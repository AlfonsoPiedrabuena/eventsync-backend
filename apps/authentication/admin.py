"""
Django admin configuration for Authentication app.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Invitation


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin interface for User model."""
    list_display = ('email', 'get_full_name', 'role', 'tenant', 'is_active', 'is_email_verified', 'created_at')
    list_filter = ('role', 'is_active', 'is_email_verified', 'created_at')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('-created_at',)

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name')}),
        ('Permissions', {
            'fields': ('role', 'tenant', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Email verification', {
            'fields': ('is_email_verified', 'email_verification_token'),
            'classes': ('collapse',)
        }),
        ('Important dates', {
            'fields': ('last_login', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'role', 'tenant', 'password1', 'password2'),
        }),
    )

    readonly_fields = ('created_at', 'updated_at', 'last_login')


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    """Admin interface for Invitation model."""
    list_display = ('email', 'tenant', 'role', 'status', 'invited_by', 'created_at', 'expires_at')
    list_filter = ('status', 'role', 'created_at')
    search_fields = ('email', 'tenant__name')
    readonly_fields = ('token', 'created_at', 'accepted_at')

    fieldsets = (
        ('Invitation Details', {
            'fields': ('email', 'first_name', 'last_name', 'role', 'tenant', 'invited_by')
        }),
        ('Status', {
            'fields': ('status', 'token')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'expires_at', 'accepted_at'),
        }),
    )
