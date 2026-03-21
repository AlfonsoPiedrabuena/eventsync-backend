"""
Tenant models for multi-tenancy support.
"""
from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Tenant(TenantMixin):
    """
    Tenant model representing an organization using EventSync.

    Each tenant has its own PostgreSQL schema with isolated data.
    """
    name = models.CharField(max_length=100, help_text="Organization name")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Billing information (for Phase 4)
    plan = models.CharField(
        max_length=20,
        default='free',
        choices=[
            ('free', 'Free'),
            ('starter', 'Starter'),
            ('pro', 'Pro'),
        ],
        help_text="Subscription plan"
    )
    is_active = models.BooleanField(default=True, help_text="Is tenant active")

    # Auto-created fields from TenantMixin:
    # - schema_name: PostgreSQL schema name (unique)
    # - auto_create_schema: Boolean for auto schema creation
    # - auto_drop_schema: Boolean for auto schema deletion

    class Meta:
        db_table = 'tenants'
        verbose_name = 'Tenant'
        verbose_name_plural = 'Tenants'

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    """
    Domain model for tenant routing.

    Maps domains/subdomains to tenants.
    Examples:
    - cliente1.eventsync.local -> Cliente 1 tenant
    - cliente2.eventsync.app -> Cliente 2 tenant
    """
    # Auto-created fields from DomainMixin:
    # - domain: Domain name (unique)
    # - tenant: ForeignKey to Tenant
    # - is_primary: Boolean indicating primary domain

    class Meta:
        db_table = 'tenant_domains'
        verbose_name = 'Domain'
        verbose_name_plural = 'Domains'

    def __str__(self):
        return self.domain
