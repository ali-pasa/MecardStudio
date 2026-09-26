import json
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.urls import path
from django.shortcuts import render
from django.template.response import TemplateResponse

from .models import (
    Card,
    CardCategory,
    Company,
    CompanyBrandPreference,
    Role,
    User,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
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
        ("Access profile", {"fields": ("role",)}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Access profile", {"fields": ("role",)}),
    )


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "user_count")
    list_filter = ("name",)
    search_fields = ("name",)

    @admin.display(description="Users")
    def user_count(self, obj):
        return obj.users.count()


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("company_name", "user", "industry", "created_at")
    list_filter = ("industry", "created_at")
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
class CompanyBrandPreferenceAdmin(admin.ModelAdmin):
    list_display = ("company", "font_family", "brand_style", "updated_at")
    list_filter = ("company", "font_family", "brand_style", "updated_at")
    search_fields = ("company__company_name", "font_family", "brand_style")


@admin.register(CardCategory)
class CardCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "default_aspect_ratio")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "category", "is_active", "updated_at")
    list_filter = ("is_active", "category", "updated_at")
    search_fields = ("name", "public_slug", "company__company_name")
    list_select_related = ("company", "category")
