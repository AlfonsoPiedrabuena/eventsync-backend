"""
Serializers for Authentication app.
"""
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core import exceptions as django_exceptions
from .models import User, Invitation


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model."""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'email', 'first_name', 'last_name', 'full_name',
            'role', 'tenant', 'is_active', 'is_email_verified',
            'created_at'
        )
        read_only_fields = ('id', 'created_at', 'is_email_verified')

    def get_full_name(self, obj):
        return obj.get_full_name()


class TenantRegistrationSerializer(serializers.Serializer):
    """
    Serializer for tenant registration (HU-E1-01).

    This creates both a new tenant and its first admin user.
    """
    # Organization info
    organization_name = serializers.CharField(max_length=100)

    # Admin user info
    first_name = serializers.CharField(max_length=50)
    last_name = serializers.CharField(max_length=50)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    password_confirm = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate_email(self, value):
        """Check if email is already registered."""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "Un usuario con este correo electrónico ya existe."
            )
        return value

    def validate(self, attrs):
        """Validate password and password confirmation match."""
        password = attrs.get('password')
        password_confirm = attrs.pop('password_confirm', None)

        if password != password_confirm:
            raise serializers.ValidationError({
                'password_confirm': 'Las contraseñas no coinciden.'
            })

        # Validate password strength
        try:
            validate_password(password)
        except django_exceptions.ValidationError as e:
            raise serializers.ValidationError({'password': list(e.messages)})

        return attrs

    def create(self, validated_data):
        """
        Create a new tenant and its admin user.

        This method is called from the view and handles the transaction.
        """
        from apps.tenants.models import Tenant, Domain
        from django.db import transaction
        from django.utils.text import slugify
        import uuid

        organization_name = validated_data.pop('organization_name')

        with transaction.atomic():
            # Create tenant
            schema_name = slugify(organization_name).replace('-', '_')[:63]
            # Ensure unique schema name
            if Tenant.objects.filter(schema_name=schema_name).exists():
                schema_name = f"{schema_name}_{uuid.uuid4().hex[:8]}"

            tenant = Tenant.objects.create(
                name=organization_name,
                schema_name=schema_name
            )

            # Create primary domain (for development)
            # In production, this should be a subdomain or custom domain
            domain_name = f"{schema_name}.localhost"
            Domain.objects.create(
                domain=domain_name,
                tenant=tenant,
                is_primary=True
            )

            # Create admin user
            user = User.objects.create_user(
                email=validated_data['email'],
                password=validated_data['password'],
                first_name=validated_data['first_name'],
                last_name=validated_data['last_name'],
                role='tenant_admin',
                tenant=tenant,
            )

            # Generate email verification token
            user.email_verification_token = uuid.uuid4().hex
            user.save()

            # TODO: Send verification email (E5)

        return {
            'user': user,
            'tenant': tenant,
        }


class LoginSerializer(serializers.Serializer):
    """Serializer for user login (HU-E1-02)."""
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})


class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for password reset request (HU-E1-03)."""
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for password reset confirmation (HU-E1-03)."""
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    password_confirm = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        """Validate password and password confirmation match."""
        password = attrs.get('password')
        password_confirm = attrs.pop('password_confirm', None)

        if password != password_confirm:
            raise serializers.ValidationError({
                'password_confirm': 'Las contraseñas no coinciden.'
            })

        # Validate password strength
        try:
            validate_password(password)
        except django_exceptions.ValidationError as e:
            raise serializers.ValidationError({'password': list(e.messages)})

        return attrs


class InvitationSerializer(serializers.ModelSerializer):
    """Serializer for user invitation (HU-E1-04)."""
    invited_by_name = serializers.SerializerMethodField()
    tenant_name = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = (
            'id', 'email', 'first_name', 'last_name', 'role',
            'status', 'invited_by_name', 'tenant_name',
            'created_at', 'expires_at'
        )
        read_only_fields = ('id', 'status', 'created_at', 'expires_at')

    def get_invited_by_name(self, obj):
        return obj.invited_by.get_full_name()

    def get_tenant_name(self, obj):
        return obj.tenant.name


class InvitationAcceptSerializer(serializers.Serializer):
    """Serializer for accepting an invitation."""
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    password_confirm = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        """Validate password and password confirmation match."""
        password = attrs.get('password')
        password_confirm = attrs.pop('password_confirm', None)

        if password != password_confirm:
            raise serializers.ValidationError({
                'password_confirm': 'Las contraseñas no coinciden.'
            })

        # Validate password strength
        try:
            validate_password(password)
        except django_exceptions.ValidationError as e:
            raise serializers.ValidationError({'password': list(e.messages)})

        return attrs
