"""
Celery configuration for EventSync project.
"""
import os
from celery import Celery
from celery.schedules import crontab

# Set default Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('eventsync')

# Load config from Django settings with CELERY_ namespace
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all installed apps
app.autodiscover_tasks()

# Celery Beat schedule for periodic tasks
app.conf.beat_schedule = {
    # Example: Check for events to finalize
    'finalize-past-events': {
        'task': 'apps.events.tasks.finalize_past_events',
        'schedule': crontab(hour=1, minute=0),  # Run daily at 1:00 AM
    },
    # Example: Send scheduled reminders
    'send-event-reminders': {
        'task': 'apps.communications.tasks.send_scheduled_reminders',
        'schedule': crontab(hour='*/1'),  # Run every hour
    },
}

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
