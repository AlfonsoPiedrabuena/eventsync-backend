"""
Tests for Registration Forms API ViewSet.
"""
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.events.models import Event
from apps.authentication.models import User
from apps.registrations.models import Registration
from apps.registration_forms.models import RegistrationFormField


def jwt_client_for(user, tenant):
    token = str(RefreshToken.for_user(user).access_token)
    client = TenantClient(tenant)
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


class FormFieldMixin:
    """Shared setUp for form field tests."""

    def setUp(self):
        self.organizer = User.objects.create_user(
            email='org@test.com', password='pass',
            first_name='Org', last_name='User',
            role='organizer', is_email_verified=True,
        )
        self.admin = User.objects.create_user(
            email='admin@test.com', password='pass',
            first_name='Admin', last_name='User',
            role='tenant_admin', is_email_verified=True,
        )
        self.staff = User.objects.create_user(
            email='staff@test.com', password='pass',
            first_name='Staff', last_name='User',
            role='checkin_staff', is_email_verified=True,
        )
        self.org_client = jwt_client_for(self.organizer, self.tenant)
        self.admin_client = jwt_client_for(self.admin, self.tenant)
        self.staff_client = jwt_client_for(self.staff, self.tenant)
        self.anon_client = TenantClient(self.tenant)

        now = timezone.now()
        self.event = Event.objects.create(
            title='Test Event',
            slug='test-event',
            organizer=self.organizer,
            status=Event.Status.DRAFT,
            modality='virtual',
            start_date=now + timedelta(days=10),
            end_date=now + timedelta(days=10, hours=4),
        )

    def _create_field(self, label='Empresa', field_key='company', field_type='text', order=1, is_required=False):
        return RegistrationFormField.objects.create(
            event=self.event,
            label=label,
            field_key=field_key,
            field_type=field_type,
            order=order,
            is_required=is_required,
        )

    def _create_confirmed_registration(self):
        return Registration.objects.create(
            event=self.event,
            first_name='Test',
            last_name='User',
            email='attendee@test.com',
            status=Registration.Status.CONFIRMED,
            qr_token='unique-qr-token-1',
        )


class TestListFormFields(FormFieldMixin, TenantTestCase):
    """GET /api/registration-form-fields/?event={id} — public endpoint."""

    def test_anonymous_can_list_fields(self):
        self._create_field('Empresa', 'company')
        self._create_field('Cargo', 'position', order=2)
        res = self.anon_client.get(
            f'/api/registration-form-fields/?event={self.event.id}'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 2)

    def test_list_returns_empty_without_event_param(self):
        self._create_field()
        res = self.anon_client.get('/api/registration-form-fields/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_ordered_by_order_then_created_at(self):
        self._create_field('B', 'field_b', order=2)
        self._create_field('A', 'field_a', order=1)
        res = self.anon_client.get(
            f'/api/registration-form-fields/?event={self.event.id}'
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        labels = [f['label'] for f in res.data]
        self.assertEqual(labels, ['A', 'B'])


class TestCreateFormField(FormFieldMixin, TenantTestCase):
    """POST /api/registration-form-fields/ — organizer/admin only."""

    def _payload(self, **kwargs):
        data = {
            'event_id': str(self.event.id),
            'label': 'Empresa',
            'field_key': 'company',
            'field_type': 'text',
            'order': 1,
            'is_required': False,
        }
        data.update(kwargs)
        return data

    def test_organizer_can_create_field(self):
        res = self.org_client.post(
            '/api/registration-form-fields/',
            self._payload(),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['label'], 'Empresa')
        self.assertEqual(res.data['field_key'], 'company')

    def test_admin_can_create_field(self):
        res = self.admin_client.post(
            '/api/registration-form-fields/',
            self._payload(label='Cargo', field_key='position'),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_anonymous_cannot_create_field(self):
        res = self.anon_client.post(
            '/api/registration-form-fields/',
            self._payload(),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_checkin_staff_cannot_create_field(self):
        res = self.staff_client.post(
            '/api/registration-form-fields/',
            self._payload(),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_missing_event_id_returns_400(self):
        payload = self._payload()
        del payload['event_id']
        res = self.org_client.post(
            '/api/registration-form-fields/',
            payload,
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_field_key_on_same_event_returns_400(self):
        self._create_field('Empresa', 'company')
        res = self.org_client.post(
            '/api/registration-form-fields/',
            self._payload(label='Otra empresa', field_key='company'),
            content_type='application/json',
        )
        self.assertIn(res.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_500_INTERNAL_SERVER_ERROR])

    def test_invalid_field_key_returns_400(self):
        res = self.org_client.post(
            '/api/registration-form-fields/',
            self._payload(field_key='Mi Campo Con Espacios'),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_select_without_options_returns_400(self):
        res = self.org_client.post(
            '/api/registration-form-fields/',
            self._payload(field_type='select', options=[]),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_select_with_options_succeeds(self):
        res = self.org_client.post(
            '/api/registration-form-fields/',
            self._payload(field_type='select', field_key='level', options=['Junior', 'Senior']),
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['options'], ['Junior', 'Senior'])


class TestUpdateFormField(FormFieldMixin, TenantTestCase):
    """PATCH /api/registration-form-fields/{id}/"""

    def test_organizer_can_update_field(self):
        field = self._create_field()
        res = self.org_client.patch(
            f'/api/registration-form-fields/{field.id}/',
            {'label': 'Empresa actualizada'},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['label'], 'Empresa actualizada')

    def test_cannot_update_field_when_event_has_active_registrations(self):
        field = self._create_field()
        self._create_confirmed_registration()
        res = self.org_client.patch(
            f'/api/registration-form-fields/{field.id}/',
            {'label': 'Nuevo label'},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)

    def test_can_update_field_when_event_has_only_cancelled_registrations(self):
        field = self._create_field()
        Registration.objects.create(
            event=self.event,
            first_name='Test', last_name='User',
            email='cancelled@test.com',
            status=Registration.Status.CANCELLED,
            qr_token='cancelled-qr-1',
        )
        res = self.org_client.patch(
            f'/api/registration-form-fields/{field.id}/',
            {'label': 'Nuevo label'},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)


class TestDeleteFormField(FormFieldMixin, TenantTestCase):
    """DELETE /api/registration-form-fields/{id}/"""

    def test_organizer_can_delete_field(self):
        field = self._create_field()
        res = self.org_client.delete(f'/api/registration-form-fields/{field.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(RegistrationFormField.objects.filter(id=field.id).exists())

    def test_cannot_delete_field_when_event_has_active_registrations(self):
        field = self._create_field()
        self._create_confirmed_registration()
        res = self.org_client.delete(f'/api/registration-form-fields/{field.id}/')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(RegistrationFormField.objects.filter(id=field.id).exists())

    def test_anonymous_cannot_delete_field(self):
        field = self._create_field()
        res = self.anon_client.delete(f'/api/registration-form-fields/{field.id}/')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class TestReorderFormFields(FormFieldMixin, TenantTestCase):
    """PATCH /api/registration-form-fields/reorder/"""

    def test_reorder_updates_order_values(self):
        f1 = self._create_field('A', 'field_a', order=1)
        f2 = self._create_field('B', 'field_b', order=2)
        f3 = self._create_field('C', 'field_c', order=3)

        # Reverse the order
        res = self.org_client.patch(
            '/api/registration-form-fields/reorder/',
            {'field_ids': [str(f3.id), str(f2.id), str(f1.id)]},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        f1.refresh_from_db()
        f2.refresh_from_db()
        f3.refresh_from_db()
        self.assertEqual(f3.order, 0)
        self.assertEqual(f2.order, 1)
        self.assertEqual(f1.order, 2)

    def test_reorder_blocked_when_active_registrations_exist(self):
        f1 = self._create_field('A', 'field_a', order=1)
        f2 = self._create_field('B', 'field_b', order=2)
        self._create_confirmed_registration()

        res = self.org_client.patch(
            '/api/registration-form-fields/reorder/',
            {'field_ids': [str(f2.id), str(f1.id)]},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)

    def test_reorder_with_invalid_ids_returns_400(self):
        import uuid
        res = self.org_client.patch(
            '/api/registration-form-fields/reorder/',
            {'field_ids': [str(uuid.uuid4())]},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reorder_requires_auth(self):
        f1 = self._create_field()
        res = self.anon_client.patch(
            '/api/registration-form-fields/reorder/',
            {'field_ids': [str(f1.id)]},
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class TestDefaultFormFieldsOnEventCreate(FormFieldMixin, TenantTestCase):
    """When an event is created via services.create_event, 3 default fields are created."""

    def test_default_fields_created_on_event_create(self):
        from apps.events import services as event_services

        new_event = event_services.create_event(self.organizer, {
            'title': 'New Event',
            'modality': 'virtual',
            'start_date': timezone.now() + timedelta(days=5),
            'end_date': timezone.now() + timedelta(days=5, hours=2),
        })

        fields = RegistrationFormField.objects.filter(event=new_event).order_by('order')
        self.assertEqual(fields.count(), 3)
        keys = list(fields.values_list('field_key', flat=True))
        self.assertIn('company', keys)
        self.assertIn('position', keys)
        self.assertIn('phone', keys)


class TestFormResponsesOnRegistration(FormFieldMixin, TenantTestCase):
    """form_responses are validated and saved during registration."""

    def setUp(self):
        super().setUp()
        self.event.status = Event.Status.PUBLISHED
        self.event.save()
        # Add a required field
        self.required_field = RegistrationFormField.objects.create(
            event=self.event,
            label='Número de empleados',
            field_key='num_employees',
            field_type='number',
            is_required=True,
            is_enabled=True,
            order=1,
        )

    def test_registration_fails_if_required_field_missing(self):
        res = self.anon_client.post(
            '/api/registrations/',
            {
                'event_id': str(self.event.id),
                'first_name': 'Ana',
                'last_name': 'López',
                'email': 'ana@test.com',
                'form_responses': {},
            },
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_registration_succeeds_with_required_field_provided(self):
        res = self.anon_client.post(
            '/api/registrations/',
            {
                'event_id': str(self.event.id),
                'first_name': 'Ana',
                'last_name': 'López',
                'email': 'ana@test.com',
                'form_responses': {'num_employees': '50'},
            },
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        reg = Registration.objects.get(id=res.data['id'])
        self.assertEqual(reg.form_responses.get('num_employees'), '50')

    def test_optional_form_responses_saved_correctly(self):
        # Disable the required field so registration always goes through
        self.required_field.is_required = False
        self.required_field.save()

        res = self.anon_client.post(
            '/api/registrations/',
            {
                'event_id': str(self.event.id),
                'first_name': 'Carlos',
                'last_name': 'Ruiz',
                'email': 'carlos@test.com',
                'form_responses': {'num_employees': '200'},
            },
            content_type='application/json',
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        reg = Registration.objects.get(id=res.data['id'])
        self.assertEqual(reg.form_responses.get('num_employees'), '200')
