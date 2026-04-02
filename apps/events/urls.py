"""
URL configuration for Events app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EventViewSet, PublicEventBySlugView

app_name = 'events'

router = DefaultRouter()
router.register(r'', EventViewSet, basename='event')

urlpatterns = [
    path('public/<path:slug_with_id>/', PublicEventBySlugView.as_view(), name='public-event-by-slug'),
    path('', include(router.urls)),
]
