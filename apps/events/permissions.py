"""
Custom permissions for Events app.
"""
from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsOrganizerOrAdmin(BasePermission):
    """
    Allow access to organizers and tenant admins.
    Read-only access is allowed for authenticated users.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_organizer_or_above()

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        # Tenant admins can manage any event; organizers only their own
        if request.user.role == 'tenant_admin':
            return True
        return obj.organizer == request.user
