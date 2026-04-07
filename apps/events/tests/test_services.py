"""
Tests for Events service layer.

Covers: create_event, update_event, transition_event_status,
        generate_unique_slug, and publish validation rules.
"""
import pytest
from datetime import timedelta
from django.utils import timezone
from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase

from apps.events.models import Event
from apps.events.services import (
    create_event,
    update_event,
    transition_event_status,
    generate_unique_slug,
)
from apps.authentication.models import User


class TestGenerateUniqueSlug(TenantTestCase):
    """Test slug generation and uniqueness collision handling."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='slug@test.com', password='pass',
            first_name='T', last_name='U', role='organizer'
        )
        now = timezone.now()
        Event.objects.create(
            title='Existing Event',
            slug='existing-event',
            start_date=now + timedelta(days=10),
            end_date=now + timedelta(days=10, hours=2),
            modality='virtual',
            organizer=self.user,
        )

    def test_generates_slug_from_title(self):
        slug = generate_unique_slug('Conferencia Tech')
        assert slug == 'conferencia-tech'

    def test_adds_suffix_on_collision(self):
        slug = generate_unique_slug('Existing Event')
        assert slug.startswith('existing-event-')
        assert len(slug) > len('existing-event')

    def test_exclude_id_allows_same_slug_for_same_event(self):
        event = Event.objects.get(slug='existing-event')
        slug = generate_unique_slug('Existing Event', exclude_id=event.id)
        assert slug == 'existing-event'

    def test_two_separate_titles_produce_same_base_slug(self):
        """New titles with no collision return their clean slug."""
        slug1 = generate_unique_slug('Fresh New Event')
        slug2 = generate_unique_slug('Another New Event')
        assert slug1 == 'fresh-new-event'
        assert slug2 == 'another-new-event'

    def test_suffix_on_second_collision_is_different_each_time(self):
        """Calling twice for a colliding title gives different UUID suffixes."""
        slug1 = generate_unique_slug('Existing Event')
        # Create event with slug1 to force another collision
        now = timezone.now()
        Event.objects.create(
            title='Existing Event 2',
            slug=slug1,
            start_date=now + timedelta(days=10),
            end_date=now + timedelta(days=10, hours=2),
            modality='virtual',
            organizer=self.user,
        )
        slug2 = generate_unique_slug('Existing Event')
        # Both are different from the original and from each other
        assert slug1 != 'existing-event'
        assert slug2 != 'existing-event'
        assert slug1 != slug2


class TestCreateEvent(TenantTestCase):
    """Test event creation via service."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@test.com', password='pass',
            first_name='A', last_name='B', role='tenant_admin'
        )
        self.organizer = User.objects.create_user(
            email='org@test.com', password='pass',
            first_name='O', last_name='R', role='organizer'
        )
        self.checkin = User.objects.create_user(
            email='checkin@test.com', password='pass',
            first_name='C', last_name='I', role='checkin_staff'
        )

    def _future_event_data(self, **overrides):
        now = timezone.now()
        return {
            'title': 'Mi Evento',
            'modality': 'virtual',
            'start_date': now + timedelta(days=30),
            'end_date': now + timedelta(days=30, hours=4),
            **overrides,
        }

    def test_create_event_as_admin(self):
        event = create_event(self.admin, self._future_event_data())
        assert event.status == Event.Status.DRAFT
        assert event.organizer == self.admin
        assert event.slug  # auto-generated

    def test_create_event_as_organizer(self):
        event = create_event(self.organizer, self._future_event_data())
        assert event.pk is not None

    def test_checkin_staff_cannot_create_event(self):
        with self.assertRaises(ValidationError) as ctx:
            create_event(self.checkin, self._future_event_data())
        self.assertIn('permisos', str(ctx.exception))

    def test_custom_slug_is_respected(self):
        event = create_event(self.admin, self._future_event_data(slug='custom-slug'))
        assert event.slug == 'custom-slug'

    def test_created_event_is_draft(self):
        event = create_event(self.admin, self._future_event_data())
        assert event.status == Event.Status.DRAFT


class TestUpdateEvent(TenantTestCase):
    """Test event update restrictions."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='upd@test.com', password='pass',
            first_name='U', last_name='P', role='tenant_admin'
        )
        now = timezone.now()
        self.base_data = {
            'start_date': now + timedelta(days=10),
            'end_date': now + timedelta(days=10, hours=4),
            'modality': 'virtual',
            'organizer': self.user,
        }

    def _make_event(self, status=Event.Status.DRAFT):
        count = Event.objects.count()
        return Event.objects.create(
            title='Original', slug=f'original-{count}', status=status, **self.base_data
        )

    def test_can_update_draft(self):
        event = self._make_event(Event.Status.DRAFT)
        updated = update_event(event, self.user, {'title': 'Updated'})
        assert updated.title == 'Updated'

    def test_can_update_published(self):
        event = self._make_event(Event.Status.PUBLISHED)
        updated = update_event(event, self.user, {'title': 'Updated Published'})
        assert updated.title == 'Updated Published'

    def test_cannot_update_cancelled(self):
        event = self._make_event(Event.Status.CANCELLED)
        with self.assertRaises(ValidationError) as ctx:
            update_event(event, self.user, {'title': 'Should Fail'})
        self.assertIn('Cancelado', str(ctx.exception))

    def test_cannot_update_finalized(self):
        event = self._make_event(Event.Status.FINALIZED)
        with self.assertRaises(ValidationError) as ctx:
            update_event(event, self.user, {'title': 'Should Fail'})
        self.assertIn('Finalizado', str(ctx.exception))

    def test_update_title_regenerates_slug(self):
        event = self._make_event()
        original_slug = event.slug
        updated = update_event(event, self.user, {'title': 'Brand New Title'})
        assert updated.slug != original_slug
        assert 'brand-new-title' in updated.slug


class TestTransitionEventStatus(TenantTestCase):
    """Test status transition service."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='trans@test.com', password='pass',
            first_name='T', last_name='R', role='tenant_admin'
        )

    def _future_event(self, status=Event.Status.DRAFT, **kwargs):
        now = timezone.now()
        count = Event.objects.count()
        return Event.objects.create(
            title='Transition Event',
            slug=f'transition-event-{count}',
            start_date=now + timedelta(days=30),
            end_date=now + timedelta(days=30, hours=4),
            modality='virtual',
            status=status,
            organizer=self.user,
            **kwargs,
        )

    def test_draft_to_published(self):
        event = self._future_event()
        result = transition_event_status(event, self.user, Event.Status.PUBLISHED)
        assert result.status == Event.Status.PUBLISHED
        assert result.published_at is not None

    def test_published_to_closed(self):
        event = self._future_event(status=Event.Status.PUBLISHED)
        result = transition_event_status(event, self.user, Event.Status.CLOSED)
        assert result.status == Event.Status.CLOSED

    def test_published_to_cancelled(self):
        event = self._future_event(status=Event.Status.PUBLISHED)
        result = transition_event_status(event, self.user, Event.Status.CANCELLED)
        assert result.status == Event.Status.CANCELLED

    def test_invalid_transition_raises_error(self):
        event = self._future_event(status=Event.Status.DRAFT)
        with self.assertRaises(ValidationError):
            transition_event_status(event, self.user, Event.Status.FINALIZED)

    def test_cannot_publish_past_event(self):
        now = timezone.now()
        count = Event.objects.count()
        event = Event.objects.create(
            title='Past Event',
            slug=f'past-event-{count}',
            start_date=now - timedelta(days=2),
            end_date=now - timedelta(days=1),
            modality='virtual',
            status=Event.Status.DRAFT,
            organizer=self.user,
        )
        with self.assertRaises(ValidationError) as ctx:
            transition_event_status(event, self.user, Event.Status.PUBLISHED)
        self.assertIn('finaliz', str(ctx.exception))

    def test_cannot_publish_presential_without_location(self):
        now = timezone.now()
        count = Event.objects.count()
        event = Event.objects.create(
            title='No Location',
            slug=f'no-location-{count}',
            start_date=now + timedelta(days=5),
            end_date=now + timedelta(days=5, hours=2),
            modality='in_person',
            location='',
            status=Event.Status.DRAFT,
            organizer=self.user,
        )
        with self.assertRaises(ValidationError) as ctx:
            transition_event_status(event, self.user, Event.Status.PUBLISHED)
        self.assertIn('ubicaci', str(ctx.exception))

    def test_cannot_publish_when_start_after_end(self):
        now = timezone.now()
        count = Event.objects.count()
        event = Event.objects.create(
            title='Bad Dates',
            slug=f'bad-dates-{count}',
            start_date=now + timedelta(days=5),
            end_date=now + timedelta(days=4),  # end before start
            modality='virtual',
            status=Event.Status.DRAFT,
            organizer=self.user,
        )
        with self.assertRaises(ValidationError) as ctx:
            transition_event_status(event, self.user, Event.Status.PUBLISHED)
        self.assertIn('inicio', str(ctx.exception))
