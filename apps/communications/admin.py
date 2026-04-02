"""
Django Admin for Communications app.
"""
from django.contrib import admin
from .models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display  = ['email_type', 'recipient_email', 'event', 'status', 'sent_at', 'created_at']
    list_filter   = ['email_type', 'status']
    search_fields = ['recipient_email', 'recipient_name', 'subject']
    ordering      = ['-created_at']
    readonly_fields = [
        'id', 'event', 'registration', 'email_type', 'recipient_email',
        'recipient_name', 'subject', 'status', 'error_message', 'sent_at', 'created_at',
    ]
