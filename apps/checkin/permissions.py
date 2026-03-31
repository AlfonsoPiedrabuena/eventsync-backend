"""
Permissions for Check-in app.
"""
from rest_framework.permissions import BasePermission


class IsCheckInStaffOrAbove(BasePermission):
    """
    Allow check-in staff and any higher role to access check-in endpoints.

    Role hierarchy (lowest to highest):
        checkin_staff → organizer → tenant_admin → super_admin
    """

    ALLOWED_ROLES = ('checkin_staff', 'organizer', 'tenant_admin', 'super_admin')

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in self.ALLOWED_ROLES
        )
