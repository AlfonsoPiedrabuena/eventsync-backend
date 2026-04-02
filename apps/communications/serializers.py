"""
Serializers for Communications app.
"""
from rest_framework import serializers
from .models import EmailLog


class EmailLogSerializer(serializers.ModelSerializer):
    email_type_display = serializers.CharField(source='get_email_type_display', read_only=True)
    status_display     = serializers.CharField(source='get_status_display',     read_only=True)

    class Meta:
        model = EmailLog
        fields = [
            'id',
            'email_type',
            'email_type_display',
            'recipient_email',
            'recipient_name',
            'subject',
            'status',
            'status_display',
            'error_message',
            'sent_at',
            'created_at',
        ]


class ManualSendSerializer(serializers.Serializer):
    SEGMENT_CHOICES = [
        ('all',        'Todos (confirmados + lista de espera)'),
        ('confirmed',  'Solo confirmados'),
        ('waitlisted', 'Solo lista de espera'),
        ('checked_in', 'Solo asistentes (hicieron check-in)'),
        ('no_show',    'No shows (confirmados, sin check-in)'),
    ]

    subject = serializers.CharField(max_length=300)
    message = serializers.CharField()
    segment = serializers.ChoiceField(
        choices=[s[0] for s in SEGMENT_CHOICES],
        default='all',
    )
