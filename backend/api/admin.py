from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

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


@admin.register(CompanyBrandPreference)
class CompanyBrandPreferenceAdmin(admin.ModelAdmin):
    list_display = ("company", "font_family", "brand_style", "updated_at")
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
