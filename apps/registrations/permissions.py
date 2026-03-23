"""
Permissions for Registrations app.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsOrganizerOrAdmin(BasePermission):
    """Allow organizers and admins to manage registrations."""

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ('organizer', 'tenant_admin', 'super_admin')
        )
