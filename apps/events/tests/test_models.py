"""
Tests for Event model.

Covers: state machine, computed properties, and field constraints.
"""
from datetime import timedelta
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase

from apps.events.models import Event
from apps.authentication.models import User


class TestEventStateTransitions(TenantTestCase):
    """Verify the state machine allows and blocks the right transitions."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='organizer@test.com',
            password='pass',
            first_name='Test',
            last_name='User',
            role='organizer',
            is_email_verified=True,
        )

    def _make_event(self, status=Event.Status.DRAFT, days_ahead=30):
        now = timezone.now()
        count = Event.objects.count()
        return Event.objects.create(
            title='Test Event',
            slug=f'test-event-{count}',
            start_date=now + timedelta(days=days_ahead),
            end_date=now + timedelta(days=days_ahead, hours=4),
            modality='virtual',
            status=status,
            organizer=self.user,
        )

    def test_draft_can_transition_to_published(self):
        event = self._make_event(Event.Status.DRAFT)
        assert event.can_transition_to(Event.Status.PUBLISHED)

    def test_draft_can_transition_to_cancelled(self):
        event = self._make_event(Event.Status.DRAFT)
        assert event.can_transition_to(Event.Status.CANCELLED)

    def test_draft_cannot_transition_to_closed(self):
        event = self._make_event(Event.Status.DRAFT)
        assert not event.can_transition_to(Event.Status.CLOSED)

    def test_draft_cannot_transition_to_finalized(self):
        event = self._make_event(Event.Status.DRAFT)
        assert not event.can_transition_to(Event.Status.FINALIZED)

    def test_published_can_transition_to_closed(self):
        event = self._make_event(Event.Status.PUBLISHED)
        assert event.can_transition_to(Event.Status.CLOSED)

    def test_published_can_transition_to_cancelled(self):
        event = self._make_event(Event.Status.PUBLISHED)
        assert event.can_transition_to(Event.Status.CANCELLED)

    def test_published_cannot_go_back_to_draft(self):
        event = self._make_event(Event.Status.PUBLISHED)
        assert not event.can_transition_to(Event.Status.DRAFT)

    def test_closed_can_transition_to_finalized(self):
        event = self._make_event(Event.Status.CLOSED)
        assert event.can_transition_to(Event.Status.FINALIZED)

    def test_closed_cannot_reopen(self):
        event = self._make_event(Event.Status.CLOSED)
        assert not event.can_transition_to(Event.Status.PUBLISHED)

    def test_cancelled_is_terminal(self):
        event = self._make_event(Event.Status.CANCELLED)
        for status in Event.Status:
            assert not event.can_transition_to(status)

    def test_finalized_is_terminal(self):
        event = self._make_event(Event.Status.FINALIZED)
        for status in Event.Status:
            assert not event.can_transition_to(status)

    def test_all_statuses_have_transition_rules(self):
        """Ensure no status is missing from VALID_TRANSITIONS."""
        all_statuses = set(s.value for s in Event.Status)
        transition_keys = set(k.value for k in Event.VALID_TRANSITIONS.keys())
        assert all_statuses == transition_keys


class TestEventComputedProperties(TenantTestCase):
    """Test is_past, is_upcoming, is_open_for_registration, spots_remaining."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='org2@test.com', password='pass',
            first_name='T', last_name='U', role='organizer'
        )

    def test_is_upcoming_for_future_event(self):
        now = timezone.now()
        event = Event(
            start_date=now + timedelta(days=10),
            end_date=now + timedelta(days=10, hours=4),
        )
        assert event.is_upcoming
        assert not event.is_past

    def test_is_past_for_old_event(self):
        now = timezone.now()
        event = Event(
            start_date=now - timedelta(days=2),
            end_date=now - timedelta(days=1),
        )
        assert event.is_past
        assert not event.is_upcoming

    def test_spots_remaining_with_capacity_and_no_registrations(self):
        """spots_remaining equals max_capacity when there are no confirmed registrations."""
        now = timezone.now()
        event = Event.objects.create(
            title='Capped Event',
            slug='capped-event',
            start_date=now + timedelta(days=5),
            end_date=now + timedelta(days=5, hours=2),
            modality='virtual',
            max_capacity=100,
            organizer=self.user,
        )
        # registration_count uses related manager — 0 until E3 (registrations app) is built
        # We verify the formula: spots_remaining = max(0, max_capacity - registration_count)
        assert event.registration_count == 0  # no registrations
        assert event.spots_remaining == 100

    def test_spots_remaining_is_none_when_no_capacity(self):
        now = timezone.now()
        event = Event.objects.create(
            title='Unlimited Event',
            slug='unlimited-event',
            start_date=now + timedelta(days=5),
            end_date=now + timedelta(days=5, hours=2),
            modality='virtual',
            max_capacity=None,
            organizer=self.user,
        )
        assert event.spots_remaining is None

    def test_is_open_for_registration_when_published_and_future(self):
        now = timezone.now()
        event = Event.objects.create(
            title='Open Event',
            slug='open-event',
            start_date=now + timedelta(days=5),
            end_date=now + timedelta(days=5, hours=2),
            modality='virtual',
            status=Event.Status.PUBLISHED,
            organizer=self.user,
        )
        assert event.is_open_for_registration()

    def test_is_not_open_for_registration_when_draft(self):
        now = timezone.now()
        event = Event(
            start_date=now + timedelta(days=5),
            end_date=now + timedelta(days=5, hours=2),
            status=Event.Status.DRAFT,
        )
        assert not event.is_open_for_registration()

    def test_is_not_open_when_past(self):
        now = timezone.now()
        event = Event.objects.create(
            title='Past Event',
            slug='past-event',
            start_date=now - timedelta(days=2),
            end_date=now - timedelta(days=1),
            modality='virtual',
            status=Event.Status.PUBLISHED,
            organizer=self.user,
        )
        assert not event.is_open_for_registration()
