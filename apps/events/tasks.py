"""
Celery tasks for the events app.
"""
from celery import shared_task
from django.utils import timezone

from apps.tenants.models import Tenant
from django_tenants.utils import schema_context


@shared_task
def finalize_past_events():
    """
    Runs daily at 1:00 AM. For every tenant:
    - Moves published events whose end_date has passed → closed
    - Moves closed events → finalized
    """
    tenant_schemas = list(
        Tenant.objects.exclude(schema_name='public')
        .values_list('schema_name', flat=True)
    )

    closed_count = 0
    finalized_count = 0

    for schema_name in tenant_schemas:
        with schema_context(schema_name):
            from apps.events.models import Event

            now = timezone.now()

            # published → closed (event has ended)
            closed = Event.objects.filter(
                status=Event.Status.PUBLISHED,
                end_date__lt=now,
            ).update(status=Event.Status.CLOSED)
            closed_count += closed

            # closed → finalized
            finalized = Event.objects.filter(
                status=Event.Status.CLOSED,
                end_date__lt=now,
            ).update(status=Event.Status.FINALIZED)
            finalized_count += finalized

    return {
        'closed': closed_count,
        'finalized': finalized_count,
    }
