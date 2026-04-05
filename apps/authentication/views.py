"""
Views for Authentication app.
"""
from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate
from django.utils import timezone
from datetime import timedelta
import uuid

from .models import User, Invitation
from .serializers import (
    UserSerializer,
    TenantRegistrationSerializer,
    LoginSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    InvitationSerializer,
    InvitationAcceptSerializer,
)


class TenantRegistrationView(APIView):
    """
    API endpoint for tenant registration (HU-E1-01).

    POST /api/auth/register/
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = TenantRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = serializer.save()
        user = result['user']
        tenant = result['tenant']

        return Response({
            'message': 'Organización registrada exitosamente. Por favor verifica tu correo electrónico.',
            'user': UserSerializer(user).data,
            'tenant': {
                'id': str(tenant.id),
                'name': tenant.name,
                'schema_name': tenant.schema_name,
            },
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """
    API endpoint for user login (HU-E1-02).

    POST /api/auth/login/
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        from django.db import connection
        connection.set_schema('public')

        # Authenticate user
        user = authenticate(request, email=email, password=password)

        if user is None:
            return Response({
                'error': 'Credenciales inválidas.'
            }, status=status.HTTP_401_UNAUTHORIZED)

        if not user.is_active:
            return Response({
                'error': 'Esta cuenta ha sido desactivada.'
            }, status=status.HTTP_403_FORBIDDEN)

        if not user.is_email_verified:
            return Response({
                'error': 'Por favor verifica tu correo electrónico antes de iniciar sesión.',
                'email_not_verified': True,
            }, status=status.HTTP_403_FORBIDDEN)

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        # Update last login
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
        })


class LogoutView(APIView):
    """
    API endpoint for user logout (HU-E1-06).

    POST /api/auth/logout/
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            return Response({
                'message': 'Sesión cerrada exitosamente.'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'error': 'Token inválido.'
            }, status=status.HTTP_400_BAD_REQUEST)


class EmailVerificationView(APIView):
    """
    API endpoint for email verification.

    GET /api/auth/verify-email/{token}/
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        from django.db import connection
        connection.set_schema('public')
        try:
            user = User.objects.get(email_verification_token=token)

            if user.is_email_verified:
                return Response({
                    'message': 'Este correo ya ha sido verificado.'
                }, status=status.HTTP_200_OK)

            user.is_email_verified = True
            user.email_verification_token = ''
            user.save()

            return Response({
                'message': 'Correo verificado exitosamente. Ya puedes iniciar sesión.'
            }, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({
                'error': 'Token de verificación inválido.'
            }, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetRequestView(APIView):
    """
    API endpoint for password reset request (HU-E1-03).

    POST /api/auth/password-reset/
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']

        from django.db import connection
        connection.set_schema('public')

        try:
            user = User.objects.get(email=email)

            # Generate reset token
            reset_token = uuid.uuid4().hex
            user.email_verification_token = reset_token  # Reusing this field
            user.save()

            from apps.communications.tasks import send_password_reset_email_task
            send_password_reset_email_task.delay(user.id)

            return Response({
                'message': 'Si el correo existe, recibirás instrucciones para restablecer tu contraseña.'
            }, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            # Don't reveal if email exists
            return Response({
                'message': 'Si el correo existe, recibirás instrucciones para restablecer tu contraseña.'
            }, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    """
    API endpoint for password reset confirmation (HU-E1-03).

    POST /api/auth/password-reset/confirm/
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data['token']
        password = serializer.validated_data['password']

        from django.db import connection
        connection.set_schema('public')

        try:
            user = User.objects.get(email_verification_token=token)
            user.set_password(password)
            user.email_verification_token = ''
            user.save()

            return Response({
                'message': 'Contraseña restablecida exitosamente.'
            }, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({
                'error': 'Token inválido o expirado.'
            }, status=status.HTTP_400_BAD_REQUEST)


class InvitationListCreateView(generics.ListCreateAPIView):
    """
    API endpoint for listing and creating invitations (HU-E1-04).

    GET/POST /api/auth/invitations/
    """
    serializer_class = InvitationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Only tenant admins can see invitations."""
        user = self.request.user
        if user.role == 'tenant_admin':
            return Invitation.objects.filter(tenant=user.tenant).order_by('-created_at')
        return Invitation.objects.none()

    def perform_create(self, serializer):
        """Create invitation with auto-generated token."""
        user = self.request.user

        if user.role != 'tenant_admin':
            return Response({
                'error': 'Solo los administradores pueden enviar invitaciones.'
            }, status=status.HTTP_403_FORBIDDEN)

        # Generate unique token
        token = uuid.uuid4().hex

        # Set expiration (48 hours)
        expires_at = timezone.now() + timedelta(hours=48)

        invitation = serializer.save(
            tenant=user.tenant,
            invited_by=user,
            token=token,
            expires_at=expires_at
        )

        # TODO: Send invitation email (E5)

        return Response({
            'message': 'Invitación enviada exitosamente.',
            'invitation': InvitationSerializer(invitation).data,
        }, status=status.HTTP_201_CREATED)


class InvitationAcceptView(APIView):
    """
    API endpoint for accepting an invitation.

    POST /api/auth/invitations/accept/
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = InvitationAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data['token']
        password = serializer.validated_data['password']

        try:
            invitation = Invitation.objects.get(token=token)

            if not invitation.is_valid():
                return Response({
                    'error': 'Esta invitación ha expirado o ya ha sido utilizada.'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Create user
            user = User.objects.create_user(
                email=invitation.email,
                password=password,
                first_name=invitation.first_name or '',
                last_name=invitation.last_name or '',
                role=invitation.role,
                tenant=invitation.tenant,
                is_email_verified=True,  # Auto-verify for invitations
            )

            # Mark invitation as accepted
            invitation.status = 'accepted'
            invitation.accepted_at = timezone.now()
            invitation.save()

            return Response({
                'message': 'Invitación aceptada exitosamente. Ya puedes iniciar sesión.',
                'user': UserSerializer(user).data,
            }, status=status.HTTP_201_CREATED)

        except Invitation.DoesNotExist:
            return Response({
                'error': 'Token de invitación inválido.'
            }, status=status.HTTP_400_BAD_REQUEST)


class CurrentUserView(APIView):
    """
    API endpoint for getting current user info.

    GET /api/auth/me/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)
