import json
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.urls import path, reverse
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.utils.html import format_html
from django.template.response import TemplateResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin

from .audit import apply_request_audit
from .models import (
    Card,
    CardCategory,
    Company,
    CompanyBrandPreference,
    Role,
    User,
)
from .services.card_generation import category_for_card_orientation, render_preview_html


class GroupAdmin(BaseGroupAdmin):
    list_filter = ("permissions__content_type",)


admin.site.unregister(Group)
admin.site.register(Group, GroupAdmin)


class AuditAdminMixin:
    audit_readonly_fields = (
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "ip_address",
    )

    def get_readonly_fields(self, request, obj=None):
        return (*super().get_readonly_fields(request, obj), *self.audit_readonly_fields)

    def save_model(self, request, obj, form, change):
        apply_request_audit(obj, request, creating=not change)
        super().save_model(request, obj, form, change)


@admin.register(User)
class UserAdmin(AuditAdminMixin, BaseUserAdmin):
    """User master with fast search, status filters and role filtering."""

    list_display = (
        "username",
        "full_name",
        "email",
        "role",
        "status_badge",
        "is_staff",
        "last_login",
    )
    list_filter = ("is_active", "is_staff", "is_superuser", "role", "date_joined")
    search_fields = ("username", "first_name", "last_name", "email")
    ordering = ("-date_joined",)
    list_select_related = ("role",)
    list_per_page = 25
    date_hierarchy = "date_joined"

    @admin.display(description="Name", ordering="first_name")
    def full_name(self, obj):
        return obj.get_full_name() or "—"

    @admin.display(description="Status", boolean=True, ordering="is_active")
    def status_badge(self, obj):
        return obj.is_active

    fieldsets = BaseUserAdmin.fieldsets + (
        ("Access profile", {"fields": ("role", "meta_data")}),
        ("Audit information", {"fields": AuditAdminMixin.audit_readonly_fields}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Access profile", {"fields": ("role", "is_active", "meta_data")}),
        ("Audit information", {"fields": AuditAdminMixin.audit_readonly_fields}),
    )


@admin.register(Role)
class RoleAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("name", "is_active", "user_count")
    list_filter = ("is_active", "name")
    search_fields = ("name",)

    @admin.display(description="Users")
    def user_count(self, obj):
        return obj.users.count()


@admin.register(Company)
class CompanyAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("company_name", "user", "industry", "is_active", "created_at")
    list_filter = ("industry", "is_active", "created_at")
    search_fields = ("company_name", "website_url", "email", "user__username")
    date_hierarchy = "created_at"
    list_select_related = ("user",)

    change_list_template = "admin/api/company/change_list.html"
    change_form_template = "admin/api/company/change_form.html"

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "create-from-url/",
                self.admin_site.admin_view(self.create_from_url_view),
                name="api_company_create_from_url",
            ),
        ]
        return custom_urls + urls

    def create_from_url_view(self, request):
        context = {
            **self.admin_site.each_context(request),
            "title": "Add company from URL",
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/api/company/create_from_url.html", context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        categories = CardCategory.objects.filter(is_active=True).order_by("name").values(
            "id", "name", "slug", "required_fields", "default_aspect_ratio"
        )
        extra_context = extra_context or {}
        extra_context["card_categories"] = list(categories)
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

@admin.register(CompanyBrandPreference)
class CompanyBrandPreferenceAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("company", "font_family", "brand_style", "is_active", "updated_at")
    list_filter = ("company", "font_family", "brand_style", "is_active", "updated_at")
    search_fields = ("company__company_name", "font_family", "brand_style")


@admin.register(CardCategory)
class CardCategoryAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "default_aspect_ratio")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")


@admin.register(Card)
class CardAdmin(AuditAdminMixin, admin.ModelAdmin):
    list_display = ("name", "preview_button", "company", "category", "is_active", "updated_at")
    list_filter = ("is_active", "category", "updated_at")
    search_fields = ("name", "public_slug", "company__company_name")
    list_select_related = ("company", "category")
    change_list_template = "admin/api/card/change_list.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/preview/",
                self.admin_site.admin_view(self.preview_view),
                name="api_card_preview",
            ),
        ]
        return custom_urls + urls

    @xframe_options_sameorigin
    def preview_view(self, request, object_id):
        if not self.has_view_permission(request):
            return HttpResponseForbidden()

        card = self.get_object(request, object_id)
        if card is None:
            raise Http404

        metadata = card.meta_data if isinstance(card.meta_data, dict) else {}
        orientation = metadata.get("orientation")
        preview_category = category_for_card_orientation(card.category, orientation)
        preview_html = render_preview_html(card.html_content, preview_category, card.company)
        return HttpResponse(preview_html, content_type="text/html; charset=utf-8")

    @admin.display(description="Preview")
    def preview_button(self, obj):
        metadata = obj.meta_data if isinstance(obj.meta_data, dict) else {}
        return format_html(
            '<button type="button" class="card-preview-trigger" '
            'data-preview-url="{}" data-card-name="{}" '
            'data-aspect-ratio="{}">Preview</button>',
            reverse("admin:api_card_preview", args=[obj.pk]),
            obj.name,
            metadata.get("aspect_ratio") or obj.category.default_aspect_ratio,
        )
