"""
Tests for Communications service layer.
"""
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.utils import timezone
from django_tenants.test.cases import TenantTestCase

from apps.authentication.models import User
from apps.events.models import Event
from apps.registrations.models import Registration
from apps.communications import services
from apps.communications.models import EmailLog


class CommunicationsServiceSetUp(TenantTestCase):
    """Common fixtures for communications tests."""

    def setUp(self):
        self.organizer = User.objects.create_user(
            email='org@test.com', password='pass',
            first_name='Org', last_name='User',
            role='organizer', is_email_verified=True,
        )
        now = timezone.now()
        self.event = Event.objects.create(
            title='Test Conference 2026',
            slug='test-conf-2026',
            organizer=self.organizer,
            status=Event.Status.PUBLISHED,
            is_virtual=True,
            start_date=now + timedelta(days=2),
            end_date=now + timedelta(days=2, hours=4),
        )
        self.registration = Registration.objects.create(
            event=self.event,
            first_name='Ana',
            last_name='López',
            email='ana@test.com',
            status=Registration.Status.CONFIRMED,
            qr_token='test-qr-token-abc123',
        )


class SendConfirmationEmailTest(CommunicationsServiceSetUp):

    @patch('apps.communications.services.EmailMultiAlternatives')
    def test_sends_confirmation_email(self, mock_email_cls):
        """Confirmation email is sent and logged on first call."""
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg

        services.send_confirmation_email(self.registration)

        mock_msg.send.assert_called_once()
        log = EmailLog.objects.get(
            registration=self.registration,
            email_type=EmailLog.EmailType.CONFIRMATION,
        )
        self.assertEqual(log.status, EmailLog.Status.SENT)
        self.assertEqual(log.recipient_email, 'ana@test.com')

    @patch('apps.communications.services.EmailMultiAlternatives')
    def test_idempotent_on_second_call(self, mock_email_cls):
        """Second call is a no-op if confirmation was already sent."""
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg

        services.send_confirmation_email(self.registration)
        services.send_confirmation_email(self.registration)

        mock_msg.send.assert_called_once()  # Only one actual send
        self.assertEqual(
            EmailLog.objects.filter(
                registration=self.registration,
                email_type=EmailLog.EmailType.CONFIRMATION,
            ).count(),
            1,
        )

    @patch('apps.communications.services.EmailMultiAlternatives')
    def test_logs_failure_on_smtp_error(self, mock_email_cls):
        """SMTP error is logged as FAILED and re-raised."""
        mock_msg = MagicMock()
        mock_msg.send.side_effect = Exception("SMTP error")
        mock_email_cls.return_value = mock_msg

        with self.assertRaises(Exception):
            services.send_confirmation_email(self.registration)

        log = EmailLog.objects.get(
            registration=self.registration,
            email_type=EmailLog.EmailType.CONFIRMATION,
        )
        self.assertEqual(log.status, EmailLog.Status.FAILED)
        self.assertIn('SMTP error', log.error_message)

    @patch('apps.communications.services.EmailMultiAlternatives')
    def test_waitlisted_registration_has_no_qr(self, mock_email_cls):
        """Waitlisted registrations don't get a QR code in context."""
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg

        self.registration.status = Registration.Status.WAITLISTED
        self.registration.save()

        with patch('apps.communications.services.render_to_string') as mock_render:
            mock_render.return_value = ''
            services.send_confirmation_email(self.registration)

        # Context passed to render_to_string should have qr_base64=None
        call_args = mock_render.call_args_list
        context = call_args[0][0][1]  # First call, second positional arg
        self.assertIsNone(context['qr_base64'])
        self.assertTrue(context['is_waitlisted'])


class SendReminderEmailTest(CommunicationsServiceSetUp):

    @patch('apps.communications.services.EmailMultiAlternatives')
    def test_sends_24h_reminder(self, mock_email_cls):
        """24h reminder is sent and logged correctly."""
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg

        services.send_reminder_email(self.registration, 'reminder_24h')

        log = EmailLog.objects.get(
            registration=self.registration,
            email_type=EmailLog.EmailType.REMINDER_24H,
        )
        self.assertEqual(log.status, EmailLog.Status.SENT)

    @patch('apps.communications.services.EmailMultiAlternatives')
    def test_sends_1h_reminder(self, mock_email_cls):
        """1h reminder is logged with the correct type."""
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg

        services.send_reminder_email(self.registration, 'reminder_1h')

        self.assertTrue(
            EmailLog.objects.filter(
                registration=self.registration,
                email_type=EmailLog.EmailType.REMINDER_1H,
                status=EmailLog.Status.SENT,
            ).exists()
        )

    @patch('apps.communications.services.EmailMultiAlternatives')
    def test_24h_and_1h_are_independent(self, mock_email_cls):
        """24h and 1h reminders are logged separately and both send."""
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg

        services.send_reminder_email(self.registration, 'reminder_24h')
        services.send_reminder_email(self.registration, 'reminder_1h')

        self.assertEqual(mock_msg.send.call_count, 2)

    def test_invalid_reminder_type_raises(self):
        """Passing an unknown reminder_type raises ValueError."""
        with self.assertRaises(ValueError):
            services.send_reminder_email(self.registration, 'reminder_48h')


class SendPostEventEmailTest(CommunicationsServiceSetUp):

    @patch('apps.communications.services.EmailMultiAlternatives')
    def test_sends_attendee_email(self, mock_email_cls):
        """Attendee who checked in gets thank-you email."""
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg

        self.registration.checked_in = True
        self.registration.save()

        services.send_post_event_email(self.registration)

        log = EmailLog.objects.get(
            registration=self.registration,
            email_type=EmailLog.EmailType.POST_EVENT,
        )
        self.assertEqual(log.status, EmailLog.Status.SENT)

    @patch('apps.communications.services.EmailMultiAlternatives')
    def test_sends_no_show_email(self, mock_email_cls):
        """Attendee who didn't check in gets no-show email."""
        mock_msg = MagicMock()
        mock_email_cls.return_value = mock_msg

        self.registration.checked_in = False
        self.registration.save()

        with patch('apps.communications.services.render_to_string') as mock_render:
            mock_render.return_value = ''
            services.send_post_event_email(self.registration)

        context = mock_render.call_args_list[0][0][1]
        self.assertFalse(context['was_attendee'])
