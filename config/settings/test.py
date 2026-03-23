"""
Test settings for EventSync project.
"""
from .base import *

DEBUG = True

# Use faster password hashing in tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# PostgreSQL required for django-tenants (schema-based multi-tenancy)
# Uses a separate test database to avoid polluting development data
from decouple import config as env_config

DATABASES = {
    'default': {
        'ENGINE': 'django_tenants.postgresql_backend',
        'NAME': env_config('TEST_DB_NAME', default='eventsync_test'),
        'USER': env_config('DB_USER', default='postgres'),
        'PASSWORD': env_config('DB_PASSWORD', default=''),
        'HOST': env_config('DB_HOST', default='localhost'),
        'PORT': env_config('DB_PORT', default='5432'),
    }
}

# Email to memory backend in tests
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Celery in eager mode for tests
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
