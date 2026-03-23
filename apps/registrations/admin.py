"""
Admin configuration for Registrations app.
"""
from django.contrib import admin
from .models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'event', 'status', 'checked_in', 'created_at')
    list_filter = ('status', 'checked_in', 'event__status')
    search_fields = ('first_name', 'last_name', 'email', 'event__title')
    readonly_fields = ('id', 'qr_token', 'created_at', 'updated_at')
    ordering = ('-created_at',)
