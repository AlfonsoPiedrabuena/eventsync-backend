"""
Event model for EventSync.
"""
import uuid
from django.db import models
from django.utils.text import slugify
from django.utils import timezone


class Event(models.Model):
    """
    Core event model for EventSync.

    An event belongs to a tenant (organization) and goes through a
    defined state machine: draft → published → closed | cancelled → finalized.
    """

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Borrador'
        PUBLISHED = 'published', 'Publicado'
        CLOSED = 'closed', 'Cerrado'
        CANCELLED = 'cancelled', 'Cancelado'
        FINALIZED = 'finalized', 'Finalizado'

    # Valid transitions: {current_status: [allowed_next_statuses]}
    VALID_TRANSITIONS = {
        Status.DRAFT: [Status.PUBLISHED, Status.CANCELLED],
        Status.PUBLISHED: [Status.CLOSED, Status.CANCELLED],
        Status.CLOSED: [Status.FINALIZED],
        Status.CANCELLED: [],
        Status.FINALIZED: [],
    }

    # Identity
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, db_index=True)
    description = models.TextField(blank=True)

    # Location
    is_virtual = models.BooleanField(default=False)
    location = models.CharField(max_length=300, blank=True)
    location_url = models.URLField(blank=True)

    # Dates
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()

    # Capacity
    max_capacity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Número máximo de asistentes. Vacío = sin límite."
    )

    # Media
    cover_image = models.ImageField(
        upload_to='events/covers/',
        null=True,
        blank=True
    )

    # Status workflow
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True
    )

    # Ownership
    organizer = models.ForeignKey(
        'authentication.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='organized_events'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'events'
        verbose_name = 'Event'
        verbose_name_plural = 'Events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['start_date']),
            models.Index(fields=['organizer']),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    @property
    def is_past(self):
        """Return True if the event has already ended."""
        return self.end_date < timezone.now()

    @property
    def is_upcoming(self):
        """Return True if the event hasn't started yet."""
        return self.start_date > timezone.now()

    @property
    def registration_count(self):
        """Return the number of confirmed registrations (requires E3 - registrations app)."""
        try:
            return self.registrations.filter(status='confirmed').count()
        except AttributeError:
            return 0

    @property
    def spots_remaining(self):
        """Return the number of remaining spots, or None if unlimited."""
        if self.max_capacity is None:
            return None
        return max(0, self.max_capacity - self.registration_count)

    def can_transition_to(self, new_status):
        """Check if the event can transition to the given status."""
        return new_status in self.VALID_TRANSITIONS.get(self.status, [])

    def is_open_for_registration(self):
        """Return True if attendees can register for this event."""
        return (
            self.status == self.Status.PUBLISHED
            and not self.is_past
            and (self.max_capacity is None or self.spots_remaining > 0)
        )
