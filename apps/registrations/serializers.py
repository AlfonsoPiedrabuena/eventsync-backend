"""
Serializers for Registrations app.
"""
import re
from rest_framework import serializers
from .models import Registration


class RegistrationSerializer(serializers.ModelSerializer):
    """Full serializer for registration detail."""
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Registration
        fields = (
            'id', 'event', 'full_name',
            'first_name', 'last_name', 'email',
            'phone', 'company', 'position',
            'status', 'checked_in', 'checked_in_at',
            'qr_token', 'created_at', 'updated_at',
        )
        read_only_fields = (
            'id', 'event', 'status', 'checked_in', 'checked_in_at',
            'qr_token', 'created_at', 'updated_at',
        )


class RegistrationListSerializer(serializers.ModelSerializer):
    """Compact serializer for registration listings."""
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Registration
        fields = (
            'id', 'full_name', 'email', 'phone',
            'company', 'status', 'checked_in', 'checked_in_at',
            'created_at',
        )


class RegistrationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new registration."""

    class Meta:
        model = Registration
        fields = (
            'first_name', 'last_name', 'email',
            'phone', 'company', 'position',
        )

    def validate_email(self, value):
        return value.lower()

    def validate_phone(self, value):
        if value and not re.match(r'^\+[1-9]\d{6,14}$', value):
            raise serializers.ValidationError(
                'Formato inválido. Usa formato E.164 (ej: +525512345678)'
            )
        return value
