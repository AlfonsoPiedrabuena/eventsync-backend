"""
Permissions for Communications app.
"""
from rest_framework.permissions import BasePermission


class IsOrganizerOrAbove(BasePermission):
    """
    Allow only organizers and above (tenant_admin, super_admin) to access
    communications endpoints. Unlike the events permission, this does NOT
    grant read access to all authenticated users — email logs are internal
    organizer data.
    """

    ALLOWED_ROLES = ('organizer', 'tenant_admin', 'super_admin')

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in self.ALLOWED_ROLES
        )
