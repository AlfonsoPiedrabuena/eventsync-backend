"""
Tests for Registrations service layer.
"""
from datetime import timedelta
from django.utils import timezone
from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase

from apps.events.models import Event
from apps.authentication.models import User
from apps.registrations.models import Registration
from apps.registrations import services


class RegistrationServiceTestCase(TenantTestCase):
    """Base setUp for registration service tests."""

    def setUp(self):
        self.organizer = User.objects.create_user(
            email='org@test.com', password='pass',
            first_name='Org', last_name='User',
            role='organizer', is_email_verified=True,
        )
        now = timezone.now()
        self.event = Event.objects.create(
            title='Conf 2026',
            slug='conf-2026',
            organizer=self.organizer,
            status=Event.Status.PUBLISHED,
            is_virtual=True,
            start_date=now + timedelta(days=30),
            end_date=now + timedelta(days=30, hours=4),
        )
        self.attendee_data = {
            'first_name': 'Ana',
            'last_name': 'López',
            'email': 'ana@test.com',
        }

    # ── create_registration ──────────────────────────────────────────────────

    def test_create_registration_confirmed(self):
        reg = services.create_registration(self.event, self.attendee_data)
        self.assertEqual(reg.status, Registration.Status.CONFIRMED)
        self.assertEqual(reg.email, 'ana@test.com')
        self.assertIsNotNone(reg.qr_token)

    def test_create_registration_generates_unique_qr_token(self):
        r1 = services.create_registration(self.event, self.attendee_data)
        r2 = services.create_registration(self.event, {**self.attendee_data, 'email': 'b@test.com'})
        self.assertNotEqual(r1.qr_token, r2.qr_token)

    def test_create_registration_waitlisted_when_full(self):
        self.event.max_capacity = 1
        self.event.save()
        services.create_registration(self.event, self.attendee_data)
        r2 = services.create_registration(self.event, {**self.attendee_data, 'email': 'b@test.com'})
        self.assertEqual(r2.status, Registration.Status.WAITLISTED)

    def test_create_registration_normalizes_email(self):
        data = {**self.attendee_data, 'email': 'ANA@TEST.COM'}
        reg = services.create_registration(self.event, data)
        self.assertEqual(reg.email, 'ana@test.com')

    def test_create_registration_rejects_draft_event(self):
        self.event.status = Event.Status.DRAFT
        self.event.save()
        with self.assertRaises(ValidationError):
            services.create_registration(self.event, self.attendee_data)

    def test_create_registration_rejects_cancelled_event(self):
        self.event.status = Event.Status.CANCELLED
        self.event.save()
        with self.assertRaises(ValidationError):
            services.create_registration(self.event, self.attendee_data)

    def test_create_registration_rejects_past_event(self):
        self.event.start_date = timezone.now() - timedelta(days=2)
        self.event.end_date = timezone.now() - timedelta(days=1)
        self.event.save()
        with self.assertRaises(ValidationError):
            services.create_registration(self.event, self.attendee_data)

    def test_create_registration_rejects_duplicate_email(self):
        services.create_registration(self.event, self.attendee_data)
        with self.assertRaises(ValidationError):
            services.create_registration(self.event, self.attendee_data)

    def test_cancelled_then_reregister_allowed(self):
        """After cancellation, same email can register again."""
        reg = services.create_registration(self.event, self.attendee_data)
        services.cancel_registration(reg)
        reg2 = services.create_registration(self.event, self.attendee_data)
        self.assertEqual(reg2.status, Registration.Status.CONFIRMED)

    # ── cancel_registration ──────────────────────────────────────────────────

    def test_cancel_confirmed_registration(self):
        reg = services.create_registration(self.event, self.attendee_data)
        cancelled = services.cancel_registration(reg)
        self.assertEqual(cancelled.status, Registration.Status.CANCELLED)

    def test_cancel_already_cancelled_raises(self):
        reg = services.create_registration(self.event, self.attendee_data)
        services.cancel_registration(reg)
        with self.assertRaises(ValidationError):
            services.cancel_registration(reg)

    def test_cancel_confirmed_promotes_waitlisted(self):
        self.event.max_capacity = 1
        self.event.save()
        r1 = services.create_registration(self.event, self.attendee_data)
        r2 = services.create_registration(self.event, {**self.attendee_data, 'email': 'b@test.com'})
        self.assertEqual(r2.status, Registration.Status.WAITLISTED)

        services.cancel_registration(r1)

        r2.refresh_from_db()
        self.assertEqual(r2.status, Registration.Status.CONFIRMED)

    def test_cancel_waitlisted_does_not_promote(self):
        self.event.max_capacity = 1
        self.event.save()
        services.create_registration(self.event, self.attendee_data)
        r2 = services.create_registration(self.event, {**self.attendee_data, 'email': 'b@test.com'})
        r3 = services.create_registration(self.event, {**self.attendee_data, 'email': 'c@test.com'})

        # Cancel the waitlisted r2 — r3 should remain waitlisted (no confirmed spot freed)
        services.cancel_registration(r2)
        r3.refresh_from_db()
        self.assertEqual(r3.status, Registration.Status.WAITLISTED)
