"""
Custom permissions for Authentication app.
"""
from rest_framework.permissions import BasePermission


class IsTenantAdmin(BasePermission):
    """
    Allow access only to tenant admins (and super admins).
    """

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ('tenant_admin', 'super_admin')
        )
