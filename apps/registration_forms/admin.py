from django.contrib import admin
from .models import RegistrationFormField


@admin.register(RegistrationFormField)
class RegistrationFormFieldAdmin(admin.ModelAdmin):
    list_display = ['label', 'event', 'field_type', 'field_key', 'is_required', 'is_enabled', 'order']
    list_filter = ['field_type', 'is_required', 'is_enabled']
    search_fields = ['label', 'field_key', 'event__title']
    ordering = ['event', 'order']
