# api/views.py

import uuid
from django.core import signing
from django.db import transaction
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from django.utils import timezone

from .audit import apply_request_audit, get_request_ip, request_audit_values
from .models import User, Company, CompanyBrandPreference, Card, CardCategory
from .serializers import UserSerializer, CompanySerializer, CardSerializer
from .services.extraction import run_full_extraction
from .services.card_generation import (
    CARD_DESIGN_DIRECTIONS,
    encode_uploaded_image_to_data_uri,
    ensure_card_styling,
    generate_card_template,
    is_renderable_card_template,
    render_mock_card_template,
    render_preview_html,
    category_for_card_orientation,
    card_fields_for_category,
    card_placeholder,
)

class RequestAuditViewSetMixin:
    def perform_create(self, serializer):
        serializer.save(**request_audit_values(self.request, creating=True))

    def perform_update(self, serializer):
        serializer.save(**request_audit_values(self.request))


class UserViewSet(RequestAuditViewSetMixin, viewsets.ModelViewSet):
    queryset = User.objects.all().select_related('role')
    serializer_class = UserSerializer


class CompanyViewSet(RequestAuditViewSetMixin, viewsets.ModelViewSet):
    queryset = Company.objects.all().select_related('user', 'brand_preference')
    serializer_class = CompanySerializer

    def create(self, request, *args, **kwargs):
        """
        POST /api/companies/
        Body: { "website_url": "https://example.com" }

        Creates the Company AND immediately runs extraction to populate
        every other field — no manual entry of company_name etc.
        """
        website_url = request.data.get("website_url")
        if not website_url:
            return Response(
                {"error": "website_url is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # TODO: replace with request.user once auth is wired up
        UserModel = get_user_model()
        user = UserModel.objects.first()
        if not user:
            return Response(
                {"error": "No users found. Create a user first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            extracted = run_full_extraction(website_url)
        except Exception as e:
            return Response(
                {"error": f"Extraction failed: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        info = extracted["company_info"]
        social = extracted["social_links"]
        brand = extracted["brand"]

        company_values = {
            "company_name": info.get("company_name") or "",
            "tagline": info.get("tagline") or "",
            "about": info.get("about") or "",
            "industry": info.get("industry") or "",
            "address": info.get("address") or "",
            "phone": info.get("phone") or "",
            "email": info.get("email") or "",
            "website": website_url,
            "linkedin_url": social.get("linkedin_url") or "",
            "instagram_url": social.get("instagram_url") or "",
            "facebook_url": social.get("facebook_url") or "",
            "youtube_url": social.get("youtube_url") or "",
            "twitter_url": social.get("twitter_url") or "",
        }

        # Create only after extraction succeeds, with extracted values already
        # in the insert so a failed fetch cannot leave behind an empty company.
        company, created = Company.objects.get_or_create(
            user=user,
            website_url=website_url,
            defaults={
                **company_values,
                **request_audit_values(request, creating=True),
            },
        )

        if not created:
            for field, value in company_values.items():
                if value:
                    setattr(company, field, value)
            apply_request_audit(company, request, creating=False)
            company.save()

        self._save_brand_preference(company, brand)

        serialized = self.get_serializer(company)
        return Response(
            serialized.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def _save_brand_preference(self, company, brand):
        preference, created = CompanyBrandPreference.objects.get_or_create(
            company=company,
            defaults={
                **{
                    field: brand.get(field)
                    for field in ("logo_url", "primary_color", "secondary_color", "accent_color")
                    if brand.get(field)
                },
                **request_audit_values(self.request, creating=True),
            },
        )
        if not created:
            for field in ("logo_url", "primary_color", "secondary_color", "accent_color"):
                value = brand.get(field)
                if value:
                    setattr(preference, field, value)
            apply_request_audit(preference, self.request, creating=False)
            preference.save()
        return preference

    @action(detail=True, methods=["post"], url_path="refresh")
    def refresh(self, request, pk=None):
        """
        POST /api/companies/{id}/refresh/
        Re-runs extraction on an existing company (e.g. site content changed).
        """
        company = self.get_object()

        try:
            extracted = run_full_extraction(company.website_url)
        except Exception as e:
            return Response(
                {"error": f"Extraction failed: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        info = extracted["company_info"]
        social = extracted["social_links"]
        brand = extracted["brand"]

        company.company_name = info.get("company_name") or company.company_name
        company.tagline = info.get("tagline") or company.tagline
        company.about = info.get("about") or company.about
        company.industry = info.get("industry") or company.industry
        company.address = info.get("address") or company.address
        company.phone = info.get("phone") or company.phone
        company.email = info.get("email") or company.email
        company.linkedin_url = social.get("linkedin_url") or company.linkedin_url
        company.instagram_url = social.get("instagram_url") or company.instagram_url
        company.facebook_url = social.get("facebook_url") or company.facebook_url
        company.youtube_url = social.get("youtube_url") or company.youtube_url
        company.twitter_url = social.get("twitter_url") or company.twitter_url
        apply_request_audit(company, request, creating=False)
        company.save()

        self._save_brand_preference(company, brand)

        serialized = self.get_serializer(company)
        return Response(serialized.data, status=status.HTTP_200_OK)


class CardViewSet(viewsets.ModelViewSet):
    queryset = Card.objects.all().select_related("company", "category")
    serializer_class = CardSerializer

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        """Generate card previews; save them only after user selection."""
        company_id = request.data.get("company_id")
        category_slug = request.data.get("category_slug")
        orientation = request.data.get("orientation", "horizontal")
        user_prompt = (request.data.get("user_prompt") or "").strip()

        if orientation not in ("horizontal", "vertical"):
            return Response(
                {"error": "Orientation must be horizontal or vertical."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            variant_count = int(request.data.get("variant_count", 3))
        except (TypeError, ValueError):
            return Response(
                {"error": "variant_count must be a number between 1 and 6."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not 1 <= variant_count <= 6:
            return Response(
                {"error": "Choose between 1 and 6 variants."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            company = Company.objects.get(pk=company_id)
        except (Company.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Company not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            category = CardCategory.objects.get(slug=category_slug)
        except CardCategory.DoesNotExist:
            return Response({"error": "Card category not found."}, status=status.HTTP_404_NOT_FOUND)

        generation_category = category_for_card_orientation(category, orientation)
        brand = getattr(company, "brand_preference", None)
        reference_image_url = None
        uploaded_file = request.FILES.get("reference_image")
        if uploaded_file:
            try:
                reference_image_url = encode_uploaded_image_to_data_uri(uploaded_file)
            except Exception as exc:
                return Response(
                    {"error": f"Could not process reference image: {exc}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        variants = []
        generation_notice = None
        quota_exhausted = False
        required_fields = card_fields_for_category(generation_category, company)

        for index in range(variant_count):
            design = CARD_DESIGN_DIRECTIONS[index % len(CARD_DESIGN_DIRECTIONS)]
            fallback_direction = design["key"]

            if quota_exhausted:
                html = render_mock_card_template(
                    company, brand, generation_category, fallback_direction
                )
            else:
                if reference_image_url:
                    direction = (
                        "Use the attached card as the visual reference. Preserve its palette, "
                        "composition, typography character, and element placement while "
                        "replacing sample data with the required placeholders. Ignore "
                        "screenshot frames and page margins."
                    )
                else:
                    direction = f"Design direction: {design['label']}. {design['instruction']}"
                instruction = (
                    f"Create option {index + 1} of {variant_count}. {direction} "
                    f"Use a {orientation} layout. Return only the finished card HTML."
                )
                try:
                    html = generate_card_template(
                        company=company,
                        brand=brand,
                        category=generation_category,
                        extra_instruction=instruction,
                        user_prompt=user_prompt,
                        reference_image_url=reference_image_url,
                        # The direction is already included above. Avoid appending
                        # the service's long duplicate direction block.
                        design_direction=None,
                    )
                except Exception as exc:
                    error_text = str(exc)
                    is_quota_error = (
                        getattr(exc, "status_code", None) == 429
                        or "429" in error_text
                        or "RESOURCE_EXHAUSTED" in error_text.upper()
                        or "RATE_LIMIT" in error_text.upper()
                    )
                    if not is_quota_error:
                        return Response(
                            {"error": f"Card generation failed: {error_text}"},
                            status=status.HTTP_502_BAD_GATEWAY,
                        )
                    quota_exhausted = True
                    generation_notice = (
                        "Gemini's request limit has been reached. This and the remaining "
                        "options use local designs; try AI generation again after the "
                        "limit resets."
                    )
                    html = render_mock_card_template(
                        company, brand, generation_category, fallback_direction
                    )

            missing_fields = [
                field for field in required_fields
                if card_placeholder(field) not in html
            ]
            if missing_fields or not is_renderable_card_template(html, required_fields):
                html = render_mock_card_template(
                    company, brand, generation_category, fallback_direction
                )

            html = ensure_card_styling(html, generation_category)
            variant_name = f"{request.data.get('name') or 'Untitled Card'} (Variant {index + 1})"
            preview_token = signing.TimestampSigner(salt="api.card-preview").sign_object({
                "company_id": company.pk,
                "category_id": category.pk,
                "name": variant_name,
                "html_content": html,
                "orientation": orientation,
            })
            variants.append({
                "id": f"variant-{uuid.uuid4().hex}",
                "index": index,
                "name": variant_name,
                "preview_token": preview_token,
                "html_content": html,
                "preview_html": render_preview_html(html, generation_category, company),
                "orientation": orientation,
                "aspect_ratio": generation_category.default_aspect_ratio,
                "design_key": fallback_direction,
                "design_label": design["label"],
            })

        return Response(
            {
                "variants": variants,
                "orientation": orientation,
                "category": category.slug,
                "generation_notice": generation_notice,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="save")
    def save(self, request):
        company_id = request.data.get("company_id")
        category_slug = request.data.get("category_slug")
        name = (request.data.get("name") or "Untitled Card").strip()
        html_content = request.data.get("html_content")
        if not html_content:
            return Response({"error": "html_content is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            company = Company.objects.get(pk=company_id)
            category = CardCategory.objects.get(slug=category_slug)
        except (Company.DoesNotExist, CardCategory.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Company or card category not found."}, status=status.HTTP_404_NOT_FOUND)

        card = Card.objects.create(
            company=company,
            category=category,
            name=name,
            html_content=html_content,
            public_slug=f"{slugify(name) or 'card'}-{uuid.uuid4().hex[:8]}",
            is_active=True,
            **request_audit_values(request, creating=True),
        )
        return Response(self.get_serializer(card).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="edit")
    def edit(self, request, pk=None):
        card = self.get_object()
        instruction = (request.data.get("instruction") or "").strip()
        if not instruction:
            return Response({"error": "instruction is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            html = generate_card_template(
                card.company,
                getattr(card.company, "brand_preference", None),
                card.category,
                extra_instruction=instruction,
                previous_html=card.html_content,
            )
        except Exception as exc:
            return Response({"error": f"Edit failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        card.html_content = html
        card.save(update_fields=["html_content"])
        return Response(self.get_serializer(card).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="regenerate")
    def regenerate(self, request, pk=None):
        card = self.get_object()
        try:
            html = generate_card_template(
                card.company,
                getattr(card.company, "brand_preference", None),
                card.category,
                extra_instruction=(
                    "Create a substantially different professional card design. "
                    "Change its composition, layout, element placement, typography, "
                    "and decorative treatment. Do not simply recolor it."
                ),
                previous_html=card.html_content,
            )
        except Exception as exc:
            return Response({"error": f"Regeneration failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        card.html_content = html
        card.save(update_fields=["html_content"])
        return Response(self.get_serializer(card).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="save-generated")
    def save_generated(self, request):
        """Save all selected generated previews after the user confirms them."""
        preview_tokens = request.data.get("preview_tokens")
        if (
            not isinstance(preview_tokens, list)
            or not preview_tokens
            or len(preview_tokens) > 6
            or any(not isinstance(token, str) or not token for token in preview_tokens)
        ):
            return Response(
                {"error": "Select between 1 and 6 generated card previews to save."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(set(preview_tokens)) != len(preview_tokens):
            return Response(
                {"error": "Each selected card preview must be unique."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        signer = signing.TimestampSigner(salt="api.card-preview")
        previews = []
        try:
            for preview_token in preview_tokens:
                preview = signer.unsign_object(preview_token, max_age=3600)
                if not isinstance(preview, dict):
                    raise ValueError("Invalid card preview.")
                previews.append(preview)
        except (signing.BadSignature, signing.SignatureExpired, ValueError):
            return Response(
                {"error": "A card preview is invalid or expired. Generate the options again to save them."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        company_ids = {preview.get("company_id") for preview in previews}
        category_ids = {preview.get("category_id") for preview in previews}
        if len(company_ids) != 1 or len(category_ids) != 1:
            return Response(
                {"error": "Selected previews must belong to the same company and card category."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            company = Company.objects.get(pk=company_ids.pop())
            category = CardCategory.objects.get(pk=category_ids.pop())
        except (Company.DoesNotExist, CardCategory.DoesNotExist, TypeError, ValueError):
            return Response(
                {"error": "A selected card preview is invalid. Generate the options again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cards_to_create = []
        for preview in previews:
            name = preview.get("name")
            html_content = preview.get("html_content")
            if not all(isinstance(value, str) and value for value in (name, html_content)):
                return Response(
                    {"error": "A selected card preview is invalid. Generate the options again."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            cards_to_create.append(Card(
                company=company,
                category=category,
                name=name,
                html_content=html_content,
                public_slug=f"{slugify(name)}-{uuid.uuid4().hex[:8]}",
                meta_data={
                    "orientation": preview.get("orientation", "horizontal"),
                    "aspect_ratio": (
                        "1:1.6"
                        if preview.get("orientation") == "vertical"
                        else "1.6:1"
                    ),
                },
                is_active=True,
                **request_audit_values(request, creating=True),
            ))

        with transaction.atomic():
            Card.objects.filter(company=company, category=category).update(
                is_active=False,
                updated_at=timezone.now(),
                updated_by=request.user if request.user.is_authenticated else None,
                ip_address=get_request_ip(request),
            )
            cards = []
            for card in cards_to_create:
                card.save(force_insert=True)
                cards.append(card)

        return Response(
            {"cards": CardSerializer(cards, many=True).data},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="preview")
    def preview(self, request, pk=None):
        """
        GET /api/cards/{id}/preview/
        Returns the card's HTML with demo data filled in, for display.
        """
        card = self.get_object()
        metadata = card.meta_data if isinstance(card.meta_data, dict) else {}
        preview_category = category_for_card_orientation(
            card.category,
            metadata.get("orientation"),
        )
        preview_html = render_preview_html(card.html_content, preview_category, card.company)
        return Response({"preview_html": preview_html})

    @action(detail=True, methods=["post"], url_path="select")
    def select(self, request, pk=None):
        """
        POST /api/cards/{id}/select/
        Marks this variant as the active one, deactivates sibling variants
        from the same generation batch (same company + category + is_active group).
        """
        card = self.get_object()
        Card.objects.filter(company=card.company, category=card.category).update(
            is_active=False,
            updated_at=timezone.now(),
            updated_by=request.user if request.user.is_authenticated else None,
            ip_address=get_request_ip(request),
        )
        card.is_active = True
        apply_request_audit(card, request, creating=False)
        card.save()
        serialized = self.get_serializer(card)
        return Response(serialized.data)
