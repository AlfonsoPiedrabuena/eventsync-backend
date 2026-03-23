"""
Registration model for EventSync.

An attendee registers for a published event. The registration is confirmed
immediately if there are spots available, or placed on a waitlist otherwise.
Each registration receives a unique QR token used for check-in (E4).
"""
import uuid
from django.db import models


class Registration(models.Model):
    """
    Represents an attendee's registration for an event.

    Status flow:
        confirmed  — registered and attending
        waitlisted — capacity full, on waitlist
        cancelled  — registration cancelled (by attendee or organizer)
    """

    class Status(models.TextChoices):
        CONFIRMED = 'confirmed', 'Confirmado'
        WAITLISTED = 'waitlisted', 'En lista de espera'
        CANCELLED = 'cancelled', 'Cancelado'

    # Identity
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Relations
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='registrations',
    )

    # Attendee info
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(db_index=True)
    phone = models.CharField(max_length=30, blank=True)
    company = models.CharField(max_length=200, blank=True)
    position = models.CharField(max_length=200, blank=True)

    # Status
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
        db_index=True,
    )

    # Check-in (used by E4)
    checked_in = models.BooleanField(default=False)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    qr_token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        editable=False,
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'registrations'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'email'],
                condition=models.Q(status__in=['confirmed', 'waitlisted']),
                name='unique_active_registration_per_event_email',
            )
        ]
        indexes = [
            models.Index(fields=['event', 'status']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.event.title} ({self.get_status_display()})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
