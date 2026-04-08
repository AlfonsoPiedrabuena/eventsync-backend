"""
Views for Registration Forms app.
"""
from django.core.exceptions import ValidationError
from django.db import connection as db_conn
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.events.models import Event
from apps.registrations.models import Registration
from apps.registrations.permissions import IsOrganizerOrAdmin
from .models import RegistrationFormField
from .serializers import RegistrationFormFieldSerializer, FormFieldReorderSerializer


def _has_active_registrations(event):
    """Return True if the event has any confirmed or waitlisted registrations."""
    return Registration.objects.filter(
        event=event,
        status__in=[Registration.Status.CONFIRMED, Registration.Status.WAITLISTED],
    ).exists()


class RegistrationFormFieldViewSet(viewsets.ModelViewSet):
    """
    ViewSet for dynamic form fields per event.

    Public:
        GET  /api/registration-form-fields/?event={id}   — list fields (used by public registration page)

    Organizer/Admin:
        POST   /api/registration-form-fields/            — create field (body: event_id + field data)
        PATCH  /api/registration-form-fields/{id}/       — update field
        DELETE /api/registration-form-fields/{id}/       — delete field
        PATCH  /api/registration-form-fields/reorder/    — reorder fields
    """
    serializer_class = RegistrationFormFieldSerializer
    lookup_field = 'id'

    def get_permissions(self):
        if self.action == 'list':
            return [permissions.AllowAny()]
        return [IsOrganizerOrAdmin()]

    def get_queryset(self):
        # For detail actions (retrieve, update, destroy), return all fields so
        # the router can look up by primary key. The list action filters by event.
        if self.action != 'list':
            return RegistrationFormField.objects.select_related('event').all()
        event_id = self.request.query_params.get('event')
        if not event_id:
            return RegistrationFormField.objects.none()
        return RegistrationFormField.objects.filter(event_id=event_id)

    def list(self, request, *args, **kwargs):
        """
        Public endpoint: returns form fields for a given event.

        Handles cross-tenant lookup for unauthenticated requests that arrive
        in the public schema (same pattern as RegistrationViewSet.create).
        """
        from django_tenants.utils import schema_context
        from apps.tenants.models import Tenant

        event_id = request.query_params.get('event')
        if not event_id:
            return Response(
                {'error': 'El parámetro event es requerido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if db_conn.schema_name != 'public':
            # Already in tenant schema (authenticated request).
            fields = self.get_queryset()
            return Response(RegistrationFormFieldSerializer(fields, many=True).data)

        # Unauthenticated: find the tenant that owns this event.
        tenant_schemas = list(
            Tenant.objects.exclude(schema_name='public').values_list('schema_name', flat=True)
        )
        for schema_name in tenant_schemas:
            try:
                with schema_context(schema_name):
                    if Event.objects.filter(id=event_id).exists():
                        fields = RegistrationFormField.objects.filter(event_id=event_id)
                        return Response(RegistrationFormFieldSerializer(fields, many=True).data)
            except Exception:
                continue

        return Response([], status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        from django.db import IntegrityError

        event_id = request.data.get('event_id')
        if not event_id:
            return Response(
                {'error': 'event_id es requerido.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        event = get_object_or_404(Event, id=event_id)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save(event=event)
        except IntegrityError:
            return Response(
                {'field_key': 'Ya existe un campo con este identificador para este evento.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        field = self.get_object()
        if _has_active_registrations(field.event):
            return Response(
                {'error': 'No se puede modificar el formulario: el evento ya tiene registros activos.'},
                status=status.HTTP_409_CONFLICT,
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        field = self.get_object()
        if _has_active_registrations(field.event):
            return Response(
                {'error': 'No se puede eliminar el campo: el evento ya tiene registros activos.'},
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['patch'], url_path='reorder')
    def reorder(self, request):
        """
        Reorder fields by providing an ordered list of field IDs.

        PATCH /api/registration-form-fields/reorder/
        Body: { "field_ids": ["uuid1", "uuid2", ...] }
        """
        serializer = FormFieldReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        field_ids = serializer.validated_data['field_ids']

        # Verify all IDs belong to the same event and the current tenant.
        fields = RegistrationFormField.objects.filter(id__in=field_ids)
        if fields.count() != len(field_ids):
            return Response(
                {'error': 'Uno o más IDs de campo no son válidos.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        events = set(fields.values_list('event_id', flat=True))
        if len(events) > 1:
            return Response(
                {'error': 'Todos los campos deben pertenecer al mismo evento.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = Event.objects.get(id=list(events)[0])
        if _has_active_registrations(event):
            return Response(
                {'error': 'No se puede reordenar el formulario: el evento ya tiene registros activos.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Bulk update order values.
        field_map = {f.id: f for f in fields}
        to_update = []
        for idx, field_id in enumerate(field_ids):
            field = field_map[field_id]
            field.order = idx
            to_update.append(field)
        RegistrationFormField.objects.bulk_update(to_update, ['order'])

        updated = RegistrationFormField.objects.filter(event=event)
        return Response(RegistrationFormFieldSerializer(updated, many=True).data)
