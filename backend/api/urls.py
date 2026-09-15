# api/urls.py

from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, CompanyViewSet, CardViewSet

router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")
router.register(r"companies", CompanyViewSet, basename="company")
router.register(r"cards", CardViewSet, basename="card")

urlpatterns = [
    path("", include(router.urls)),
]