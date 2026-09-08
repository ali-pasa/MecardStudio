"""
Digital ID Card Platform — Django Models (v2: clean table names + unified User)

Changes from the previous version:
1. Every model has an explicit Meta.db_table — clean snake_case names
   instead of Django's default "api_modelname" squished naming.
2. User now extends AbstractUser instead of being a separate plain model.
   This REPLACES Django's built-in auth_user table — you get one users
   table, not two. Requires AUTH_USER_MODEL = "api.User" in settings.py
   (see note at the bottom of this file).
3. Removed the manually-managed username/email/password fields on User
   since AbstractUser already provides username, email, first_name,
   last_name, password (properly hashed via Django's auth system) —
   your old `name` and `password_hash` fields are gone; only `role`
   is added on top.
"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


# ------------------------------------------------------------
# Roles
# ------------------------------------------------------------

class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)  # 'admin', 'editor', 'viewer'

    class Meta:
        db_table = "roles"

    def __str__(self):
        return self.name


# ------------------------------------------------------------
# User — replaces Django's default auth_user entirely.
# Adds `role` on top of everything AbstractUser already gives you
# (username, email, password, first_name, last_name, is_staff, etc.)
# ------------------------------------------------------------

class User(AbstractUser):
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="users", null=True, blank=True)

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.username


# ------------------------------------------------------------
# Access roles — lookup table for the Company "View Access" multiselect
# ------------------------------------------------------------

class AccessRole(models.Model):
    name = models.CharField(max_length=50, unique=True)  # 'admin', 'editor', 'viewer', 'client', 'public'

    class Meta:
        db_table = "access_roles"

    def __str__(self):
        return self.name


# ------------------------------------------------------------
# Extracted-detail tables — standalone, Company points TO these
# ------------------------------------------------------------

class BrandData(models.Model):
    logo_url = models.URLField(max_length=500, null=True, blank=True)
    primary_color = models.CharField(max_length=7, null=True, blank=True)
    secondary_color = models.CharField(max_length=7, null=True, blank=True)
    accent_color = models.CharField(max_length=7, null=True, blank=True)
    font_family = models.CharField(max_length=150, null=True, blank=True)
    brand_style = models.CharField(max_length=100, null=True, blank=True)
    background_style = models.CharField(max_length=100, null=True, blank=True)
    raw_extraction_json = models.JSONField(null=True, blank=True)
    is_reviewed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "brand_data"
        verbose_name_plural = "Brand data"

    def __str__(self):
        return f"BrandData #{self.pk}"


class CompanyInfo(models.Model):
    company_name = models.CharField(max_length=255, null=True, blank=True)
    tagline = models.CharField(max_length=255, null=True, blank=True)
    about = models.TextField(null=True, blank=True)
    industry = models.CharField(max_length=150, null=True, blank=True)
    address = models.CharField(max_length=500, null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)
    website = models.URLField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "company_info"
        verbose_name_plural = "Company info"

    def __str__(self):
        return self.company_name or f"CompanyInfo #{self.pk}"


class SocialLinks(models.Model):
    linkedin = models.URLField(max_length=500, null=True, blank=True)
    instagram = models.URLField(max_length=500, null=True, blank=True)
    facebook = models.URLField(max_length=500, null=True, blank=True)
    youtube = models.URLField(max_length=500, null=True, blank=True)
    twitter_x = models.URLField(max_length=500, null=True, blank=True)
    other_links = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "social_links"
        verbose_name_plural = "Social links"

    def __str__(self):
        return f"SocialLinks #{self.pk}"


# ------------------------------------------------------------
# Companies — holds FKs OUT to the three tables above
# ------------------------------------------------------------

class Company(models.Model):
    class ExtractionStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="companies")
    website_url = models.URLField(max_length=500)
    extraction_status = models.CharField(
        max_length=20, choices=ExtractionStatus.choices, default=ExtractionStatus.PENDING
    )
    extraction_error = models.TextField(null=True, blank=True)

    brand_data = models.OneToOneField(
        BrandData, on_delete=models.SET_NULL, null=True, blank=True, related_name="company"
    )
    company_info = models.OneToOneField(
        CompanyInfo, on_delete=models.SET_NULL, null=True, blank=True, related_name="company"
    )
    social_links = models.OneToOneField(
        SocialLinks, on_delete=models.SET_NULL, null=True, blank=True, related_name="company"
    )

    view_access_roles = models.ManyToManyField(
        AccessRole, blank=True, related_name="companies", db_table="company_view_access"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "companies"
        verbose_name_plural = "Companies"
        indexes = [models.Index(fields=["user"])]

    def __str__(self):
        return self.website_url


# ------------------------------------------------------------
# Offerings — normal ForeignKey -> Company (not flipped)
# ------------------------------------------------------------

class Offering(models.Model):
    class OfferingType(models.TextChoices):
        PRODUCT = "product", "Product"
        SERVICE = "service", "Service"
        KEY_OFFERING = "key_offering", "Key Offering"
        CATEGORY = "category", "Category"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="offerings")
    type = models.CharField(max_length=20, choices=OfferingType.choices)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "offerings"
        indexes = [models.Index(fields=["company", "type"])]

    def __str__(self):
        return self.name


# ------------------------------------------------------------
# Card categories — lookup table
# ------------------------------------------------------------

class CardCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    required_fields = models.JSONField()
    default_aspect_ratio = models.CharField(max_length=20, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "card_categories"
        verbose_name_plural = "Card categories"

    def __str__(self):
        return self.name


# ------------------------------------------------------------
# Card sessions
# ------------------------------------------------------------

class CardSession(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        GENERATING = "generating", "Generating"
        READY = "ready", "Ready"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="card_sessions")
    category = models.ForeignKey(CardCategory, on_delete=models.PROTECT, related_name="sessions")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    active_version = models.ForeignKey(
        "CardVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_for_session",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "card_sessions"
        indexes = [models.Index(fields=["company"])]

    def __str__(self):
        return f"Session #{self.pk} ({self.company})"


# ------------------------------------------------------------
# Card versions
# ------------------------------------------------------------

class CardVersion(models.Model):
    class GenerationType(models.TextChoices):
        INITIAL = "initial", "Initial"
        EDIT = "edit", "Edit"
        REGENERATE = "regenerate", "Regenerate"

    session = models.ForeignKey(CardSession, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    generation_type = models.CharField(max_length=20, choices=GenerationType.choices)
    prompt_used = models.TextField(null=True, blank=True)
    html_content = models.TextField()
    ai_model_used = models.CharField(max_length=100, null=True, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    validation_passed = models.BooleanField(default=False)
    validation_notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "card_versions"
        constraints = [
            models.UniqueConstraint(fields=["session", "version_number"], name="uq_session_version")
        ]
        indexes = [models.Index(fields=["session"])]

    def __str__(self):
        return f"v{self.version_number} of session #{self.session_id}"


# ------------------------------------------------------------
# Card exports
# ------------------------------------------------------------

class CardExport(models.Model):
    class FileType(models.TextChoices):
        PDF = "pdf", "PDF"
        PNG = "png", "PNG"

    version = models.ForeignKey(CardVersion, on_delete=models.CASCADE, related_name="exports")
    file_type = models.CharField(max_length=10, choices=FileType.choices)
    file_path = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "card_exports"
        indexes = [models.Index(fields=["version"])]

    def __str__(self):
        return f"{self.file_type} export for version #{self.version_id}"


# ------------------------------------------------------------
# Published cards
# ------------------------------------------------------------

class PublishedCard(models.Model):
    version = models.OneToOneField(CardVersion, on_delete=models.CASCADE, related_name="published")
    public_slug = models.SlugField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    view_count = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "published_cards"

    def __str__(self):
        return self.public_slug


# ==============================================================
# REQUIRED SETTINGS.PY CHANGE — add this line:
#
#     AUTH_USER_MODEL = "api.User"
#
# This tells Django to use YOUR User model for auth instead of
# creating its own auth_user table. See the migration reset steps
# in the chat response for how to apply this safely.
# ==============================================================