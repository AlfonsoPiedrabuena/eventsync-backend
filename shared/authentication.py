"""
Tenant-aware JWT authentication for EventSync MVP.

Instead of routing by subdomain, we detect the tenant from the JWT token
and switch the database schema accordingly. This allows all API requests
to go through a single domain (localhost:8000 in development,
api.eventsync.app in production) while maintaining full tenant isolation.
"""
from django.db import connection
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


class TenantAwareJWTAuthentication(JWTAuthentication):
    """
    Extends JWTAuthentication to automatically switch the PostgreSQL
    search_path to the authenticated user's tenant schema.

    Flow:
        1. Validate JWT token (standard simplejwt)
        2. Fetch user from DB (public schema — users live there)
        3. If user has a tenant, switch connection to that schema
        4. All subsequent queries in the view use the tenant schema

    Note: InvalidToken (expired/malformed token) is caught and treated as
    anonymous so that AllowAny endpoints (e.g. /api/auth/register/) work
    correctly even when the browser sends a stale token.
    """

    def authenticate(self, request):
        try:
            result = super().authenticate(request)
        except InvalidToken:
            return None

        if result is None:
            return None

        user, token = result

        if user.tenant:
            connection.set_schema(user.tenant.schema_name)
            _sync_user_to_tenant_schema(user)

        return user, token


def _sync_user_to_tenant_schema(user):
    """
    Ensure the user row exists in the tenant schema.

    Users are created in the public schema during registration, but the
    events.organizer FK points to the users table in the tenant schema.
    This lazy sync creates the row on first access so FK constraints work.
    """
    from apps.authentication.models import User
    User.objects.get_or_create(
        id=user.id,
        defaults={
            'email': user.email,
            'password': user.password,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'tenant': user.tenant,
            'is_active': user.is_active,
            'is_email_verified': user.is_email_verified,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'created_at': user.created_at,
        }
    )
