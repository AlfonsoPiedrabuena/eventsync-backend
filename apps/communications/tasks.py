"""
Celery tasks for EventSync communications.

Multi-tenancy note
------------------
Celery workers start with no tenant context (public schema). Every task that
queries tenant tables must either:

  a) Receive `tenant_schema` as an argument and call
     `connection.set_schema(tenant_schema)` at the top (tasks triggered
     from a user request).

  b) Iterate over all tenants via `schema_context` (Beat / scheduled tasks
     with no incoming context).

All model imports happen *inside* task bodies to avoid circular imports at
module load time (communications ↔ registrations).
"""
from celery import shared_task
from django.db import connection
from django.utils import timezone
from datetime import timedelta


# ---------------------------------------------------------------------------
# Request-triggered tasks  (receive tenant_schema from the caller)
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_confirmation_email_task(self, registration_id: str, tenant_schema: str):
    """
    Send a confirmation email to a newly registered attendee.

    Enqueued by registrations.services.create_registration immediately
    after a registration is created. Caller passes connection.schema_name
    so the worker knows which schema to query.
    """
    from apps.registrations.models import Registration
    from . import services

    try:
        connection.set_schema(tenant_schema)
        registration = (
            Registration.objects
            .select_related('event')
            .get(id=registration_id)
        )
        services.send_confirmation_email(registration)
    except Registration.DoesNotExist:
        pass
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_reminder_email_task(self, registration_id: str, reminder_type: str, tenant_schema: str):
    """
    Send a 24h or 1h reminder to a confirmed attendee.

    Enqueued by send_scheduled_reminders (Beat task), which passes the
    tenant_schema it is already iterating over.
    """
    from apps.registrations.models import Registration
    from . import services

    try:
        connection.set_schema(tenant_schema)
        registration = (
            Registration.objects
            .select_related('event')
            .get(id=registration_id)
        )
        if registration.status != Registration.Status.CONFIRMED:
            return
        services.send_reminder_email(registration, reminder_type)
    except Registration.DoesNotExist:
        pass
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_post_event_emails_task(self, event_id: str, tenant_schema: str):
    """
    Send post-event emails to all confirmed registrations for an event.

    Enqueued by events.services.transition_event_status when an event
    transitions to 'finalized'. Caller passes connection.schema_name.
    """
    from apps.events.models import Event
    from apps.registrations.models import Registration
    from . import services

    try:
        connection.set_schema(tenant_schema)
        event = Event.objects.get(id=event_id)
        registrations = (
            event.registrations
            .filter(status=Registration.Status.CONFIRMED)
            .select_related('event')
        )
        for reg in registrations:
            try:
                services.send_post_event_email(reg)
            except Exception:
                pass
    except Event.DoesNotExist:
        pass
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_manual_email_task(self, event_id: str, subject: str, message: str, segment: str, tenant_schema: str):
    """
    Send a manual organizer email to a segment of event attendees.

    Enqueued by the ManualSendView. Caller passes connection.schema_name.

    Segments:
        all        — confirmed + waitlisted (excludes cancelled)
        confirmed  — confirmed only
        waitlisted — waitlisted only
        checked_in — confirmed attendees who checked in
        no_show    — confirmed attendees who did NOT check in
    """
    from apps.events.models import Event
    from apps.registrations.models import Registration
    from . import services

    try:
        connection.set_schema(tenant_schema)
        event = Event.objects.get(id=event_id)

        qs = event.registrations.exclude(status=Registration.Status.CANCELLED)
        if segment == 'confirmed':
            qs = qs.filter(status=Registration.Status.CONFIRMED)
        elif segment == 'waitlisted':
            qs = qs.filter(status=Registration.Status.WAITLISTED)
        elif segment == 'checked_in':
            qs = qs.filter(status=Registration.Status.CONFIRMED, checked_in=True)
        elif segment == 'no_show':
            qs = qs.filter(status=Registration.Status.CONFIRMED, checked_in=False)

        for reg in qs.select_related('event'):
            try:
                services.send_manual_email_to_registration(reg, subject, message)
            except Exception:
                pass
    except Event.DoesNotExist:
        pass
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_cancellation_email_task(self, registration_id: str, tenant_schema: str):
    """
    Send a cancellation confirmation email to an attendee.

    Enqueued by registrations.views.CancelByTokenView after cancelling
    a registration via the public cancellation link.
    """
    from apps.registrations.models import Registration
    from . import services

    try:
        connection.set_schema(tenant_schema)
        registration = (
            Registration.objects
            .select_related('event')
            .get(id=registration_id)
        )
        services.send_cancellation_email(registration)
    except Registration.DoesNotExist:
        pass
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email_task(self, user_id: int):
    """
    Send a password reset email to the user.

    Enqueued by authentication.views.PasswordResetRequestView after
    generating the reset token. User always lives in the public schema.
    """
    from apps.authentication.models import User
    from . import services

    try:
        connection.set_schema('public')
        user = User.objects.get(id=user_id)
        services.send_password_reset_email(user)
    except User.DoesNotExist:
        pass
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_verification_email_task(self, user_id: int, tenant_schema: str):
    """
    Send an account verification email to a newly registered user.

    Enqueued by authentication.serializers.TenantRegistrationSerializer
    immediately after the user and tenant are created.
    """
    from apps.authentication.models import User
    from . import services

    try:
        connection.set_schema(tenant_schema)
        user = User.objects.select_related('tenant').get(id=user_id)
        services.send_verification_email(user)
    except User.DoesNotExist:
        pass
    except Exception as exc:
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Beat task  (no incoming context — iterates over all tenants)
# ---------------------------------------------------------------------------

@shared_task
def send_scheduled_reminders():
    """
    Beat task — runs every hour.

    Iterates over every active tenant schema and finds events starting
    within the ±30 min window around the 24h and 1h marks, then enqueues
    individual reminder tasks. Deduplication is handled by
    services.send_reminder_email (idempotency check against EmailLog).
    """
    from django_tenants.utils import schema_context
    from apps.tenants.models import Tenant
    from apps.events.models import Event
    from apps.registrations.models import Registration

    now = timezone.now()
    windows = [
        (now + timedelta(hours=23, minutes=30), now + timedelta(hours=24, minutes=30), 'reminder_24h'),
        (now + timedelta(minutes=30),           now + timedelta(hours=1,  minutes=30), 'reminder_1h'),
    ]

    tenants = Tenant.objects.exclude(schema_name='public')

    for tenant in tenants:
        with schema_context(tenant.schema_name):
            for window_start, window_end, reminder_type in windows:
                events = Event.objects.filter(
                    status=Event.Status.PUBLISHED,
                    start_date__gte=window_start,
                    start_date__lte=window_end,
                )
                for event in events:
                    reg_ids = (
                        event.registrations
                        .filter(status=Registration.Status.CONFIRMED)
                        .values_list('id', flat=True)
                    )
                    for reg_id in reg_ids:
                        send_reminder_email_task.delay(
                            str(reg_id),
                            reminder_type,
                            tenant.schema_name,
                        )
