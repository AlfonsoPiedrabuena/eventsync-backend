"""
Views for Events app.
"""
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from .models import Event
from .serializers import (
    EventListSerializer,
    EventDetailSerializer,
    EventCreateSerializer,
    EventUpdateSerializer,
    EventStatusTransitionSerializer,
)
from .permissions import IsOrganizerOrAdmin
from . import services


class EventViewSet(viewsets.ModelViewSet):
    """
    ViewSet for CRUD operations on events (E2).

    list:   GET  /api/events/
    create: POST /api/events/
    retrieve: GET /api/events/{id}/
    update: PATCH /api/events/{id}/
    destroy: DELETE /api/events/{id}/
    transition: POST /api/events/{id}/transition/
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    lookup_field = 'id'

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated(), IsOrganizerOrAdmin()]

    def get_queryset(self):
        """
        Filter events for the current tenant's organizers.
        Tenant admins see all events; organizers see only their own.
        """
        user = self.request.user
        qs = Event.objects.select_related('organizer').order_by('-created_at')

        # Unauthenticated access: only show published events
        if not user or not user.is_authenticated:
            qs = qs.filter(status=Event.Status.PUBLISHED)
        elif user.role == 'organizer':
            qs = qs.filter(organizer=user)

        # Optional query params
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        slug_filter = self.request.query_params.get('slug')
        if slug_filter:
            qs = qs.filter(slug=slug_filter)

        return qs

    def get_serializer_class(self):
        if self.action == 'list':
            return EventListSerializer
        if self.action == 'create':
            return EventCreateSerializer
        if self.action in ('update', 'partial_update'):
            return EventUpdateSerializer
        if self.action == 'transition':
            return EventStatusTransitionSerializer
        return EventDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action == 'transition':
            context['event'] = self.get_object()
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            event = services.create_event(request.user, serializer.validated_data)
        except ValidationError as e:
            return Response({'error': e.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            EventDetailSerializer(event, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        event = self.get_object()
        serializer = self.get_serializer(event, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        try:
            event = services.update_event(event, request.user, serializer.validated_data)
        except ValidationError as e:
            return Response({'error': e.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(EventDetailSerializer(event, context={'request': request}).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        event = self.get_object()
        if event.status != Event.Status.DRAFT:
            return Response(
                {'error': 'Solo se pueden eliminar eventos en estado Borrador.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        event.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='transition')
    def transition(self, request, id=None):
        """
        Transition an event to a new status.

        POST /api/events/{id}/transition/
        Body: {"status": "published"}
        """
        event = self.get_object()
        serializer = EventStatusTransitionSerializer(
            data=request.data,
            context={'event': event, 'request': request}
        )
        serializer.is_valid(raise_exception=True)

        try:
            event = services.transition_event_status(
                event, request.user, serializer.validated_data['status']
            )
        except ValidationError as e:
            return Response({'error': e.messages}, status=status.HTTP_400_BAD_REQUEST)

        return Response(EventDetailSerializer(event, context={'request': request}).data)
