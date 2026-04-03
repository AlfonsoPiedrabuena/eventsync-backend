"""
Analytics views for E6.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from django.shortcuts import get_object_or_404

from apps.events.models import Event
from apps.events.permissions import IsOrganizerOrAdmin
from . import services


class EventSummaryView(APIView):
    """GET /api/analytics/events/{event_id}/summary/"""
    permission_classes = [permissions.IsAuthenticated, IsOrganizerOrAdmin]

    def get(self, request, event_id):
        event = get_object_or_404(Event, id=event_id)
        return Response(services.get_event_summary(event))


class EventTimelineView(APIView):
    """GET /api/analytics/events/{event_id}/timeline/"""
    permission_classes = [permissions.IsAuthenticated, IsOrganizerOrAdmin]

    def get(self, request, event_id):
        event = get_object_or_404(Event, id=event_id)
        return Response(services.get_registrations_timeline(event))


class TenantDashboardView(APIView):
    """GET /api/analytics/dashboard/"""
    permission_classes = [permissions.IsAuthenticated, IsOrganizerOrAdmin]

    def get(self, request):
        return Response(services.get_tenant_dashboard())
