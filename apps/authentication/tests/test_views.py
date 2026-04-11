"""
Tests for TeamViewSet — FEAT-07 Gestión de Equipo por Organización.

Covers: list, change role, deactivate, permission enforcement,
        cross-tenant isolation, and login block for inactive users.
"""
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User


def jwt_client_for(user, tenant):
    """Return a TenantClient authenticated via JWT for the given user."""
    token = str(RefreshToken.for_user(user).access_token)
    client = TenantClient(tenant)
    client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


class TeamViewSetMixin:
    """Shared setUp for TeamViewSet tests."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@test.com', password='pass123!A',
            first_name='Admin', last_name='User',
            role='tenant_admin', is_email_verified=True,
            tenant=self.tenant,
        )
        self.organizer = User.objects.create_user(
            email='org@test.com', password='pass123!A',
            first_name='Org', last_name='User',
            role='organizer', is_email_verified=True,
            tenant=self.tenant,
        )
        self.checkin = User.objects.create_user(
            email='checkin@test.com', password='pass123!A',
            first_name='Check', last_name='In',
            role='checkin_staff', is_email_verified=True,
            tenant=self.tenant,
        )
        self.admin_client = jwt_client_for(self.admin, self.tenant)
        self.org_client = jwt_client_for(self.organizer, self.tenant)
        self.checkin_client = jwt_client_for(self.checkin, self.tenant)


class TestTeamList(TeamViewSetMixin, TenantTestCase):
    """GET /api/auth/team/ — list team members."""

    def test_list_team_as_admin(self):
        response = self.admin_client.get('/api/auth/team/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = [m['email'] for m in response.data['results']]
        # Organizer and checkin_staff visible; admin excluded (own account)
        self.assertIn('org@test.com', emails)
        self.assertIn('checkin@test.com', emails)
        self.assertNotIn('admin@test.com', emails)

    def test_list_team_as_organizer(self):
        response = self.org_client.get('/api/auth/team/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_team_as_checkin_staff(self):
        response = self.checkin_client.get('/api/auth/team/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_team_unauthenticated_returns_401(self):
        response = TenantClient(self.tenant).get('/api/auth/team/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_super_admin_not_in_list(self):
        User.objects.create_user(
            email='super@test.com', password='pass123!A',
            first_name='Super', last_name='Admin',
            role='super_admin', is_email_verified=True,
            tenant=self.tenant,
        )
        response = self.admin_client.get('/api/auth/team/')
        emails = [m['email'] for m in response.data['results']]
        self.assertNotIn('super@test.com', emails)


class TestTeamChangeRole(TeamViewSetMixin, TenantTestCase):
    """PATCH /api/auth/team/{id}/ — change role."""

    def test_change_role_as_admin(self):
        import json
        response = self.admin_client.patch(
            f'/api/auth/team/{self.organizer.id}/',
            data=json.dumps({'role': 'checkin_staff'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.organizer.refresh_from_db()
        self.assertEqual(self.organizer.role, 'checkin_staff')

    def test_organizer_cannot_patch(self):
        import json
        response = self.org_client.patch(
            f'/api/auth/team/{self.checkin.id}/',
            data=json.dumps({'role': 'organizer'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_checkin_staff_cannot_patch(self):
        import json
        response = self.checkin_client.patch(
            f'/api/auth/team/{self.organizer.id}/',
            data=json.dumps({'role': 'checkin_staff'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_set_role_to_super_admin(self):
        import json
        response = self.admin_client.patch(
            f'/api/auth/team/{self.organizer.id}/',
            data=json.dumps({'role': 'super_admin'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestTeamDeactivate(TeamViewSetMixin, TenantTestCase):
    """DELETE /api/auth/team/{id}/ — deactivate member."""

    def test_deactivate_member_as_admin(self):
        response = self.admin_client.delete(f'/api/auth/team/{self.organizer.id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.organizer.refresh_from_db()
        # is_active=False but record still exists
        self.assertFalse(self.organizer.is_active)
        self.assertIsNotNone(self.organizer.pk)

    def test_deactivated_user_cannot_login(self):
        self.organizer.is_active = False
        self.organizer.save(update_fields=['is_active'])
        response = TenantClient(self.tenant).post('/api/auth/login/', {
            'email': 'org@test.com',
            'password': 'pass123!A',
        }, format='json')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ])

    def test_checkin_staff_cannot_delete(self):
        response = self.checkin_client.delete(f'/api/auth/team/{self.organizer.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_deactivate_own_account(self):
        """Admin is excluded from queryset — deleting self returns 404."""
        response = self.admin_client.delete(f'/api/auth/team/{self.admin.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_see_other_tenant_members(self):
        """Users from a different tenant must not appear in this tenant's team list.

        TenantTestCase wraps each test in a transaction, making Tenant.objects.create()
        unfeasible (migrate_schemas needs a real commit). Instead we reuse the public
        tenant that TenantTestCase already creates in setUpClass().
        """
        from apps.tenants.models import Tenant

        # El tenant público ya existe — úsalo como "otro tenant"
        other_tenant = Tenant.objects.exclude(pk=self.tenant.pk).first()
        if other_tenant is None:
            self.skipTest('No hay un segundo tenant disponible en la DB de tests')

        User.objects.create_user(
            email='intruso@otraorg.com', password='pass123!A',
            first_name='Otro', last_name='Usuario',
            role='organizer', is_email_verified=True,
            tenant=other_tenant,
        )

        response = self.admin_client.get('/api/auth/team/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = [m['email'] for m in response.data['results']]
        self.assertNotIn('intruso@otraorg.com', emails)
