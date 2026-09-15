from rest_framework import serializers
from .models import User, Role, Company, Card, CompanyBrandPreference


class UserSerializer(serializers.ModelSerializer):
    role = serializers.CharField(write_only=True, required=False)
    role_name = serializers.CharField(source='role.name', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password', 'role', 'role_name']
        extra_kwargs = {
            'password': {'write_only': True, 'style': {'input_type': 'password'}}
        }

    def create(self, validated_data):
        role_name = validated_data.pop('role', None)
        password = validated_data.pop('password', None)

        user = User(**validated_data)

        if password:
            user.set_password(password)
        else:
            raise serializers.ValidationError({"password": "Password is required."})

        if role_name:
            role_obj, _ = Role.objects.get_or_create(name=role_name.strip())
            user.role = role_obj

        user.save()
        return user


class CompanyBrandPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyBrandPreference
        fields = [
            "logo_url", "primary_color", "secondary_color", "accent_color",
            "font_family", "brand_style", "background_style",
        ]


class CompanySerializer(serializers.ModelSerializer):
    # Everything except website_url is filled in AUTOMATICALLY by extraction —
    # the client never sends these, so they're read-only in the API.
    brand_preference = CompanyBrandPreferenceSerializer(read_only=True)

    class Meta:
        model = Company
        fields = [
            'id', 'user', 'website_url', 'ip_address',
            'company_name', 'tagline', 'about', 'industry',
            'address', 'phone', 'email', 'website',
            'linkedin_url', 'instagram_url', 'facebook_url',
            'youtube_url', 'twitter_url',
            'brand_preference',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'user', 'company_name', 'tagline', 'about', 'industry',
            'address', 'phone', 'email', 'website',
            'linkedin_url', 'instagram_url', 'facebook_url',
            'youtube_url', 'twitter_url',
            'created_at', 'updated_at',
        ]
        # Only website_url and ip_address remain writable by the client


class CardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Card
        fields = [
            "id", "company", "category", "name",
            "html_content", "public_slug", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["html_content", "public_slug"]