"""
URL configuration for Registrations app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import RegistrationViewSet, CancelByTokenView

router = DefaultRouter()
router.register(r'', RegistrationViewSet, basename='registration')

urlpatterns = [
    path('cancel/', CancelByTokenView.as_view(), name='cancel-by-token'),
    path('', include(router.urls)),
]
