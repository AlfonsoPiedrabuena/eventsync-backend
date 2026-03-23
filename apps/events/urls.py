"""
URL configuration for Events app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EventViewSet

app_name = 'events'

router = DefaultRouter()
router.register(r'', EventViewSet, basename='event')

urlpatterns = [
    path('', include(router.urls)),
]
