from django.urls import path
from .views import EventSummaryView, EventTimelineView, TenantDashboardView

urlpatterns = [
    path('dashboard/', TenantDashboardView.as_view(), name='analytics-dashboard'),
    path('events/<uuid:event_id>/summary/', EventSummaryView.as_view(), name='analytics-event-summary'),
    path('events/<uuid:event_id>/timeline/', EventTimelineView.as_view(), name='analytics-event-timeline'),
]
