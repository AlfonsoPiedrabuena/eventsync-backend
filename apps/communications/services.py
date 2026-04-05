"""
Communication services for EventSync.

Core email-sending logic. All functions are idempotent: they check EmailLog
before sending to avoid duplicate emails on task retries. QR codes are
embedded as base64 PNG so emails work without S3.
"""
import io
import base64

import qrcode
from qrcode.image.pil import PilImage

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from apps.events.models import Event
from apps.registrations.models import Registration
from .models import EmailLog


# Base URL used to build the check-in QR link embedded in confirmation emails.
# Override in settings with CHECKIN_BASE_URL for custom domains.
_CHECKIN_BASE_URL = getattr(settings, 'CHECKIN_BASE_URL', 'https://eventsync.app/checkin')


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_qr_base64(qr_token: str) -> str:
    """
    Generate a QR code PNG and return it as a base64 string.

    The QR encodes the full check-in URL so scanning it from any QR reader
    opens the check-in flow directly, not just a raw token.
    """
    qr_url = f"{_CHECKIN_BASE_URL}/{qr_token}"

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_url)
    qr.make(fit=True)

    img = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def _send_email(to_email: str, subject: str, template_base: str, context: dict) -> None:
    """
    Render HTML + plain text templates and send via the configured backend.

    In development, EMAIL_BACKEND=console prints to stdout.
    In production, anymail routes to SendGrid.
    """
    html_content = render_to_string(f"{template_base}.html", context)
    text_content = render_to_string(f"{template_base}.txt", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send()


def _log_email(
    *,
    event: Event,
    registration: Registration | None,
    email_type: str,
    recipient_email: str,
    recipient_name: str,
    subject: str,
    status: str,
    error_message: str = '',
) -> EmailLog:
    """Create an EmailLog record for an attempted send."""
    return EmailLog.objects.create(
        event=event,
        registration=registration,
        email_type=email_type,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        subject=subject,
        status=status,
        error_message=error_message,
        sent_at=timezone.now() if status == EmailLog.Status.SENT else None,
    )


def _already_sent(registration: Registration, email_type: str) -> bool:
    """Return True if a successful email of this type was already sent to this registration."""
    return EmailLog.objects.filter(
        registration=registration,
        email_type=email_type,
        status=EmailLog.Status.SENT,
    ).exists()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_confirmation_email(registration: Registration) -> None:
    """
    Send a registration confirmation email with embedded QR code.

    Idempotent — no-ops if a successful confirmation was already sent.

    Args:
        registration: Confirmed or waitlisted Registration instance.
    """
    if _already_sent(registration, EmailLog.EmailType.CONFIRMATION):
        return

    event = registration.event
    is_waitlisted = registration.status == Registration.Status.WAITLISTED
    qr_base64 = None if is_waitlisted else _generate_qr_base64(registration.qr_token)
    qr_url = f"{_CHECKIN_BASE_URL}/{registration.qr_token}"
    subject = f"Registro {'en lista de espera' if is_waitlisted else 'confirmado'}: {event.title}"

    context = {
        'registration': registration,
        'event': event,
        'is_waitlisted': is_waitlisted,
        'qr_base64': qr_base64,
        'qr_url': qr_url,
    }

    try:
        _send_email(
            to_email=registration.email,
            subject=subject,
            template_base='emails/confirmation',
            context=context,
        )
        _log_email(
            event=event,
            registration=registration,
            email_type=EmailLog.EmailType.CONFIRMATION,
            recipient_email=registration.email,
            recipient_name=registration.full_name,
            subject=subject,
            status=EmailLog.Status.SENT,
        )
    except Exception as exc:
        _log_email(
            event=event,
            registration=registration,
            email_type=EmailLog.EmailType.CONFIRMATION,
            recipient_email=registration.email,
            recipient_name=registration.full_name,
            subject=subject,
            status=EmailLog.Status.FAILED,
            error_message=str(exc),
        )
        raise


def send_reminder_email(registration: Registration, reminder_type: str) -> None:
    """
    Send a pre-event reminder (24h or 1h before start).

    Idempotent per reminder_type.

    Args:
        registration: Confirmed Registration instance.
        reminder_type: 'reminder_24h' or 'reminder_1h'.
    """
    valid_types = (EmailLog.EmailType.REMINDER_24H, EmailLog.EmailType.REMINDER_1H)
    if reminder_type not in valid_types:
        raise ValueError(f"Invalid reminder_type: {reminder_type}")

    if _already_sent(registration, reminder_type):
        return

    event = registration.event
    hours = 24 if reminder_type == EmailLog.EmailType.REMINDER_24H else 1
    subject = f"Recordatorio: {event.title} comienza en {hours} hora{'s' if hours > 1 else ''}"

    context = {
        'registration': registration,
        'event': event,
        'hours_until': hours,
    }

    try:
        _send_email(
            to_email=registration.email,
            subject=subject,
            template_base='emails/reminder',
            context=context,
        )
        _log_email(
            event=event,
            registration=registration,
            email_type=reminder_type,
            recipient_email=registration.email,
            recipient_name=registration.full_name,
            subject=subject,
            status=EmailLog.Status.SENT,
        )
    except Exception as exc:
        _log_email(
            event=event,
            registration=registration,
            email_type=reminder_type,
            recipient_email=registration.email,
            recipient_name=registration.full_name,
            subject=subject,
            status=EmailLog.Status.FAILED,
            error_message=str(exc),
        )
        raise


def send_post_event_email(registration: Registration) -> None:
    """
    Send a post-event thank-you email.

    Distinguishes between attendees (checked_in=True) and no-shows.
    Idempotent.

    Args:
        registration: Confirmed Registration instance.
    """
    if _already_sent(registration, EmailLog.EmailType.POST_EVENT):
        return

    event = registration.event
    was_attendee = registration.checked_in
    subject = (
        f"Gracias por asistir a: {event.title}"
        if was_attendee
        else f"Te esperamos la próxima vez: {event.title}"
    )

    context = {
        'registration': registration,
        'event': event,
        'was_attendee': was_attendee,
    }

    try:
        _send_email(
            to_email=registration.email,
            subject=subject,
            template_base='emails/post_event',
            context=context,
        )
        _log_email(
            event=event,
            registration=registration,
            email_type=EmailLog.EmailType.POST_EVENT,
            recipient_email=registration.email,
            recipient_name=registration.full_name,
            subject=subject,
            status=EmailLog.Status.SENT,
        )
    except Exception as exc:
        _log_email(
            event=event,
            registration=registration,
            email_type=EmailLog.EmailType.POST_EVENT,
            recipient_email=registration.email,
            recipient_name=registration.full_name,
            subject=subject,
            status=EmailLog.Status.FAILED,
            error_message=str(exc),
        )
        raise


def send_manual_email_to_registration(
    registration: Registration,
    subject: str,
    message: str,
) -> None:
    """
    Send a custom manual email from the organizer to a single registration.

    Not idempotent — manual sends can repeat. Each send is logged.

    Args:
        registration: Target Registration instance.
        subject: Email subject line.
        message: HTML-safe custom message body.
    """
    event = registration.event
    context = {
        'registration': registration,
        'event': event,
        'message': message,
    }

    try:
        _send_email(
            to_email=registration.email,
            subject=subject,
            template_base='emails/manual',
            context=context,
        )
        _log_email(
            event=event,
            registration=registration,
            email_type=EmailLog.EmailType.MANUAL,
            recipient_email=registration.email,
            recipient_name=registration.full_name,
            subject=subject,
            status=EmailLog.Status.SENT,
        )
    except Exception as exc:
        _log_email(
            event=event,
            registration=registration,
            email_type=EmailLog.EmailType.MANUAL,
            recipient_email=registration.email,
            recipient_name=registration.full_name,
            subject=subject,
            status=EmailLog.Status.FAILED,
            error_message=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# Auth emails  (not tied to a Registration — no EmailLog)
# ---------------------------------------------------------------------------

def send_verification_email(user) -> None:
    """
    Send an account verification email to a newly registered user.

    The link points to the Next.js frontend verify-email page, which
    calls the backend API to complete the verification.
    """
    from django.conf import settings as django_settings

    verification_url = (
        f"{django_settings.FRONTEND_URL}/verify-email"
        f"?token={user.email_verification_token}"
    )

    _send_email(
        to_email=user.email,
        subject='Verifica tu cuenta en EventSync',
        template_base='emails/verification',
        context={
            'first_name': user.first_name,
            'organization_name': getattr(user.tenant, 'name', 'tu organización'),
            'verification_url': verification_url,
        },
    )
