"""
Business logic for Registrations app.

Handles capacity validation, QR token generation, and registration lifecycle.
"""
import uuid
from django.core.exceptions import ValidationError

from apps.events.models import Event
from .models import Registration


def _generate_qr_token() -> str:
    """Generate a unique QR token for a registration."""
    return uuid.uuid4().hex


def create_registration(event: Event, validated_data: dict) -> Registration:
    """
    Create a registration for a published event.

    If the event has available spots, status is 'confirmed'.
    If the event is full, status is 'waitlisted'.

    Args:
        event: The Event instance to register for
        validated_data: Validated data from RegistrationCreateSerializer

    Returns:
        Registration: The newly created registration

    Raises:
        ValidationError: If registration is not allowed
    """
    # Event must be published to accept registrations
    if event.status != Event.Status.PUBLISHED:
        raise ValidationError(
            "Solo se puede registrar en eventos publicados."
        )

    if event.is_past:
        raise ValidationError(
            "No se puede registrar en un evento que ya finalizó."
        )

    email = validated_data.get('email', '').lower()

    # Check for duplicate active registration
    if Registration.objects.filter(
        event=event,
        email=email,
        status__in=[Registration.Status.CONFIRMED, Registration.Status.WAITLISTED],
    ).exists():
        raise ValidationError(
            "Ya existe un registro activo con este email para este evento."
        )

    # Validate dynamic form fields
    _validate_form_responses(event, validated_data.get('form_responses', {}))

    # Determine status based on capacity
    reg_status = Registration.Status.CONFIRMED
    if event.max_capacity is not None and event.spots_remaining == 0:
        reg_status = Registration.Status.WAITLISTED

    # Generate QR token
    qr_token = _generate_qr_token()
    while Registration.objects.filter(qr_token=qr_token).exists():
        qr_token = _generate_qr_token()

    registration = Registration.objects.create(
        event=event,
        status=reg_status,
        qr_token=qr_token,
        email=email,
        **{k: v for k, v in validated_data.items() if k != 'email'},
    )

    # Enqueue confirmation email (E5). Import here to avoid circular imports.
    try:
        from django.db import connection
        from apps.communications.tasks import send_confirmation_email_task
        send_confirmation_email_task.delay(str(registration.id), connection.schema_name)
    except Exception:
        pass  # Task queue unavailable — registration still succeeds.

    return registration


def cancel_registration(registration: Registration, cancelled_by_organizer: bool = False) -> Registration:
    """
    Cancel a registration.

    When an organizer cancels a confirmed registration, promote the first
    waitlisted attendee if one exists.

    Args:
        registration: The Registration instance to cancel
        cancelled_by_organizer: Whether the cancellation is by the organizer

    Returns:
        Registration: The cancelled registration

    Raises:
        ValidationError: If the registration cannot be cancelled
    """
    if registration.status == Registration.Status.CANCELLED:
        raise ValidationError("Este registro ya está cancelado.")

    was_confirmed = registration.status == Registration.Status.CONFIRMED
    registration.status = Registration.Status.CANCELLED
    registration.save(update_fields=['status', 'updated_at'])

    # If a confirmed spot opens up, promote from waitlist
    if was_confirmed and registration.event.max_capacity is not None:
        _promote_from_waitlist(registration.event)

    return registration


def _promote_from_waitlist(event: Event):
    """
    Promote the earliest waitlisted registration to confirmed.
    Called after a confirmed registration is cancelled.
    """
    next_in_line = (
        Registration.objects.filter(event=event, status=Registration.Status.WAITLISTED)
        .order_by('created_at')
        .first()
    )
    if next_in_line:
        next_in_line.status = Registration.Status.CONFIRMED
        next_in_line.save(update_fields=['status', 'updated_at'])


def _validate_form_responses(event: Event, form_responses: dict):
    """
    Validate that all required dynamic form fields have been answered.

    Args:
        event: The Event instance whose form fields are checked
        form_responses: Dict of {field_key: value} from the registration request

    Raises:
        ValidationError: If any required field is missing
    """
    from apps.registration_forms.models import RegistrationFormField

    required_fields = RegistrationFormField.objects.filter(
        event=event,
        is_required=True,
        is_enabled=True,
    )
    errors = {}
    for field in required_fields:
        val = form_responses.get(field.field_key)
        if val is None or (val == '' and val != 0):
            errors[field.field_key] = f'El campo "{field.label}" es obligatorio.'
    if errors:
        raise ValidationError(errors)
