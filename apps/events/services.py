"""
Business logic for Events app.

Handles slug generation, state transitions, and event lifecycle management.
"""
import uuid
from django.utils.text import slugify
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import Event


def generate_unique_slug(title: str, exclude_id=None) -> str:
    """
    Generate a unique slug from a title.

    If the base slug already exists, appends a short UUID suffix.

    Args:
        title: Event title to slugify
        exclude_id: UUID of the event to exclude from uniqueness check (for updates)

    Returns:
        str: A unique slug
    """
    base_slug = slugify(title)[:200]
    slug = base_slug

    qs = Event.objects.filter(slug=slug)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)

    if qs.exists():
        slug = f"{base_slug}-{uuid.uuid4().hex[:8]}"

    return slug


def create_event(user, validated_data: dict) -> Event:
    """
    Create a new event in Draft status.

    Args:
        user: The authenticated user (must be organizer or above)
        validated_data: Validated data from EventCreateSerializer

    Returns:
        Event: The newly created event

    Raises:
        ValidationError: If the user lacks permission or data is invalid
    """
    if not user.is_organizer_or_above():
        raise ValidationError("No tienes permisos para crear eventos.")

    title = validated_data.get('title', '')
    slug = validated_data.pop('slug', None) or generate_unique_slug(title)

    event = Event.objects.create(
        organizer=user,
        slug=slug,
        **validated_data
    )
    return event


def update_event(event: Event, user, validated_data: dict) -> Event:
    """
    Update an existing event.

    Only draft and published events can be edited.

    Args:
        event: The Event instance to update
        user: The authenticated user
        validated_data: Validated partial data from EventUpdateSerializer

    Returns:
        Event: The updated event

    Raises:
        ValidationError: If the event status doesn't allow edits
    """
    if event.status in (Event.Status.CANCELLED, Event.Status.FINALIZED):
        raise ValidationError(
            f"No se puede editar un evento en estado '{event.get_status_display()}'."
        )

    if 'title' in validated_data and 'slug' not in validated_data:
        validated_data['slug'] = generate_unique_slug(
            validated_data['title'], exclude_id=event.id
        )

    for field, value in validated_data.items():
        setattr(event, field, value)

    event.save()
    return event


def transition_event_status(event: Event, user, new_status: str) -> Event:
    """
    Transition an event to a new status following the defined workflow.

    Valid transitions:
        draft       → published | cancelled
        published   → closed | cancelled
        closed      → finalized
        cancelled   → (terminal)
        finalized   → (terminal)

    Args:
        event: The Event instance
        user: The authenticated user
        new_status: Target status string

    Returns:
        Event: The updated event

    Raises:
        ValidationError: If the transition is not allowed
    """
    if not event.can_transition_to(new_status):
        raise ValidationError(
            f"No se puede cambiar el estado de '{event.get_status_display()}' a "
            f"'{Event.Status(new_status).label}'."
        )

    if new_status == Event.Status.PUBLISHED:
        _validate_ready_to_publish(event)
        event.published_at = timezone.now()

    event.status = new_status
    event.save(update_fields=['status', 'published_at', 'updated_at']
               if new_status == Event.Status.PUBLISHED
               else ['status', 'updated_at'])
    return event


def _validate_ready_to_publish(event: Event):
    """
    Validate that an event has all required fields before publishing.

    Raises:
        ValidationError: If required fields are missing
    """
    errors = []

    if not event.title:
        errors.append("El evento debe tener un título.")

    if not event.start_date or not event.end_date:
        errors.append("El evento debe tener fechas de inicio y fin.")
    elif event.start_date >= event.end_date:
        errors.append("La fecha de inicio debe ser anterior a la fecha de fin.")
    elif event.end_date <= timezone.now():
        errors.append("No se puede publicar un evento que ya finalizó.")

    if not event.is_virtual and not event.location:
        errors.append("Un evento presencial debe tener una ubicación.")

    if errors:
        raise ValidationError(errors)
