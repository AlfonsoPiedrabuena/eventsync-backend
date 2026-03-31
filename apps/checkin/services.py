"""
Business logic for Check-in app.

Handles QR token validation, check-in recording, event stats, and manual search.
"""
from dataclasses import dataclass
from django.core.exceptions import ValidationError
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.events.models import Event
from apps.registrations.models import Registration


@dataclass
class CheckinResult:
    """
    Result of a check-in operation.

    Attributes:
        registration: The registration that was checked in (or already was)
        already_checked_in: True if the attendee had already checked in before
                            this call. The frontend should show a warning instead
                            of a success message.
    """
    registration: Registration
    already_checked_in: bool


def checkin_by_token(qr_token: str) -> CheckinResult:
    """
    Validate a QR token and mark the attendee as checked in.

    Idempotent: if the attendee already checked in, returns the registration
    with already_checked_in=True so the caller can show a warning.

    Args:
        qr_token: The unique token from the registration's QR code.

    Returns:
        CheckinResult with the registration and already_checked_in flag.

    Raises:
        ValidationError: If the token is invalid or the registration is not confirmed.
    """
    try:
        registration = Registration.objects.select_related('event').get(qr_token=qr_token)
    except Registration.DoesNotExist:
        raise ValidationError("QR inválido o no encontrado.")

    if registration.status != Registration.Status.CONFIRMED:
        raise ValidationError(
            f"Este registro no puede hacer check-in (estado: {registration.get_status_display()})."
        )

    # Idempotent: already checked in → return with warning flag
    if registration.checked_in:
        return CheckinResult(registration=registration, already_checked_in=True)

    registration.checked_in = True
    registration.checked_in_at = timezone.now()
    registration.save(update_fields=['checked_in', 'checked_in_at', 'updated_at'])

    return CheckinResult(registration=registration, already_checked_in=False)


def get_event_stats(event: Event) -> dict:
    """
    Return real-time check-in statistics for an event.

    Args:
        event: The Event instance.

    Returns:
        dict with confirmed, checked_in, pending, waitlisted, cancelled counts.
    """
    counts = Registration.objects.filter(event=event).aggregate(
        confirmed=Count('id', filter=Q(status=Registration.Status.CONFIRMED)),
        checked_in=Count('id', filter=Q(status=Registration.Status.CONFIRMED, checked_in=True)),
        waitlisted=Count('id', filter=Q(status=Registration.Status.WAITLISTED)),
        cancelled=Count('id', filter=Q(status=Registration.Status.CANCELLED)),
    )
    counts['pending'] = counts['confirmed'] - counts['checked_in']
    return counts


def search_registrations(event: Event, query: str) -> QuerySet:
    """
    Search confirmed registrations for an event by name or email.

    Used for manual check-in when QR scanning is not possible.

    Args:
        event: The Event instance.
        query: Search string matched against first_name, last_name, or email.

    Returns:
        QuerySet of matching Registration instances (confirmed only).
    """
    query = query.strip()
    if not query:
        return Registration.objects.none()

    return Registration.objects.filter(
        event=event,
        status=Registration.Status.CONFIRMED,
    ).filter(
        Q(first_name__icontains=query)
        | Q(last_name__icontains=query)
        | Q(email__icontains=query)
    ).order_by('last_name', 'first_name')
