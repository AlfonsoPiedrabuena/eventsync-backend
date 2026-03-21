"""
Test settings for EventSync project.
"""
from .base import *

DEBUG = True

# Use faster password hashing in tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# In-memory SQLite for tests (faster)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Email to memory backend in tests
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Celery in eager mode for tests
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
