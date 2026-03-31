"""
Views for Check-in app.
"""
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.events.models import Event
from apps.registrations.models import Registration
from .permissions import IsCheckInStaffOrAbove
from .serializers import (
    CheckinByTokenSerializer,
    CheckinResponseSerializer,
    EventStatsSerializer,
    ManualCheckinSerializer,
)
from . import services


class CheckinByTokenView(APIView):
    """
    POST /api/checkin/
    Validate a QR token and mark the attendee as checked in.

    Returns the registration detail and an `already_checked_in` flag.
    If the attendee had already checked in, the flag is True and the
    frontend should show a warning instead of a success message.
    """
    permission_classes = [IsCheckInStaffOrAbove]

    def post(self, request):
        serializer = CheckinByTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = services.checkin_by_token(serializer.validated_data['qr_token'])
        except ValidationError as e:
            return Response({'error': e.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            CheckinResponseSerializer(result).data,
            status=status.HTTP_200_OK,
        )


class ManualCheckinView(APIView):
    """
    POST /api/checkin/manual/
    Check in an attendee by registration ID (manual fallback).

    Used when QR scanning is not possible (damaged QR, no camera, etc.).
    """
    permission_classes = [IsCheckInStaffOrAbove]

    def post(self, request):
        serializer = ManualCheckinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        registration = get_object_or_404(
            Registration,
            id=serializer.validated_data['registration_id'],
        )

        try:
            result = services.checkin_by_token(registration.qr_token)
        except ValidationError as e:
            return Response({'error': e.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            CheckinResponseSerializer(result).data,
            status=status.HTTP_200_OK,
        )


class EventStatsView(APIView):
    """
    GET /api/checkin/stats/?event={id}
    Return real-time check-in statistics for an event.

    Used to display live counters on the check-in screen.
    """
    permission_classes = [IsCheckInStaffOrAbove]

    def get(self, request):
        event_id = request.query_params.get('event')
        if not event_id:
            return Response(
                {'error': 'El parámetro event es requerido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = get_object_or_404(Event, id=event_id)
        stats = services.get_event_stats(event)

        return Response(EventStatsSerializer(stats).data)


class RegistrationSearchView(APIView):
    """
    GET /api/checkin/search/?event={id}&q={query}
    Search confirmed registrations by name or email for manual check-in.
    """
    permission_classes = [IsCheckInStaffOrAbove]

    def get(self, request):
        event_id = request.query_params.get('event')
        query = request.query_params.get('q', '').strip()

        if not event_id:
            return Response(
                {'error': 'El parámetro event es requerido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(query) < 2:
            return Response(
                {'error': 'La búsqueda debe tener al menos 2 caracteres.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = get_object_or_404(Event, id=event_id)
        registrations = services.search_registrations(event, query)

        from apps.registrations.serializers import RegistrationListSerializer
        return Response({
            'count': registrations.count(),
            'results': RegistrationListSerializer(registrations, many=True).data,
        })
