"""
Tests for Registrations API ViewSet.
"""
import json
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.events.models import Event
from apps.authentication.models import User
from apps.registrations.models import Registration


def jwt_client_for(user, tenant):
    token = str(RefreshToken.for_user(user).access_token)
    client = TenantClient(tenant)
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


class RegistrationViewSetMixin:
    """Shared setUp for registration view tests."""

    def setUp(self):
        self.organizer = User.objects.create_user(
            email='org@test.com', password='pass',
            first_name='Org', last_name='User',
            role='organizer', is_email_verified=True,
        )
        self.other_organizer = User.objects.create_user(
            email='other@test.com', password='pass',
            first_name='Other', last_name='Org',
            role='organizer', is_email_verified=True,
        )
        self.admin = User.objects.create_user(
            email='admin@test.com', password='pass',
            first_name='Admin', last_name='User',
            role='tenant_admin', is_email_verified=True,
        )
        self.org_client = jwt_client_for(self.organizer, self.tenant)
        self.other_client = jwt_client_for(self.other_organizer, self.tenant)
        self.admin_client = jwt_client_for(self.admin, self.tenant)
        self.anon_client = TenantClient(self.tenant)

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
        self.payload = {
            'event_id': str(self.event.id),
            'first_name': 'Ana',
            'last_name': 'López',
            'email': 'ana@test.com',
        }

    def _create_registration(self, email='reg@test.com'):
        return Registration.objects.create(
            event=self.event,
            first_name='Test',
            last_name='User',
            email=email,
            status=Registration.Status.CONFIRMED,
            qr_token=f'token-{email}',
        )


class TestPublicRegistration(RegistrationViewSetMixin, TenantTestCase):
    """Anonymous attendees can register for published events."""

    def test_anonymous_can_register(self):
        res = self.anon_client.post(
            '/api/registrations/',
            data=json.dumps(self.payload),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['status'], 'confirmed')
        self.assertIn('qr_token', res.data)

    def test_register_missing_event_id(self):
        payload = {k: v for k, v in self.payload.items() if k != 'event_id'}
        res = self.anon_client.post(
            '/api/registrations/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_nonexistent_event(self):
        payload = {**self.payload, 'event_id': '00000000-0000-0000-0000-000000000000'}
        res = self.anon_client.post(
            '/api/registrations/',
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_register_draft_event_rejected(self):
        self.event.status = Event.Status.DRAFT
        self.event.save()
        res = self.anon_client.post(
            '/api/registrations/',
            data=json.dumps(self.payload),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_duplicate_email_rejected(self):
        self.anon_client.post(
            '/api/registrations/',
            data=json.dumps(self.payload),
            content_type='application/json',
        )
        res = self.anon_client.post(
            '/api/registrations/',
            data=json.dumps(self.payload),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_waitlisted_when_full(self):
        self.event.max_capacity = 1
        self.event.save()
        self.anon_client.post(
            '/api/registrations/',
            data=json.dumps(self.payload),
            content_type='application/json',
        )
        payload2 = {**self.payload, 'email': 'b@test.com'}
        res = self.anon_client.post(
            '/api/registrations/',
            data=json.dumps(payload2),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['status'], 'waitlisted')


class TestOrganizerRegistrationList(RegistrationViewSetMixin, TenantTestCase):
    """Organizers can list and manage registrations for their events."""

    def test_organizer_can_list_own_event_registrations(self):
        self._create_registration()
        res = self.org_client.get(f'/api/registrations/?event={self.event.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)

    def test_anon_cannot_list_registrations(self):
        res = self.anon_client.get('/api/registrations/')
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

    def test_organizer_cannot_see_other_event_registrations(self):
        other_event = Event.objects.create(
            title='Other Event',
            slug='other-event',
            organizer=self.other_organizer,
            status=Event.Status.PUBLISHED,
            is_virtual=True,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=10, hours=4),
        )
        Registration.objects.create(
            event=other_event,
            first_name='X', last_name='Y', email='x@test.com',
            status=Registration.Status.CONFIRMED, qr_token='tok-x',
        )
        res = self.org_client.get(f'/api/registrations/?event={other_event.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 0)

    def test_admin_can_see_all_registrations(self):
        self._create_registration()
        res = self.admin_client.get(f'/api/registrations/?event={self.event.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)

    def test_filter_by_status(self):
        self._create_registration('confirmed@test.com')
        Registration.objects.create(
            event=self.event,
            first_name='W', last_name='L', email='wait@test.com',
            status=Registration.Status.WAITLISTED, qr_token='tok-w',
        )
        res = self.org_client.get(
            f'/api/registrations/?event={self.event.id}&status=waitlisted'
        )
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['status'], 'waitlisted')

    def test_csv_export(self):
        self._create_registration()
        res = self.org_client.get(
            f'/api/registrations/?event={self.event.id}&export=csv'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'text/csv; charset=utf-8')


class TestCancelRegistration(RegistrationViewSetMixin, TenantTestCase):
    """Organizers can cancel registrations."""

    def test_organizer_can_cancel(self):
        reg = self._create_registration()
        res = self.org_client.post(f'/api/registrations/{reg.id}/cancel/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'cancelled')

    def test_cancel_already_cancelled_returns_400(self):
        reg = self._create_registration()
        reg.status = Registration.Status.CANCELLED
        reg.save()
        res = self.org_client.post(f'/api/registrations/{reg.id}/cancel/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_anon_cannot_cancel(self):
        reg = self._create_registration()
        res = self.anon_client.post(f'/api/registrations/{reg.id}/cancel/')
        self.assertIn(res.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])
