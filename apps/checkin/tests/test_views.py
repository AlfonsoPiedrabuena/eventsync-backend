"""
Tests for Check-in API views.
"""
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.events.models import Event
from apps.registrations.models import Registration


def jwt_client_for(user, tenant):
    token = str(RefreshToken.for_user(user).access_token)
    client = TenantClient(tenant)
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


class CheckinViewMixin:
    """Shared setUp for check-in view tests."""

    def setUp(self):
        self.organizer = User.objects.create_user(
            email='org@test.com', password='pass',
            first_name='Org', last_name='User',
            role='organizer', is_email_verified=True,
        )
        self.staff = User.objects.create_user(
            email='staff@test.com', password='pass',
            first_name='Staff', last_name='User',
            role='checkin_staff', is_email_verified=True,
        )
        self.org_client = jwt_client_for(self.organizer, self.tenant)
        self.staff_client = jwt_client_for(self.staff, self.tenant)
        self.anon_client = TenantClient(self.tenant)

        now = timezone.now()
        self.event = Event.objects.create(
            title='Conf 2026',
            slug='conf-2026',
            organizer=self.organizer,
            status=Event.Status.PUBLISHED,
            modality='virtual',
            start_date=now + timedelta(days=1),
            end_date=now + timedelta(days=1, hours=4),
        )
        self.registration = Registration.objects.create(
            event=self.event,
            first_name='Ana',
            last_name='López',
            email='ana@test.com',
            status=Registration.Status.CONFIRMED,
            qr_token='test-qr-token-valid',
        )


# ── POST /api/checkin/ ────────────────────────────────────────────────────────

class TestCheckinByToken(CheckinViewMixin, TenantTestCase):

    def test_staff_can_checkin(self):
        res = self.staff_client.post(
            '/api/checkin/',
            {'qr_token': self.registration.qr_token},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data['already_checked_in'])
        self.assertEqual(res.data['registration']['email'], 'ana@test.com')

    def test_organizer_can_checkin(self):
        res = self.org_client.post(
            '/api/checkin/',
            {'qr_token': self.registration.qr_token},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_anonymous_cannot_checkin(self):
        res = self.anon_client.post(
            '/api/checkin/',
            {'qr_token': self.registration.qr_token},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_checkin_marks_registration_in_db(self):
        self.staff_client.post(
            '/api/checkin/',
            {'qr_token': self.registration.qr_token},
            content_type='application/json',
        )
        self.registration.refresh_from_db()
        self.assertTrue(self.registration.checked_in)

    def test_second_checkin_returns_warning(self):
        self.staff_client.post(
            '/api/checkin/',
            {'qr_token': self.registration.qr_token},
            content_type='application/json',
        )
        res = self.staff_client.post(
            '/api/checkin/',
            {'qr_token': self.registration.qr_token},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data['already_checked_in'])

    def test_invalid_token_returns_400(self):
        res = self.staff_client.post(
            '/api/checkin/',
            {'qr_token': 'fake-token-xyz'},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancelled_registration_returns_400(self):
        self.registration.status = Registration.Status.CANCELLED
        self.registration.save()
        res = self.staff_client.post(
            '/api/checkin/',
            {'qr_token': self.registration.qr_token},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_qr_token_returns_400(self):
        res = self.staff_client.post(
            '/api/checkin/', {}, content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ── POST /api/checkin/manual/ ─────────────────────────────────────────────────

class TestManualCheckin(CheckinViewMixin, TenantTestCase):

    def test_manual_checkin_by_id(self):
        res = self.staff_client.post(
            '/api/checkin/manual/',
            {'registration_id': str(self.registration.id)},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data['already_checked_in'])

    def test_manual_checkin_invalid_id_returns_404(self):
        import uuid
        res = self.staff_client.post(
            '/api/checkin/manual/',
            {'registration_id': str(uuid.uuid4())},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_manual_checkin_anonymous_returns_401(self):
        res = self.anon_client.post(
            '/api/checkin/manual/',
            {'registration_id': str(self.registration.id)},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# ── GET /api/checkin/stats/ ───────────────────────────────────────────────────

class TestEventStats(CheckinViewMixin, TenantTestCase):

    def test_stats_returns_counts(self):
        res = self.staff_client.get(f'/api/checkin/stats/?event={self.event.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['confirmed'], 1)
        self.assertEqual(res.data['checked_in'], 0)
        self.assertEqual(res.data['pending'], 1)

    def test_stats_updates_after_checkin(self):
        self.staff_client.post(
            '/api/checkin/',
            {'qr_token': self.registration.qr_token},
            content_type='application/json',
        )
        res = self.staff_client.get(f'/api/checkin/stats/?event={self.event.id}')
        self.assertEqual(res.data['checked_in'], 1)
        self.assertEqual(res.data['pending'], 0)

    def test_stats_missing_event_returns_400(self):
        res = self.staff_client.get('/api/checkin/stats/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_stats_anonymous_returns_401(self):
        res = self.anon_client.get(f'/api/checkin/stats/?event={self.event.id}')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# ── GET /api/checkin/search/ ──────────────────────────────────────────────────

class TestRegistrationSearch(CheckinViewMixin, TenantTestCase):

    def test_search_by_name(self):
        res = self.staff_client.get(f'/api/checkin/search/?event={self.event.id}&q=Ana')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)

    def test_search_by_email(self):
        res = self.staff_client.get(f'/api/checkin/search/?event={self.event.id}&q=ana@test')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)

    def test_search_no_results(self):
        res = self.staff_client.get(f'/api/checkin/search/?event={self.event.id}&q=Inexistente')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 0)

    def test_search_too_short_returns_400(self):
        res = self.staff_client.get(f'/api/checkin/search/?event={self.event.id}&q=A')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_search_missing_event_returns_400(self):
        res = self.staff_client.get('/api/checkin/search/?q=Ana')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_search_anonymous_returns_401(self):
        res = self.anon_client.get(f'/api/checkin/search/?event={self.event.id}&q=Ana')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
