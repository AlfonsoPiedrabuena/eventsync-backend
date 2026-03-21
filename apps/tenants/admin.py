"""
Django admin configuration for Tenant app.
"""
from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import Tenant, Domain


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    """Admin interface for Tenant model."""
    list_display = ('name', 'schema_name', 'plan', 'is_active', 'created_at')
    list_filter = ('plan', 'is_active', 'created_at')
    search_fields = ('name', 'schema_name')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'schema_name')
        }),
        ('Subscription', {
            'fields': ('plan', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    """Admin interface for Domain model."""
    list_display = ('domain', 'tenant', 'is_primary')
    list_filter = ('is_primary',)
    search_fields = ('domain', 'tenant__name')
