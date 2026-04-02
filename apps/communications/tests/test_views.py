"""
Tests for Communications API views.
"""
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.events.models import Event
from apps.registrations.models import Registration
from apps.communications.models import EmailLog


def jwt_client_for(user, tenant):
    token = str(RefreshToken.for_user(user).access_token)
    client = TenantClient(tenant)
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


class CommunicationsViewSetUp(TenantTestCase):

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
        self.org_client   = jwt_client_for(self.organizer, self.tenant)
        self.staff_client = jwt_client_for(self.staff, self.tenant)
        self.anon_client  = TenantClient(self.tenant)

        now = timezone.now()
        self.event = Event.objects.create(
            title='Test Conf',
            slug='test-conf',
            organizer=self.organizer,
            status=Event.Status.PUBLISHED,
            is_virtual=True,
            start_date=now + timedelta(days=2),
            end_date=now + timedelta(days=2, hours=4),
        )
        self.registration = Registration.objects.create(
            event=self.event,
            first_name='Ana', last_name='López',
            email='ana@test.com',
            status=Registration.Status.CONFIRMED,
            qr_token='test-token-123',
        )


class EmailLogsViewTest(CommunicationsViewSetUp):

    def _url(self):
        return f'/api/communications/events/{self.event.id}/logs/'

    def test_organizer_can_list_logs(self):
        """Organizer can retrieve email logs for their event."""
        EmailLog.objects.create(
            event=self.event,
            registration=self.registration,
            email_type=EmailLog.EmailType.CONFIRMATION,
            recipient_email='ana@test.com',
            recipient_name='Ana López',
            subject='Confirmado: Test Conf',
            status=EmailLog.Status.SENT,
            sent_at=timezone.now(),
        )
        response = self.org_client.get(self._url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data.get('results', data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['email_type'], 'confirmation')

    def test_unauthenticated_returns_401(self):
        response = self.anon_client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_checkin_staff_cannot_access_logs(self):
        """checkin_staff role is below organizer — should be forbidden."""
        response = self.staff_client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_empty_log_returns_empty_list(self):
        """No logs yet returns an empty list, not 404."""
        response = self.org_client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        results = data.get('results', data)
        self.assertEqual(len(results), 0)


class ManualSendViewTest(CommunicationsViewSetUp):

    def _url(self):
        return f'/api/communications/events/{self.event.id}/send/'

    @patch('apps.communications.views.send_manual_email_task')
    def test_organizer_can_trigger_manual_send(self, mock_task):
        """Organizer can POST a manual send request — returns 202."""
        payload = {
            'subject': 'Información importante',
            'message': 'Por favor revisar el link del evento.',
            'segment': 'confirmed',
        }
        response = self.org_client.post(
            self._url(), payload, content_type='application/json',
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        call_kwargs = mock_task.delay.call_args[1]
        self.assertEqual(call_kwargs['event_id'], str(self.event.id))
        self.assertEqual(call_kwargs['subject'], 'Información importante')
        self.assertEqual(call_kwargs['message'], 'Por favor revisar el link del evento.')
        self.assertEqual(call_kwargs['segment'], 'confirmed')

    @patch('apps.communications.views.send_manual_email_task')
    def test_default_segment_is_all(self, mock_task):
        """Omitting segment defaults to 'all'."""
        payload = {'subject': 'Hola', 'message': 'Mensaje de prueba.'}
        self.org_client.post(self._url(), payload, content_type='application/json')

        _, kwargs = mock_task.delay.call_args
        self.assertEqual(kwargs['segment'], 'all')

    def test_invalid_segment_returns_400(self):
        payload = {'subject': 'x', 'message': 'y', 'segment': 'unknown'}
        response = self.org_client.post(
            self._url(), payload, content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_subject_returns_400(self):
        response = self.org_client.post(
            self._url(), {'message': 'x'}, content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated_returns_401(self):
        payload = {'subject': 'x', 'message': 'y'}
        response = self.anon_client.post(
            self._url(), payload, content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_checkin_staff_cannot_send(self):
        """checkin_staff cannot trigger a manual send — 403."""
        payload = {'subject': 'x', 'message': 'y'}
        response = self.staff_client.post(
            self._url(), payload, content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
