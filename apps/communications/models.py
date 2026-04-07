"""
EmailLog model for Communications app.

Tracks every email sent from EventSync — transactional (confirmation,
reminders, post-event) and manual (organizer broadcasts). Used for
deduplication (idempotency) and audit trail.
"""
import uuid
from django.db import models


class EmailLog(models.Model):
    """
    Immutable record of an email send attempt.

    Created after every send attempt, successful or not. The combination
    (registration, email_type, status=sent) is used as an idempotency
    key to prevent duplicate emails.
    """

    class EmailType(models.TextChoices):
        CONFIRMATION = 'confirmation', 'Confirmación de Registro'
        REMINDER_24H = 'reminder_24h', 'Recordatorio 24h'
        REMINDER_1H  = 'reminder_1h',  'Recordatorio 1h'
        POST_EVENT   = 'post_event',   'Post-evento'
        MANUAL       = 'manual',       'Envío Manual'
        CANCELLATION = 'cancellation', 'Cancelación'

    class Status(models.TextChoices):
        SENT   = 'sent',   'Enviado'
        FAILED = 'failed', 'Fallido'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Context
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='email_logs',
    )
    registration = models.ForeignKey(
        'registrations.Registration',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_logs',
    )

    # Email metadata
    email_type      = models.CharField(max_length=20, choices=EmailType.choices, db_index=True)
    recipient_email = models.EmailField()
    recipient_name  = models.CharField(max_length=200)
    subject         = models.CharField(max_length=300)

    # Result
    status        = models.CharField(max_length=10, choices=Status.choices, db_index=True)
    error_message = models.TextField(blank=True)
    sent_at       = models.DateTimeField(null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'email_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event', 'email_type']),
            models.Index(fields=['registration', 'email_type']),
        ]

    def __str__(self):
        return (
            f"{self.get_email_type_display()} → {self.recipient_email} "
            f"({self.get_status_display()})"
        )
