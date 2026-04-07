"""
Views for Registrations app.
"""
import csv
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.events.models import Event
from .models import Registration
from .serializers import (
    RegistrationSerializer,
    RegistrationListSerializer,
    RegistrationCreateSerializer,
)
from .permissions import IsOrganizerOrAdmin
from . import services


class RegistrationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for attendee registrations.

    Public endpoints (no auth required):
        POST /api/registrations/                   — register for an event

    Organizer endpoints (auth required):
        GET  /api/registrations/?event={id}        — list registrations for an event
        GET  /api/registrations/{id}/              — get registration detail
        POST /api/registrations/{id}/cancel/       — cancel a registration
        GET  /api/registrations/?event={id}&export=csv  — export to CSV
    """
    lookup_field = 'id'

    def get_permissions(self):
        if self.action == 'create':
            return [permissions.AllowAny()]
        return [IsOrganizerOrAdmin()]

    def get_serializer_class(self):
        if self.action == 'list':
            return RegistrationListSerializer
        if self.action == 'create':
            return RegistrationCreateSerializer
        return RegistrationSerializer

    def get_queryset(self):
        qs = Registration.objects.select_related('event').order_by('-created_at')

        event_id = self.request.query_params.get('event')
        if event_id:
            qs = qs.filter(event_id=event_id)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        # Organizers only see registrations for their own events
        user = self.request.user
        if user.is_authenticated and user.role == 'organizer':
            qs = qs.filter(event__organizer=user)

        return qs

    def create(self, request, *args, **kwargs):
        """
        Public endpoint: register for an event.

        Body must include event_id plus attendee fields.
        Unauthenticated callers hit the public schema, so we locate the
        correct tenant schema via the event_id, then switch to it.
        """
        from django.db import connection as db_conn
        from django_tenants.utils import schema_context
        from apps.tenants.models import Tenant

        event_id = request.data.get('event_id')
        if not event_id:
            return Response(
                {'error': 'event_id es requerido.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # If already in a real tenant schema (authenticated request), proceed directly.
        if db_conn.schema_name != 'public':
            event = get_object_or_404(Event, id=event_id)
            serializer = RegistrationCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            try:
                registration = services.create_registration(event, serializer.validated_data)
            except ValidationError as e:
                return Response({'error': e.messages}, status=status.HTTP_400_BAD_REQUEST)
            return Response(RegistrationSerializer(registration).data, status=status.HTTP_201_CREATED)

        # Unauthenticated: find which tenant owns this event.
        tenant_schemas = list(
            Tenant.objects.exclude(schema_name='public').values_list('schema_name', flat=True)
        )
        target_schema = None
        for schema_name in tenant_schemas:
            try:
                with schema_context(schema_name):
                    if Event.objects.filter(id=event_id).exists():
                        target_schema = schema_name
                        break
            except Exception:
                continue

        if not target_schema:
            return Response({'error': 'Evento no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        # Switch permanently for this request so services/tasks see the right schema.
        db_conn.set_schema(target_schema)

        event = get_object_or_404(Event, id=event_id)
        serializer = RegistrationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            registration = services.create_registration(event, serializer.validated_data)
        except ValidationError as e:
            return Response({'error': e.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            RegistrationSerializer(registration).data,
            status=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        """
        List registrations. Supports CSV export via ?export=csv.
        """
        qs = self.get_queryset()

        if request.query_params.get('export') == 'csv':
            return self._export_csv(qs)

        serializer = RegistrationListSerializer(qs, many=True)
        return Response({
            'count': qs.count(),
            'results': serializer.data,
        })

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, id=None):
        """
        Cancel a registration and promote from waitlist if applicable.

        POST /api/registrations/{id}/cancel/
        """
        registration = self.get_object()

        try:
            registration = services.cancel_registration(
                registration,
                cancelled_by_organizer=True,
            )
        except ValidationError as e:
            return Response({'error': e.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(RegistrationSerializer(registration).data)

    def _export_csv(self, queryset):

        """Export registrations as CSV file."""
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="registrations.csv"'
        response.write('\ufeff')  # UTF-8 BOM for Excel compatibility

        writer = csv.writer(response)
        writer.writerow([
            'Nombre', 'Apellido', 'Email', 'Teléfono',
            'Empresa', 'Cargo', 'Estado', 'Check-in', 'Fecha registro'
        ])

        for reg in queryset:
            writer.writerow([
                reg.first_name,
                reg.last_name,
                reg.email,
                reg.phone,
                reg.company,
                reg.position,
                reg.get_status_display(),
                'Sí' if reg.checked_in else 'No',
                reg.created_at.strftime('%Y-%m-%d %H:%M'),
            ])

        return response


class CancelByTokenView(APIView):
    """
    Public endpoint to cancel a registration via the cancellation token
    embedded in the confirmation email link.

    POST /api/registrations/cancel/
    Body: { "token": "<cancellation_token>" }

    Responses:
        200 { "status": "cancelled", "event_title": "..." }
        200 { "status": "already_cancelled" }
        404 { "error": "Token inválido." }
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from django.db import connection as db_conn
        from django_tenants.utils import schema_context
        from apps.tenants.models import Tenant
        from apps.communications.tasks import send_cancellation_email_task

        token = request.data.get('token')
        if not token:
            return Response(
                {'error': 'El token es requerido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Search across all tenant schemas for a registration with this token.
        tenant_schemas = list(
            Tenant.objects.exclude(schema_name='public').values_list('schema_name', flat=True)
        )

        target_schema = None
        registration = None

        for schema_name in tenant_schemas:
            try:
                with schema_context(schema_name):
                    reg = Registration.objects.select_related('event').filter(
                        cancellation_token=token
                    ).first()
                    if reg:
                        target_schema = schema_name
                        # Fetch outside schema_context so the object is usable after
                        break
            except Exception:
                continue

        if not target_schema:
            return Response(
                {'error': 'Token inválido.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Switch permanently to the tenant schema for the rest of this request.
        db_conn.set_schema(target_schema)
        registration = Registration.objects.select_related('event').get(
            cancellation_token=token
        )

        if registration.status == Registration.Status.CANCELLED:
            return Response({'status': 'already_cancelled'}, status=status.HTTP_200_OK)

        event_title = registration.event.title
        services.cancel_registration(registration, cancelled_by_organizer=False)

        try:
            send_cancellation_email_task.delay(str(registration.id), target_schema)
        except Exception:
            pass  # Email failure must not break the cancellation flow.

        return Response(
            {'status': 'cancelled', 'event_title': event_title},
            status=status.HTTP_200_OK,
        )
