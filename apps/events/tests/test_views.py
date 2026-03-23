"""
Tests for Events API ViewSet.

Covers: CRUD endpoints, permissions, state transition endpoint,
        and tenant isolation.
"""
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.events.models import Event
from apps.authentication.models import User


def jwt_client_for(user, tenant):
    """
    Return a TenantClient authenticated via JWT for the given user.
    TenantClient sets the correct Host header so TenantMainMiddleware
    routes requests to the right schema.
    """
    token = str(RefreshToken.for_user(user).access_token)
    client = TenantClient(tenant)
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


class EventViewSetMixin:
    """Shared setUp and helpers for Event view tests."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@test.com', password='pass',
            first_name='Admin', last_name='User',
            role='tenant_admin', is_email_verified=True,
        )
        self.organizer = User.objects.create_user(
            email='org@test.com', password='pass',
            first_name='Org', last_name='User',
            role='organizer', is_email_verified=True,
        )
        self.checkin = User.objects.create_user(
            email='checkin@test.com', password='pass',
            first_name='Check', last_name='In',
            role='checkin_staff', is_email_verified=True,
        )
        self.admin_client = jwt_client_for(self.admin, self.tenant)
        self.org_client = jwt_client_for(self.organizer, self.tenant)
        self.checkin_client = jwt_client_for(self.checkin, self.tenant)

    def _future_event(self, user=None, ev_status=Event.Status.DRAFT, title=None):
        now = timezone.now()
        count = Event.objects.count()
        return Event.objects.create(
            title=title or f'Event {count}',
            slug=f'event-{count}',
            start_date=now + timedelta(days=30),
            end_date=now + timedelta(days=30, hours=4),
            is_virtual=True,
            status=ev_status,
            organizer=user or self.admin,
        )

    def _event_payload(self, **overrides):
        now = timezone.now()
        return {
            'title': 'New Event',
            'is_virtual': True,
            'start_date': (now + timedelta(days=30)).isoformat(),
            'end_date': (now + timedelta(days=30, hours=4)).isoformat(),
            **overrides,
        }


class TestEventCRUD(EventViewSetMixin, TenantTestCase):
    """Test basic CRUD operations."""

    def test_list_events_authenticated(self):
        self._future_event()
        response = self.admin_client.get('/api/events/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data['count'], 1)

    def test_list_events_unauthenticated_returns_only_published(self):
        # List is now public — returns only published events for anonymous users
        self._future_event(ev_status=Event.Status.DRAFT)
        published = self._future_event(ev_status=Event.Status.PUBLISHED)
        response = TenantClient(self.tenant).get('/api/events/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [e['id'] for e in response.data['results']]
        self.assertIn(str(published.id), ids)
        self.assertEqual(len(ids), 1)  # draft not exposed

    def test_create_event_as_admin(self):
        response = self.admin_client.post('/api/events/', self._event_payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'draft')
        self.assertEqual(response.data['title'], 'New Event')

    def test_create_event_as_organizer(self):
        response = self.org_client.post('/api/events/', self._event_payload(title='Org Event'), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_checkin_staff_cannot_create_event(self):
        response = self.checkin_client.post('/api/events/', self._event_payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_retrieve_event(self):
        event = self._future_event()
        response = self.admin_client.get(f'/api/events/{event.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(event.id))
        self.assertIn('valid_transitions', response.data)

    def test_partial_update_event(self):
        import json
        event = self._future_event()
        response = self.admin_client.patch(
            f'/api/events/{event.id}/',
            data=json.dumps({'title': 'Updated Title'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['title'], 'Updated Title')

    def test_delete_draft_event(self):
        event = self._future_event(ev_status=Event.Status.DRAFT)
        response = self.admin_client.delete(f'/api/events/{event.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Event.objects.filter(id=event.id).exists())

    def test_cannot_delete_published_event(self):
        event = self._future_event(ev_status=Event.Status.PUBLISHED)
        response = self.admin_client.delete(f'/api/events/{event.id}/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filter_events_by_status(self):
        self._future_event(ev_status=Event.Status.DRAFT)
        self._future_event(ev_status=Event.Status.PUBLISHED)
        response = self.admin_client.get('/api/events/?status=draft')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for e in response.data['results']:
            self.assertEqual(e['status'], 'draft')


class TestEventPermissions(EventViewSetMixin, TenantTestCase):
    """Test that organizers only see their own events, admins see all."""

    def test_organizer_sees_only_own_events(self):
        self._future_event(user=self.admin, title='Admin Event')
        self._future_event(user=self.organizer, title='Org Event')
        response = self.org_client.get('/api/events/')
        titles = [e['title'] for e in response.data['results']]
        self.assertIn('Org Event', titles)
        self.assertNotIn('Admin Event', titles)

    def test_admin_sees_all_events(self):
        self._future_event(user=self.admin, title='Admin Event')
        self._future_event(user=self.organizer, title='Org Event')
        response = self.admin_client.get('/api/events/')
        titles = [e['title'] for e in response.data['results']]
        self.assertIn('Admin Event', titles)
        self.assertIn('Org Event', titles)

    def test_organizer_cannot_edit_other_organizers_event(self):
        import json
        other = User.objects.create_user(
            email='other@test.com', password='pass',
            first_name='Other', last_name='Org', role='organizer'
        )
        event = self._future_event(user=other)
        # Organizer's queryset filters to own events, so `other`'s event returns 404
        # (security best practice: don't reveal resource existence)
        response = self.org_client.patch(
            f'/api/events/{event.id}/',
            data=json.dumps({'title': 'Hacked'}),
            content_type='application/json',
        )
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])


class TestEventStatusTransition(EventViewSetMixin, TenantTestCase):
    """Test the /transition/ endpoint."""

    def test_transition_draft_to_published(self):
        event = self._future_event(ev_status=Event.Status.DRAFT)
        response = self.admin_client.post(
            f'/api/events/{event.id}/transition/',
            {'status': 'published'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'published')
        self.assertIsNotNone(response.data['published_at'])

    def test_invalid_transition_returns_400(self):
        event = self._future_event(ev_status=Event.Status.DRAFT)
        response = self.admin_client.post(
            f'/api/events/{event.id}/transition/',
            {'status': 'finalized'},  # invalid from draft
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_transition_to_cancelled(self):
        event = self._future_event(ev_status=Event.Status.PUBLISHED)
        response = self.admin_client.post(
            f'/api/events/{event.id}/transition/',
            {'status': 'cancelled'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'cancelled')

    def test_checkin_staff_cannot_transition(self):
        event = self._future_event(ev_status=Event.Status.DRAFT)
        response = self.checkin_client.post(
            f'/api/events/{event.id}/transition/',
            {'status': 'published'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestCreateEventValidation(EventViewSetMixin, TenantTestCase):
    """Test create/update validation errors."""

    def test_create_without_title_fails(self):
        now = timezone.now()
        response = self.admin_client.post('/api/events/', {
            'is_virtual': True,
            'start_date': (now + timedelta(days=1)).isoformat(),
            'end_date': (now + timedelta(days=1, hours=2)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_presential_without_location_fails(self):
        now = timezone.now()
        response = self.admin_client.post('/api/events/', {
            'title': 'No Location',
            'is_virtual': False,
            'start_date': (now + timedelta(days=1)).isoformat(),
            'end_date': (now + timedelta(days=1, hours=2)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('location', str(response.data).lower())

    def test_end_before_start_fails(self):
        now = timezone.now()
        response = self.admin_client.post('/api/events/', {
            'title': 'Bad Dates',
            'is_virtual': True,
            'start_date': (now + timedelta(days=5)).isoformat(),
            'end_date': (now + timedelta(days=3)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
