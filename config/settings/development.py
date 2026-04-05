"""
Development settings for EventSync project.
"""
from .base import *

DEBUG = True

# Email: respeta EMAIL_BACKEND del .env (default: console)
# Para usar Resend en desarrollo, setear EMAIL_BACKEND=anymail.backends.resend.EmailBackend en .env

# Django Debug Toolbar
INSTALLED_APPS += ['debug_toolbar', 'django_extensions']
MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')

INTERNAL_IPS = ['127.0.0.1', 'localhost']

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
