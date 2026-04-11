"""
Communication services for EventSync.

Core email-sending logic. All functions are idempotent: they check EmailLog
before sending to avoid duplicate emails on task retries. QR codes are
embedded as CID inline attachments (multipart/related) so they render in
Gmail, Outlook, and Apple Mail — unlike data:base64 URIs which are blocked
by CSP in most email clients.
"""
import io
from email.mime.image import MIMEImage

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

def _generate_qr_png(qr_token: str) -> bytes:
    """
    Generate a QR code PNG and return the raw bytes.

    Returns bytes instead of base64 — the caller attaches it as a CID inline
    image. The QR encodes the full check-in URL so scanning it from any QR
    reader opens the check-in flow directly, not just a raw token.
    """
    qr_url = f"{_CHECKIN_BASE_URL}/{qr_token}"

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(qr_url)
    qr.make(fit=True)

    img = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


def _send_email(
    to_email: str,
    subject: str,
    template_base: str,
    context: dict,
    inline_image: bytes | None = None,
    inline_image_cid: str = 'qr_image',
) -> None:
    """
    Render HTML + plain text templates and send via the configured backend.

    In development, EMAIL_BACKEND=console prints to stdout.
    In production, anymail routes to Resend.

    Args:
        inline_image: Optional PNG bytes to embed as a CID inline attachment.
            Referenced in the HTML template as <img src="cid:{inline_image_cid}">.
            Works in Gmail, Outlook, and Apple Mail — unlike data:base64 URIs
            which are blocked by CSP in most email clients.
        inline_image_cid: Content-ID for referencing the image in the template.
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

    if inline_image is not None:
        mime_img = MIMEImage(inline_image, _subtype='png')
        mime_img.add_header('Content-ID', f'<{inline_image_cid}>')
        mime_img.add_header('Content-Disposition', 'inline', filename=f'{inline_image_cid}.png')
        msg.mixed_subtype = 'related'
        msg.attach(mime_img)

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
    qr_png_bytes = None if is_waitlisted else _generate_qr_png(registration.qr_token)
    qr_url = f"{_CHECKIN_BASE_URL}/{registration.qr_token}"
    subject = f"Registro {'en lista de espera' if is_waitlisted else 'confirmado'}: {event.title}"

    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
    cancellation_link = (
        f"{frontend_url}/registrations/cancel?token={registration.cancellation_token}"
    )

    context = {
        'registration': registration,
        'event': event,
        'is_waitlisted': is_waitlisted,
        'qr_url': qr_url,
        'cancellation_link': cancellation_link,
    }

    try:
        _send_email(
            to_email=registration.email,
            subject=subject,
            template_base='emails/confirmation',
            context=context,
            inline_image=qr_png_bytes,
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


def send_cancellation_email(registration: Registration) -> None:
    """
    Send a cancellation confirmation email to an attendee.

    Idempotent — no-ops if a successful cancellation email was already sent.

    Args:
        registration: Cancelled Registration instance.
    """
    if _already_sent(registration, EmailLog.EmailType.CANCELLATION):
        return

    event = registration.event
    subject = f"Cancelación confirmada: {event.title}"

    context = {
        'registration': registration,
        'event': event,
    }

    try:
        _send_email(
            to_email=registration.email,
            subject=subject,
            template_base='emails/cancellation',
            context=context,
        )
        _log_email(
            event=event,
            registration=registration,
            email_type=EmailLog.EmailType.CANCELLATION,
            recipient_email=registration.email,
            recipient_name=registration.full_name,
            subject=subject,
            status=EmailLog.Status.SENT,
        )
    except Exception as exc:
        _log_email(
            event=event,
            registration=registration,
            email_type=EmailLog.EmailType.CANCELLATION,
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


ROLE_LABELS = {
    'tenant_admin': 'Administrador',
    'organizer': 'Organizador de Eventos',
    'checkin_staff': 'Staff de Check-in',
}


def send_invitation_email(invitation) -> None:
    """
    Send an invitation email to a new team member.

    The link points to the Next.js frontend invite/accept page, which
    calls the backend API to complete the registration.
    """
    from django.conf import settings as django_settings

    accept_url = (
        f"{django_settings.FRONTEND_URL}/invite/accept"
        f"?token={invitation.token}"
    )

    first_name = invitation.first_name or invitation.email.split('@')[0]
    invited_by_name = invitation.invited_by.get_full_name() or invitation.invited_by.email
    organization_name = getattr(invitation.tenant, 'name', 'tu organización')
    role_label = ROLE_LABELS.get(invitation.role, invitation.role)

    _send_email(
        to_email=invitation.email,
        subject=f'Te han invitado a unirte a {organization_name} en EventSync',
        template_base='emails/invitation',
        context={
            'first_name': first_name,
            'invited_by_name': invited_by_name,
            'organization_name': organization_name,
            'role_label': role_label,
            'accept_url': accept_url,
        },
    )


def send_password_reset_email(user) -> None:
    """
    Send a password reset email with a one-time link.

    The link points to the Next.js frontend password-reset page, which
    calls POST /api/auth/password-reset/confirm/ to complete the reset.
    """
    from django.conf import settings as django_settings

    reset_url = (
        f"{django_settings.FRONTEND_URL}/password-reset"
        f"?token={user.email_verification_token}"
    )

    _send_email(
        to_email=user.email,
        subject='Restablece tu contraseña en EventSync',
        template_base='emails/password_reset',
        context={
            'first_name': user.first_name,
            'reset_url': reset_url,
        },
    )
