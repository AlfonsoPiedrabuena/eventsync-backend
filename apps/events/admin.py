"""
Django Admin configuration for Events app.
"""
from django.contrib import admin
from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'organizer', 'start_date', 'end_date', 'max_capacity', 'created_at')
    list_filter = ('status', 'modality', 'start_date')
    search_fields = ('title', 'slug', 'organizer__email')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ('id', 'created_at', 'updated_at', 'published_at')
    date_hierarchy = 'start_date'
    ordering = ('-created_at',)

    fieldsets = (
        ('Información General', {
            'fields': ('id', 'title', 'slug', 'description', 'cover_image')
        }),
        ('Fecha y Lugar', {
            'fields': ('start_date', 'end_date', 'modality', 'location', 'location_url', 'virtual_access_url')
        }),
        ('Capacidad y Estado', {
            'fields': ('max_capacity', 'status', 'organizer')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'published_at'),
            'classes': ('collapse',)
        }),
    )
