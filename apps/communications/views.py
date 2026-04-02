"""
Views for Communications app.

Endpoints:
    GET  /api/communications/events/{event_id}/logs/  — email log for organizer
    POST /api/communications/events/{event_id}/send/  — manual broadcast to segment
"""
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404

from django.db import connection

from apps.events.models import Event
from .models import EmailLog
from .permissions import IsOrganizerOrAbove
from .serializers import EmailLogSerializer, ManualSendSerializer
from .tasks import send_manual_email_task


class EventEmailLogsView(ListAPIView):
    """
    GET /api/communications/events/{event_id}/logs/

    Returns all email send attempts for an event, newest first.
    Useful for the organizer to audit delivery and troubleshoot failures.
    """
    serializer_class    = EmailLogSerializer
    permission_classes  = [IsOrganizerOrAbove]

    def get_queryset(self):
        event = get_object_or_404(Event, id=self.kwargs['event_id'])
        return (
            EmailLog.objects
            .filter(event=event)
            .select_related('registration')
        )


class EventManualSendView(APIView):
    """
    POST /api/communications/events/{event_id}/send/

    Enqueue a manual email to a segment of the event's attendees.
    Returns 202 immediately — actual sending happens in Celery workers.

    Body:
        subject  (str)  — email subject line
        message  (str)  — email body (rendered into the manual template)
        segment  (str)  — 'all' | 'confirmed' | 'waitlisted' |
                          'checked_in' | 'no_show'
    """
    permission_classes = [IsOrganizerOrAbove]

    def post(self, request, event_id):
        event = get_object_or_404(Event, id=event_id)
        serializer = ManualSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        send_manual_email_task.delay(
            event_id=str(event.id),
            subject=data['subject'],
            message=data['message'],
            segment=data['segment'],
            tenant_schema=connection.schema_name,
        )

        return Response(
            {'detail': 'Envío en progreso. Los emails se despacharán en breve.'},
            status=status.HTTP_202_ACCEPTED,
        )
