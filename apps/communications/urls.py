"""
URL routing for Communications app.
"""
from django.urls import path
from . import views

urlpatterns = [
    path(
        'events/<uuid:event_id>/logs/',
        views.EventEmailLogsView.as_view(),
        name='email-logs',
    ),
    path(
        'events/<uuid:event_id>/send/',
        views.EventManualSendView.as_view(),
        name='manual-send',
    ),
]
