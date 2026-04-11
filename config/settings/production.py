"""
Production settings for EventSync project.
"""
from .base import *

DEBUG = False

# Security
# Railway termina SSL en el proxy — el contenedor recibe HTTP internamente.
# SECURE_SSL_REDIRECT=True causa loop de 301. Ver CLAUDE.md.
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Sentry
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

SENTRY_DSN = config('SENTRY_DSN', default='')
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

# Email
ANYMAIL = {
    'RESEND_API_KEY': config('RESEND_API_KEY'),
}
EMAIL_BACKEND = 'anymail.backends.resend.EmailBackend'

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
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
