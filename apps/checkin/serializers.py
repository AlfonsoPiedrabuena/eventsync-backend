"""
Serializers for Check-in app.
"""
from rest_framework import serializers
from apps.registrations.models import Registration


class CheckinByTokenSerializer(serializers.Serializer):
    """Input serializer for QR check-in."""
    qr_token = serializers.CharField(max_length=64)


class CheckinRegistrationSerializer(serializers.ModelSerializer):
    """Registration detail returned after a check-in operation."""
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Registration
        fields = (
            'id', 'full_name', 'first_name', 'last_name',
            'email', 'company', 'position',
            'status', 'checked_in', 'checked_in_at',
        )


class CheckinResponseSerializer(serializers.Serializer):
    """Response envelope for a check-in operation."""
    registration = CheckinRegistrationSerializer(read_only=True)
    already_checked_in = serializers.BooleanField(read_only=True)


class EventStatsSerializer(serializers.Serializer):
    """Real-time check-in statistics for an event."""
    confirmed = serializers.IntegerField()
    checked_in = serializers.IntegerField()
    pending = serializers.IntegerField()
    waitlisted = serializers.IntegerField()
    cancelled = serializers.IntegerField()


class ManualCheckinSerializer(serializers.Serializer):
    """Input for manual check-in by registration ID."""
    registration_id = serializers.UUIDField()
