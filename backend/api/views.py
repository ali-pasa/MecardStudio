# api/views.py

import uuid
import random
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
    render_preview_html,
    category_for_card_orientation,
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
        """
        POST /api/cards/generate/

        Generates multiple DISTINCT card design variants.

        Nothing is saved to the database at this stage.
        """

        company_id = request.data.get("company_id")
        category_slug = request.data.get("category_slug")
        orientation = request.data.get("orientation", "horizontal")
        user_prompt = request.data.get("user_prompt") or ""
        
        try:
            variant_count = int(request.data.get("variant_count", 3))
        except (TypeError, ValueError):
            variant_count = 3

        variant_count = max(1, min(variant_count, 6))

        if not company_id:
            return Response(
                {"error": "company_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not category_slug:
            return Response(
                {"error": "category_slug is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ---------------------------------------------------------
        # Reference image
        # ---------------------------------------------------------

        reference_image_url = None

        uploaded_file = request.FILES.get("reference_image")

        if uploaded_file:
            try:
                reference_image_url = encode_uploaded_image_to_data_uri(
                    uploaded_file
                )
            except Exception as exc:
                return Response(
                    {
                        "error": (
                            "Could not process the reference image: "
                            f"{str(exc)}"
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ---------------------------------------------------------
        # Company
        # ---------------------------------------------------------

        try:
            company = Company.objects.get(pk=company_id)
        except Company.DoesNotExist:
            return Response(
                {"error": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ---------------------------------------------------------
        # Category
        # ---------------------------------------------------------

        try:
            category = CardCategory.objects.get(slug=category_slug)
        except CardCategory.DoesNotExist:
            return Response(
                {"error": "Card category not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Apply requested orientation to the category.
        category = category_for_card_orientation(
            category,
            orientation,
        )

        brand = getattr(company, "brand_preference", None)

        # ---------------------------------------------------------
        # Generate variants
        # ---------------------------------------------------------

        results = []

        for index in range(variant_count):

            # Without a reference, use distinct curated directions. With a
            # reference, its own layout and palette take priority instead.
            design = (
                CARD_DESIGN_DIRECTIONS[index % len(CARD_DESIGN_DIRECTIONS)]
                if not reference_image_url else None
            )
            design_direction = design["key"] if design else None

            if reference_image_url:
                variant_instruction = f"""
REFERENCE-LED VARIANT {index + 1} OF {variant_count}

The attached image is the visual source of truth. Preserve its design
closely; do not apply a preset card style or invent a new composition.
If it contains multiple separate card designs, reproduce card {index + 1}
when counting from left to right. If it contains only one design, reproduce
that same layout for every variant and make only restrained variations to
small decorative details. Preserve the reference's colors, layout geometry,
portrait treatment, information grouping, typography character, and footer
or QR placement. Replace sample identity text with the required placeholder
tokens and use the provided company identity.

Do not copy phone frames or screenshot/page margins. Return only the card.
Keep every required field legible and aligned within the requested card size.
""".strip()
            else:
                variant_instruction = (
                    f"""
VARIANT {index + 1} OF {variant_count}

This variant MUST be visually different from the other variants.

DESIGN DIRECTION:
{design["label"]}

{design["instruction"]}

IMPORTANT:
- Do NOT reuse the same composition.
- Do NOT simply change colors.
- Do NOT return the same layout with minor spacing changes.
- Change the actual placement and grouping of elements.
- Change the visual hierarchy.
- Change the position of the portrait/photo.
- Change the position of the QR code.
- Change the header/footer treatment.
- Change the information layout.
- Keep the same company branding.
- Keep all required placeholder fields.
- Keep the card dimensions and requested orientation.
"""
                ).strip()

            try:
                html = generate_card_template(
                    company=company,
                    brand=brand,
                    category=category,
                    extra_instruction=variant_instruction,
                    user_prompt=user_prompt,
                    reference_image_url=reference_image_url,
                    design_direction=design_direction,
                )

            except Exception as exc:
                return Response(
                    {
                        "error": (
                            f"Template generation failed on variant "
                            f"{index + 1}: {str(exc)}"
                        )
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            # -----------------------------------------------------
            # Validate generated template
            # -----------------------------------------------------

            required_fields = category.required_fields or []

            missing_fields = []

            for field in required_fields:
                token = f"{{{{{field}}}}}"

                if token not in html:
                    missing_fields.append(field)

            # If Gemini omitted important fields, regenerate this
            # variant once with an explicit repair instruction.
            if missing_fields:

                repair_instruction = f"""
REPAIR THIS CARD DESIGN.

The previous generated HTML omitted these required placeholder fields:

{", ".join(missing_fields)}

You MUST include every missing field in the card.

Required placeholder tokens:

{", ".join(
    f"{{{{{field}}}}}"
    for field in required_fields
)}

Keep the existing visual design and improve it rather than replacing
it with a generic layout.

Do not remove any existing required placeholders.

The final HTML must contain every required placeholder exactly.
""".strip()

                try:
                    repaired_html = generate_card_template(
                        company=company,
                        brand=brand,
                        category=category,
                        extra_instruction=repair_instruction,
                        previous_html=html,
                        user_prompt=user_prompt,
                        reference_image_url=reference_image_url,
                        design_direction=design_direction,
                    )

                    html = repaired_html

                except Exception:
                    # Keep original HTML if repair fails.
                    pass

            # -----------------------------------------------------
            # Final validation
            # -----------------------------------------------------

            missing_after_repair = []

            for field in required_fields:
                token = f"{{{{{field}}}}}"

                if token not in html:
                    missing_after_repair.append(field)

            # If Gemini still failed to produce required data fields,
            # use our deterministic designed fallback for this variant.
            #
            # This guarantees the user NEVER gets an empty card.
            if missing_after_repair:
                if reference_image_url:
                    return Response(
                        {
                            "error": (
                                f"Reference-based design {index + 1} did not "
                                "include all required card fields. Please try "
                                "again or use a clearer reference image."
                            )
                        },
                        status=status.HTTP_502_BAD_GATEWAY,
                    )
                html = generate_card_template(
                    company=company,
                    brand=brand,
                    category=category,
                    extra_instruction=(
                        "Use the deterministic fallback design. "
                        "Prioritize showing every required field."
                    ),
                    user_prompt=user_prompt,
                    reference_image_url=None,
                    design_direction=design_direction,
                )

            # -----------------------------------------------------
            # Preview
            # -----------------------------------------------------

            preview_html = render_preview_html(
                html,
                category=category,
                company=company,
            )

            # IMPORTANT:
            # React needs a unique ID for every card.
            variant_id = f"variant-{uuid.uuid4().hex}"

            results.append(
                {
                    "id": variant_id,
                    "index": index,
                    "design_key": design_direction,
                    "design_label": (
                        design["label"] if design else f"Reference {index + 1}"
                    ),
                    "html_content": html,
                    "preview_html": preview_html,
                }
            )

        return Response(
            {
                "variants": results,
                "orientation": orientation,
                "category": category.slug,
            },
            status=status.HTTP_200_OK,
        )

    # =============================================================
    # SAVE
    # =============================================================

    @action(detail=False, methods=["post"], url_path="save")
    def save(self, request):
        """
        POST /api/cards/save/

        Saves one generated card.
        """

        company_id = request.data.get("company_id")
        category_slug = request.data.get("category_slug")
        name = request.data.get("name") or "Untitled Card"
        html_content = request.data.get("html_content")

        if not company_id:
            return Response(
                {"error": "company_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not category_slug:
            return Response(
                {"error": "category_slug is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not html_content:
            return Response(
                {"error": "html_content is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            company = Company.objects.get(pk=company_id)
        except Company.DoesNotExist:
            return Response(
                {"error": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            category = CardCategory.objects.get(slug=category_slug)
        except CardCategory.DoesNotExist:
            return Response(
                {"error": "Card category not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        public_slug = (
            f"{slugify(name)}-{uuid.uuid4().hex[:8]}"
        )

        card = Card.objects.create(
            company=company,
            category=category,
            name=name,
            html_content=html_content,
            public_slug=public_slug,
            is_active=True,
        )

        serialized = self.get_serializer(card)

        return Response(
            serialized.data,
            status=status.HTTP_201_CREATED,
        )

    # =============================================================
    # EDIT
    # =============================================================

    @action(detail=True, methods=["post"], url_path="edit")
    def edit(self, request, pk=None):

        card = self.get_object()

        instruction = request.data.get("instruction")

        if not instruction:
            return Response(
                {"error": "instruction is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        brand = getattr(
            card.company,
            "brand_preference",
            None,
        )

        try:
            html = generate_card_template(
                company=card.company,
                brand=brand,
                category=card.category,
                extra_instruction=instruction,
                previous_html=card.html_content,
            )

        except Exception as exc:
            return Response(
                {"error": f"Edit failed: {str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        card.html_content = html
        card.save(update_fields=["html_content"])

        serialized = self.get_serializer(card)

        return Response(
            serialized.data,
            status=status.HTTP_200_OK,
        )

    # =============================================================
    # REGENERATE
    # =============================================================

    @action(detail=True, methods=["post"], url_path="regenerate")
    def regenerate(self, request, pk=None):

        card = self.get_object()

        brand = getattr(
            card.company,
            "brand_preference",
            None,
        )

        design = CARD_DESIGN_DIRECTIONS[
            uuid.uuid4().int % len(CARD_DESIGN_DIRECTIONS)
        ]

        try:
            html = generate_card_template(
                company=card.company,
                brand=brand,
                category=card.category,
                extra_instruction=(
                    f"""
Generate a completely different design.

Use this design direction:

{design["label"]}

{design["instruction"]}

Do not reuse the existing composition.
""".strip()
                ),
                previous_html=card.html_content,
                design_direction=design["key"],
            )

        except Exception as exc:
            return Response(
                {"error": f"Regenerate failed: {str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        card.html_content = html
        card.save(update_fields=["html_content"])

        serialized = self.get_serializer(card)

        return Response(
            serialized.data,
            status=status.HTTP_200_OK,
        )
    queryset = Card.objects.all().select_related("company", "category")
    serializer_class = CardSerializer

    VARIANT_STYLES = [
        (
            "VARIANT 1 — MINIMAL EDITORIAL DESIGN: "
            "Use a clean, premium layout with generous whitespace, "
            "precise typography, a strong alignment grid, and restrained "
            "brand-color accents. Keep the information clearly organized."
        ),
        (
            "VARIANT 2 — GEOMETRIC CORPORATE DESIGN: "
            "Use a visibly different composition with asymmetric panels, "
            "geometric shapes, a contrasting information sidebar, and "
            "a strong visual hierarchy. Do not reuse the first layout."
        ),
        (
            "VARIANT 3 — BOLD MODERN DESIGN: "
            "Use a distinctive composition with a bold header, "
            "contrasting color blocks, a different information arrangement, "
            "and a visually prominent QR-code area. Do not reuse either "
            "previous layout."
        ),
        (
            "VARIANT 4 — PREMIUM LUXURY DESIGN: "
            "Use sophisticated typography, fine borders, balanced spacing, "
            "and subtle brand-color accents. Create a new composition."
        ),
        (
            "VARIANT 5 — CONTEMPORARY ASYMMETRIC DESIGN: "
            "Use an offset grid, a distinctive side panel, layered shapes, "
            "and a new arrangement of all card elements."
        ),
        (
            "VARIANT 6 — CREATIVE PROFESSIONAL DESIGN: "
            "Use a fresh visual concept, distinctive typography, "
            "intentional whitespace, and a different information hierarchy."
        ),
    ]

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        """Generate card previews without saving them to the database."""

        company_id = request.data.get("company_id")
        category_slug = request.data.get("category_slug")
        user_prompt = (request.data.get("user_prompt") or "").strip()
        orientation = request.data.get("orientation", "horizontal")

        try:
            variant_count = int(request.data.get("variant_count", 3))
        except (TypeError, ValueError):
            return Response(
                {"error": "variant_count must be a number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not 1 <= variant_count <= 6:
            return Response(
                {"error": "Choose between 1 and 6 variants."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if orientation not in ("horizontal", "vertical"):
            return Response(
                {"error": "Orientation must be horizontal or vertical."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            company = Company.objects.get(pk=company_id)
        except (Company.DoesNotExist, ValueError, TypeError):
            return Response(
                {"error": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            category = CardCategory.objects.get(slug=category_slug)
        except CardCategory.DoesNotExist:
            return Response(
                {"error": "Card category not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Read the optional uploaded reference image.
        uploaded_file = request.FILES.get("reference_image")
        reference_image_url = None

        if uploaded_file:
            try:
                reference_image_url = encode_uploaded_image_to_data_uri(
                    uploaded_file
                )
            except Exception as exc:
                return Response(
                    {"error": f"Could not process reference image: {exc}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        brand = getattr(company, "brand_preference", None)

        orientation_instruction = (
            "Create a LANDSCAPE card. Use a wide horizontal composition."
            if orientation == "horizontal"
            else "Create a PORTRAIT card. Use a tall vertical composition."
        )

        common_instructions = (
            f"Requested orientation: {orientation_instruction}\n"
            "Create a complete, polished, production-quality card design "
            "as HTML/CSS. Do not return a wireframe or a mostly empty card.\n"
            "Use the supplied company's real brand colors and identity. "
            "Preserve all required information, readable contrast, and "
            "consistent typography. Make effective use of the entire card.\n"
            "Include appropriate visual hierarchy, spacing, decorative "
            "elements, and a clear location for any required QR code.\n"
            "If a reference image is supplied, use it as visual inspiration "
            "for style, mood, colors, and composition. Do not simply copy "
            "its entire layout. Create an original design.\n"
            "Keep the required card information accurate. Do not invent "
            "personal details, company information, or QR-code content."
        )

        results = []

        for index in range(variant_count):
            style_instruction = self.VARIANT_STYLES[index]

            full_prompt = (
                f"{common_instructions}\n\n"
                f"DESIGN DIRECTION:\n{style_instruction}\n\n"
                f"ADDITIONAL USER INSTRUCTIONS:\n"
                f"{user_prompt or 'Use your best professional design judgment.'}\n\n"
                f"IMPORTANT: This is design {index + 1} of {variant_count}. "
                "Make its layout, visual hierarchy, placement of elements, "
                "and decorative treatment visibly different from the other "
                "designs. Do not merely change colors or typography."
            )

            try:
                html = generate_card_template(
                    company,
                    brand,
                    category,
                    extra_instruction=full_prompt,
                    user_prompt=user_prompt,
                    reference_image_url=reference_image_url,
                )

                preview_html = render_preview_html(html, category)

            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "Card generation failed for variant %s", index + 1
                )
                return Response(
                    {
                        "error": (
                            f"Generation failed for design {index + 1}. "
                            "Check the backend logs for details."
                        )
                    },
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            # Return the fields the frontend can actually use.
            # Each preview has a stable ID within this response.
            results.append({
                "id": str(uuid.uuid4()),
                "index": index,
                "html_content": html,
                "preview_html": preview_html,
            })

        return Response(
            {"variants": results},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="save")
    def save(self, request):
        """Save one selected design as a Card."""

        company_id = request.data.get("company_id")
        category_slug = request.data.get("category_slug")
        name = (request.data.get("name") or "Untitled Card").strip()
        html_content = request.data.get("html_content")

        if not html_content:
            return Response(
                {"error": "html_content is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            company = Company.objects.get(pk=company_id)
        except (Company.DoesNotExist, ValueError, TypeError):
            return Response(
                {"error": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            category = CardCategory.objects.get(slug=category_slug)
        except CardCategory.DoesNotExist:
            return Response(
                {"error": "Card category not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        public_slug = f"{slugify(name) or 'card'}-{uuid.uuid4().hex[:8]}"

        card = Card.objects.create(
            company=company,
            category=category,
            name=name,
            html_content=html_content,
            public_slug=public_slug,
            is_active=True,
        )

        return Response(
            self.get_serializer(card).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="edit")
    def edit(self, request, pk=None):
        card = self.get_object()
        instruction = (request.data.get("instruction") or "").strip()

        if not instruction:
            return Response(
                {"error": "instruction is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        brand = getattr(card.company, "brand_preference", None)

        try:
            html = generate_card_template(
                card.company,
                brand,
                card.category,
                extra_instruction=instruction,
                previous_html=card.html_content,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Card edit failed")
            return Response(
                {"error": "Card edit failed. Check the backend logs."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        card.html_content = html
        card.save(update_fields=["html_content"])

        return Response(
            self.get_serializer(card).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="regenerate")
    def regenerate(self, request, pk=None):
        card = self.get_object()
        brand = getattr(card.company, "brand_preference", None)

        try:
            html = generate_card_template(
                card.company,
                brand,
                card.category,
                extra_instruction=(
                    "Create a substantially different professional card "
                    "design. Change the composition, layout, placement of "
                    "elements, typography, and decorative treatment. "
                    "Do not simply recolor the previous design."
                ),
                previous_html=card.html_content,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Card regeneration failed")
            return Response(
                {"error": "Card regeneration failed. Check the backend logs."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        card.html_content = html
        card.save(update_fields=["html_content"])

        return Response(
            self.get_serializer(card).data,
            status=status.HTTP_200_OK,
        )
    queryset = Card.objects.all().select_related("company", "category")
    serializer_class = CardSerializer

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        company_id = request.data.get("company_id")
        category_slug = request.data.get("category_slug")
        orientation = request.data.get("orientation", "horizontal")
        if orientation not in ("horizontal", "vertical"):
            return Response(
                {"error": "orientation must be horizontal or vertical."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        name = request.data.get("name", "Untitled Card")
        try:
            variant_count = int(request.data.get("variant_count", 3))
        except (TypeError, ValueError):
            return Response(
                {"error": "variant_count must be a number between 1 and 6."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        variant_count = max(1, min(variant_count, 6))
        user_prompt = request.data.get("user_prompt")

        reference_image_url = None
        uploaded_file = request.FILES.get("reference_image")
        if uploaded_file:
            try:
                reference_image_url = encode_uploaded_image_to_data_uri(uploaded_file)
            except Exception as e:
                return Response(
                    {"error": f"Could not read the reference image: {e}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            company = Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            return Response({"error": "Company not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            category = CardCategory.objects.get(slug=category_slug)
        except CardCategory.DoesNotExist:
            return Response({"error": "Card category not found."}, status=status.HTTP_404_NOT_FOUND)

        generation_category = category_for_card_orientation(category, orientation)
        brand = getattr(company, "brand_preference", None)

        design_directions = random.SystemRandom().sample(
            CARD_DESIGN_DIRECTIONS,
            variant_count,
        )

        variants = []
        for i, design_direction in enumerate(design_directions, start=1):
            try:
                html = generate_card_template(
                    company, brand, generation_category,
                    extra_instruction=(
                        f"Use the {design_direction['label']} composition. "
                        "Make this option visibly different in layout, hierarchy, "
                        "and color placement from every other option in this batch. "
                        f"Use a {orientation} card orientation."
                    ),
                    user_prompt=user_prompt,
                    reference_image_url=reference_image_url,
                    design_direction=design_direction["key"],
                )
            except Exception as e:
                return Response({"error": f"Template generation failed on variant {i}: {str(e)}"}, status=status.HTTP_502_BAD_GATEWAY)

            try:
                html = ensure_card_styling(html, generation_category)
                variant_name = f"{name} (Variant {i})"
                preview_token = signing.TimestampSigner(salt="api.card-preview").sign_object({
                    "company_id": company.pk,
                    "category_id": category.pk,
                    "name": variant_name,
                    "html_content": html,
                    "orientation": orientation,
                })
                variants.append({
                    "id": f"variant-{i}",
                    "name": variant_name,
                    "preview_token": preview_token,
                    "preview_html": render_preview_html(html, generation_category, company),
                    "orientation": orientation,
                    "aspect_ratio": generation_category.default_aspect_ratio,
                })
            except Exception as e:
                return Response(
                    {"error": f"Could not prepare preview for variant {i}: {e}"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        return Response({"variants": variants}, status=status.HTTP_200_OK)

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
