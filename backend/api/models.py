from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


# ------------------------------------------------------------
# Role
# ------------------------------------------------------------

class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        db_table = "roles"

    def __str__(self):
        return self.name


# ------------------------------------------------------------
# User
# ------------------------------------------------------------

class User(AbstractUser):
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.username


# ------------------------------------------------------------
# Company
# ------------------------------------------------------------

class Company(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="companies",
    )

    # Website submitted for extraction
    website_url = models.URLField(max_length=500)

    # IP address from which the company was created
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    # Company information
    company_name = models.CharField(max_length=255, null=True, blank=True)
    tagline = models.CharField(max_length=255, null=True, blank=True)
    about = models.TextField(null=True, blank=True)
    industry = models.CharField(max_length=150, null=True, blank=True)
    address = models.CharField(max_length=500, null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)
    website = models.URLField(max_length=500, null=True, blank=True)

    # Social links
    linkedin_url = models.URLField(max_length=500, null=True, blank=True)
    instagram_url = models.URLField(max_length=500, null=True, blank=True)
    facebook_url = models.URLField(max_length=500, null=True, blank=True)
    youtube_url = models.URLField(max_length=500, null=True, blank=True)
    twitter_url = models.URLField(max_length=500, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "companies"
        verbose_name_plural = "Companies"
        indexes = [
            models.Index(fields=["user"]),
        ]

    def __str__(self):
        return self.company_name or self.website_url


# ------------------------------------------------------------
# Company Brand Preference
# ------------------------------------------------------------

class CompanyBrandPreference(models.Model):
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="brand_preference",
    )

    logo_url = models.URLField(max_length=500, null=True, blank=True)
    primary_color = models.CharField(max_length=7, null=True, blank=True)
    secondary_color = models.CharField(max_length=7, null=True, blank=True)
    accent_color = models.CharField(max_length=7, null=True, blank=True)
    font_family = models.CharField(max_length=150, null=True, blank=True)
    brand_style = models.CharField(max_length=100, null=True, blank=True)
    background_style = models.CharField(max_length=100, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "company_brand_preferences"
        verbose_name_plural = "Company brand preferences"

    def __str__(self):
        return f"Brand Preference - {self.company}"

# ------------------------------------------------------------
# Card Category
# ------------------------------------------------------------

class CardCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)

    required_fields = models.JSONField(
        default=list,
        blank=True,
    )

    default_aspect_ratio = models.CharField(
        max_length=20,
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "card_categories"
        verbose_name_plural = "Card categories"

    def __str__(self):
        return self.name


# ------------------------------------------------------------
# Card
# ------------------------------------------------------------

class Card(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="cards",
    )

    category = models.ForeignKey(
        CardCategory,
        on_delete=models.PROTECT,
        related_name="cards",
    )

    name = models.CharField(max_length=255)

    html_content = models.TextField()

    public_slug = models.SlugField(
        max_length=150,
        unique=True,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cards"
        indexes = [
            models.Index(fields=["company"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        return self.name