"""
URL configuration for Check-in app.
"""
from django.urls import path
from .views import (
    CheckinByTokenView,
    ManualCheckinView,
    EventStatsView,
    RegistrationSearchView,
)

app_name = 'checkin'

urlpatterns = [
    path('', CheckinByTokenView.as_view(), name='checkin-by-token'),
    path('manual/', ManualCheckinView.as_view(), name='checkin-manual'),
    path('stats/', EventStatsView.as_view(), name='event-stats'),
    path('search/', RegistrationSearchView.as_view(), name='registration-search'),
]
