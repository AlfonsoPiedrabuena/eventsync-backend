import uuid
from django.db import models


class RegistrationFormField(models.Model):

    class FieldType(models.TextChoices):
        TEXT = 'text', 'Texto corto'
        TEXTAREA = 'textarea', 'Texto largo'
        EMAIL = 'email', 'Email'
        PHONE = 'phone', 'Teléfono'
        SELECT = 'select', 'Lista de opciones'
        CHECKBOX = 'checkbox', 'Casilla de verificación'
        NUMBER = 'number', 'Número'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        'events.Event',
        on_delete=models.CASCADE,
        related_name='form_fields',
    )
    label = models.CharField(max_length=200)
    field_type = models.CharField(
        max_length=20,
        choices=FieldType.choices,
        default=FieldType.TEXT,
    )
    placeholder = models.CharField(max_length=200, blank=True)
    is_required = models.BooleanField(default=False)
    is_enabled = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    options = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista de opciones para tipo select: ['Opción A', 'Opción B']",
    )
    field_key = models.SlugField(
        max_length=100,
        help_text="Identificador interno del campo. Ej: 'cargo', 'empresa'",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'registration_form_fields'
        ordering = ['order', 'created_at']
        unique_together = [('event', 'field_key')]

    def __str__(self):
        return f"{self.event.title} — {self.label}"
