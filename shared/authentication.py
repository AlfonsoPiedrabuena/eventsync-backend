"""
Tenant-aware JWT authentication for EventSync MVP.

Instead of routing by subdomain, we detect the tenant from the JWT token
and switch the database schema accordingly. This allows all API requests
to go through a single domain (localhost:8000 in development,
api.eventsync.app in production) while maintaining full tenant isolation.
"""
from django.db import connection
from rest_framework_simplejwt.authentication import JWTAuthentication


class TenantAwareJWTAuthentication(JWTAuthentication):
    """
    Extends JWTAuthentication to automatically switch the PostgreSQL
    search_path to the authenticated user's tenant schema.

    Flow:
        1. Validate JWT token (standard simplejwt)
        2. Fetch user from DB (public schema — users live there)
        3. If user has a tenant, switch connection to that schema
        4. All subsequent queries in the view use the tenant schema
    """

    def authenticate(self, request):
        result = super().authenticate(request)

        if result is None:
            return None

        user, token = result

        if user.tenant:
            connection.set_schema(user.tenant.schema_name)

        return user, token
