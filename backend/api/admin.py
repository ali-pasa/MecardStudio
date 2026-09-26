import json
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.urls import path
from django.shortcuts import render
from django.template.response import TemplateResponse

from .audit import apply_request_audit
from .models import (
    Card,
    CardCategory,
    Company,
    CompanyBrandPreference,
    Role,
    User,
)


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
    list_display = ("name", "company", "category", "is_active", "updated_at")
    list_filter = ("is_active", "category", "updated_at")
    search_fields = ("name", "public_slug", "company__company_name")
    list_select_related = ("company", "category")
