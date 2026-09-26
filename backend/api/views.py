# api/views.py

import uuid
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
from .services.card_generation import generate_card_template, render_preview_html, encode_uploaded_image_to_data_uri

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

        # Don't create a duplicate if this user already has a company with this URL
        company, created = Company.objects.get_or_create(
            user=user,
            website_url=website_url,
            defaults=request_audit_values(request, creating=True),
        )

        try:
            extracted = run_full_extraction(website_url)
        except Exception as e:
            # Company row exists but extraction failed — still return it,
            # just without extracted data, so the client knows what happened.
            serialized = self.get_serializer(company)
            return Response(
                {"company": serialized.data, "error": f"Extraction failed: {str(e)}"},
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
        company.website = website_url
        company.linkedin_url = social.get("linkedin_url") or company.linkedin_url
        company.instagram_url = social.get("instagram_url") or company.instagram_url
        company.facebook_url = social.get("facebook_url") or company.facebook_url
        company.youtube_url = social.get("youtube_url") or company.youtube_url
        company.twitter_url = social.get("twitter_url") or company.twitter_url
        apply_request_audit(company, request, creating=False)
        company.save()

        self._save_brand_preference(company, brand)

        serialized = self.get_serializer(company)
        return Response(
            serialized.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def _save_brand_preference(self, company, brand):
        brand_values = {
            "logo_url": brand.get("logo_url"),
            "primary_color": brand.get("primary_color"),
            "secondary_color": brand.get("secondary_color"),
            "accent_color": brand.get("accent_color"),
        }
        preference, created = CompanyBrandPreference.objects.get_or_create(
            company=company,
            defaults={**brand_values, **request_audit_values(self.request, creating=True)},
        )
        if not created:
            for field, value in brand_values.items():
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


class CardViewSet(RequestAuditViewSetMixin, viewsets.ModelViewSet):
    queryset = Card.objects.all().select_related("company", "category")
    serializer_class = CardSerializer

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        company_id = request.data.get("company_id")
        category_slug = request.data.get("category_slug")
        name = request.data.get("name", "Untitled Card")
        variant_count = int(request.data.get("variant_count", 3))
        variant_count = max(1, min(variant_count, 6))
        user_prompt = request.data.get("user_prompt")

        reference_image_url = None
        uploaded_file = request.FILES.get("reference_image")
        if uploaded_file:
            reference_image_url = encode_uploaded_image_to_data_uri(uploaded_file)

        try:
            company = Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            return Response({"error": "Company not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            category = CardCategory.objects.get(slug=category_slug)
        except CardCategory.DoesNotExist:
            return Response({"error": "Card category not found."}, status=status.HTTP_404_NOT_FOUND)

        brand = getattr(company, "brand_preference", None)

        variant_instructions = [None]
        for i in range(2, variant_count + 1):
            variant_instructions.append(
                f"Design a visually DISTINCT alternative (variant {i} of {variant_count}) — "
                f"different composition/layout/style than the previous variants, still using the same brand colors."
            )

        created_cards = []
        for i, instruction in enumerate(variant_instructions, start=1):
            try:
                html = generate_card_template(
                    company, brand, category,
                    extra_instruction=instruction,
                    user_prompt=user_prompt,
                    reference_image_url=reference_image_url,
                )
            except Exception as e:
                return Response({"error": f"Template generation failed on variant {i}: {str(e)}"}, status=status.HTTP_502_BAD_GATEWAY)

            public_slug = f"{slugify(name)}-v{i}-{uuid.uuid4().hex[:8]}"
            card = Card.objects.create(
                company=company, category=category, name=f"{name} (Variant {i})",
                html_content=html, public_slug=public_slug, is_active=(i == 1),
                **request_audit_values(request, creating=True),
            )
            created_cards.append(card)

        serialized = CardSerializer(created_cards, many=True).data
        for item, card in zip(serialized, created_cards):
            item["preview_html"] = render_preview_html(card.html_content, category)

        return Response({"variants": serialized}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="preview")
    def preview(self, request, pk=None):
        """
        GET /api/cards/{id}/preview/
        Returns the card's HTML with demo data filled in, for display.
        """
        card = self.get_object()
        preview_html = render_preview_html(card.html_content, card.category)
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