"""
Serializers for Events app.
"""
from rest_framework import serializers
from django.utils import timezone

from .models import Event


class EventListSerializer(serializers.ModelSerializer):
    """Compact serializer for event listings."""
    organizer_name = serializers.SerializerMethodField()
    registration_count = serializers.IntegerField(read_only=True)
    spots_remaining = serializers.IntegerField(read_only=True)
    is_open_for_registration = serializers.BooleanField(read_only=True)
    cover_image_url = serializers.SerializerMethodField()
    is_virtual = serializers.BooleanField(read_only=True)

    class Meta:
        model = Event
        fields = (
            'id', 'title', 'slug', 'status', 'modality', 'is_virtual',
            'visibility', 'audience_type', 'target_company',
            'location', 'start_date', 'end_date',
            'max_capacity', 'registration_count', 'spots_remaining',
            'is_open_for_registration', 'cover_image_url',
            'organizer_name', 'created_at',
        )

    def get_organizer_name(self, obj):
        return obj.organizer.get_full_name() if obj.organizer else None

    def get_cover_image_url(self, obj):
        if obj.cover_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.cover_image.url)
        return None


class EventDetailSerializer(serializers.ModelSerializer):
    """Full serializer for event detail view."""
    organizer_name = serializers.SerializerMethodField()
    registration_count = serializers.IntegerField(read_only=True)
    spots_remaining = serializers.IntegerField(read_only=True)
    is_open_for_registration = serializers.BooleanField(read_only=True)
    cover_image_url = serializers.SerializerMethodField()
    valid_transitions = serializers.SerializerMethodField()
    is_virtual = serializers.BooleanField(read_only=True)

    class Meta:
        model = Event
        fields = (
            'id', 'title', 'slug', 'description', 'status',
            'modality', 'is_virtual', 'location', 'location_url',
            'virtual_access_url', 'hero_image_url',
            'visibility', 'audience_type', 'target_company',
            'start_date', 'end_date', 'max_capacity',
            'registration_count', 'spots_remaining',
            'is_open_for_registration', 'cover_image_url',
            'organizer', 'organizer_name',
            'valid_transitions',
            'created_at', 'updated_at', 'published_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at', 'published_at', 'organizer')

    def get_organizer_name(self, obj):
        return obj.organizer.get_full_name() if obj.organizer else None

    def get_cover_image_url(self, obj):
        if obj.cover_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.cover_image.url)
        return None

    def get_valid_transitions(self, obj):
        """Return the list of valid next statuses for frontend UI."""
        return [
            {'value': s, 'label': Event.Status(s).label}
            for s in obj.VALID_TRANSITIONS.get(obj.status, [])
        ]


class EventCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new event."""
    slug = serializers.SlugField(required=False)

    class Meta:
        model = Event
        fields = (
            'title', 'slug', 'description',
            'modality', 'location', 'location_url', 'virtual_access_url',
            'hero_image_url',
            'visibility', 'audience_type', 'target_company',
            'start_date', 'end_date', 'max_capacity',
        )

    def validate(self, attrs):
        start = attrs.get('start_date')
        end = attrs.get('end_date')
        if start and end and start >= end:
            raise serializers.ValidationError({
                'end_date': 'La fecha de fin debe ser posterior a la fecha de inicio.'
            })

        modality = attrs.get('modality', Event.Modality.IN_PERSON)
        location = attrs.get('location', '')
        if modality == Event.Modality.IN_PERSON and not location:
            raise serializers.ValidationError({
                'location': 'Un evento presencial debe tener una ubicación.'
            })

        visibility = attrs.get('visibility', Event.Visibility.PUBLIC)
        audience_type = attrs.get('audience_type')
        target_company = attrs.get('target_company', '')

        if visibility == Event.Visibility.PRIVATE and not audience_type:
            raise serializers.ValidationError({
                'audience_type': 'Un evento privado debe ser interno o externo.'
            })
        if visibility == Event.Visibility.PRIVATE and audience_type == Event.AudienceType.EXTERNAL and not target_company:
            raise serializers.ValidationError({
                'target_company': 'Un evento privado externo debe indicar la empresa destinataria.'
            })

        # Limpiar campos que no aplican
        if visibility == Event.Visibility.PUBLIC:
            attrs['audience_type'] = None
            attrs['target_company'] = ''
        if attrs.get('audience_type') == Event.AudienceType.INTERNAL:
            attrs['target_company'] = ''

        return attrs


class EventUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating an event (partial updates allowed)."""

    class Meta:
        model = Event
        fields = (
            'title', 'description',
            'modality', 'location', 'location_url', 'virtual_access_url',
            'hero_image_url',
            'visibility', 'audience_type', 'target_company',
            'start_date', 'end_date', 'max_capacity',
        )

    def validate(self, attrs):
        instance = self.instance
        start = attrs.get('start_date', instance.start_date if instance else None)
        end = attrs.get('end_date', instance.end_date if instance else None)
        if start and end and start >= end:
            raise serializers.ValidationError({
                'end_date': 'La fecha de fin debe ser posterior a la fecha de inicio.'
            })

        visibility = attrs.get('visibility', instance.visibility if instance else Event.Visibility.PUBLIC)
        audience_type = attrs.get('audience_type', instance.audience_type if instance else None)
        target_company = attrs.get('target_company', instance.target_company if instance else '')

        if visibility == Event.Visibility.PRIVATE and not audience_type:
            raise serializers.ValidationError({
                'audience_type': 'Un evento privado debe ser interno o externo.'
            })
        if visibility == Event.Visibility.PRIVATE and audience_type == Event.AudienceType.EXTERNAL and not target_company:
            raise serializers.ValidationError({
                'target_company': 'Un evento privado externo debe indicar la empresa destinataria.'
            })

        if visibility == Event.Visibility.PUBLIC:
            attrs['audience_type'] = None
            attrs['target_company'] = ''
        if attrs.get('audience_type') == Event.AudienceType.INTERNAL:
            attrs['target_company'] = ''

        return attrs


class EventStatusTransitionSerializer(serializers.Serializer):
    """Serializer for status transition action."""
    status = serializers.ChoiceField(choices=Event.Status.choices)

    def validate_status(self, value):
        event = self.context.get('event')
        if event and not event.can_transition_to(value):
            raise serializers.ValidationError(
                f"No se puede cambiar de '{event.get_status_display()}' a "
                f"'{Event.Status(value).label}'."
            )
        return value
