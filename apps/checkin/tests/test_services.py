"""
Tests for Check-in service layer.
"""
from datetime import timedelta
from django.utils import timezone
from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase

from apps.authentication.models import User
from apps.events.models import Event
from apps.registrations.models import Registration
from apps.checkin import services


class CheckinServiceTestCase(TenantTestCase):
    """Base setUp for check-in service tests."""

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
            start_date=now + timedelta(days=1),
            end_date=now + timedelta(days=1, hours=4),
        )
        self.registration = Registration.objects.create(
            event=self.event,
            first_name='Ana',
            last_name='López',
            email='ana@test.com',
            status=Registration.Status.CONFIRMED,
            qr_token='valid-qr-token-abc123',
        )

    # ── checkin_by_token ─────────────────────────────────────────────────────

    def test_checkin_success(self):
        result = services.checkin_by_token(self.registration.qr_token)
        self.assertFalse(result.already_checked_in)
        self.registration.refresh_from_db()
        self.assertTrue(self.registration.checked_in)
        self.assertIsNotNone(self.registration.checked_in_at)

    def test_checkin_sets_timestamp(self):
        before = timezone.now()
        services.checkin_by_token(self.registration.qr_token)
        after = timezone.now()
        self.registration.refresh_from_db()
        self.assertGreaterEqual(self.registration.checked_in_at, before)
        self.assertLessEqual(self.registration.checked_in_at, after)

    def test_checkin_already_checked_in_returns_warning(self):
        """Second scan is idempotent and returns already_checked_in=True."""
        services.checkin_by_token(self.registration.qr_token)
        result = services.checkin_by_token(self.registration.qr_token)
        self.assertTrue(result.already_checked_in)
        self.assertEqual(result.registration.id, self.registration.id)

    def test_checkin_already_checked_in_does_not_update_timestamp(self):
        """Second scan does not overwrite the original check-in timestamp."""
        services.checkin_by_token(self.registration.qr_token)
        self.registration.refresh_from_db()
        first_timestamp = self.registration.checked_in_at

        services.checkin_by_token(self.registration.qr_token)
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.checked_in_at, first_timestamp)

    def test_checkin_invalid_token_raises(self):
        with self.assertRaises(ValidationError):
            services.checkin_by_token('nonexistent-token')

    def test_checkin_waitlisted_raises(self):
        self.registration.status = Registration.Status.WAITLISTED
        self.registration.save()
        with self.assertRaises(ValidationError):
            services.checkin_by_token(self.registration.qr_token)

    def test_checkin_cancelled_raises(self):
        self.registration.status = Registration.Status.CANCELLED
        self.registration.save()
        with self.assertRaises(ValidationError):
            services.checkin_by_token(self.registration.qr_token)

    # ── get_event_stats ──────────────────────────────────────────────────────

    def test_stats_initial_state(self):
        stats = services.get_event_stats(self.event)
        self.assertEqual(stats['confirmed'], 1)
        self.assertEqual(stats['checked_in'], 0)
        self.assertEqual(stats['pending'], 1)
        self.assertEqual(stats['waitlisted'], 0)
        self.assertEqual(stats['cancelled'], 0)

    def test_stats_after_checkin(self):
        services.checkin_by_token(self.registration.qr_token)
        stats = services.get_event_stats(self.event)
        self.assertEqual(stats['confirmed'], 1)
        self.assertEqual(stats['checked_in'], 1)
        self.assertEqual(stats['pending'], 0)

    def test_stats_with_mixed_statuses(self):
        Registration.objects.create(
            event=self.event, first_name='B', last_name='B', email='b@test.com',
            status=Registration.Status.WAITLISTED, qr_token='tok-b',
        )
        Registration.objects.create(
            event=self.event, first_name='C', last_name='C', email='c@test.com',
            status=Registration.Status.CANCELLED, qr_token='tok-c',
        )
        services.checkin_by_token(self.registration.qr_token)
        stats = services.get_event_stats(self.event)
        self.assertEqual(stats['confirmed'], 1)
        self.assertEqual(stats['checked_in'], 1)
        self.assertEqual(stats['waitlisted'], 1)
        self.assertEqual(stats['cancelled'], 1)

    # ── search_registrations ─────────────────────────────────────────────────

    def test_search_by_first_name(self):
        results = services.search_registrations(self.event, 'Ana')
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first().email, 'ana@test.com')

    def test_search_by_last_name(self):
        results = services.search_registrations(self.event, 'López')
        self.assertEqual(results.count(), 1)

    def test_search_by_email(self):
        results = services.search_registrations(self.event, 'ana@test')
        self.assertEqual(results.count(), 1)

    def test_search_case_insensitive(self):
        results = services.search_registrations(self.event, 'ANA')
        self.assertEqual(results.count(), 1)

    def test_search_empty_query_returns_none(self):
        results = services.search_registrations(self.event, '')
        self.assertEqual(results.count(), 0)

    def test_search_excludes_waitlisted_and_cancelled(self):
        Registration.objects.create(
            event=self.event, first_name='Ana', last_name='Wait', email='wait@test.com',
            status=Registration.Status.WAITLISTED, qr_token='tok-wait',
        )
        results = services.search_registrations(self.event, 'Ana')
        self.assertEqual(results.count(), 1)  # Only the confirmed one

    def test_search_no_results(self):
        results = services.search_registrations(self.event, 'Inexistente')
        self.assertEqual(results.count(), 0)
