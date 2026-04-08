from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Creates the public tenant and its domain if they do not exist'

    def add_arguments(self, parser):
        parser.add_argument(
            '--domain',
            default='api.eventsync.cloud',
            help='Domain to associate with the public tenant',
        )

    def handle(self, *args, **options):
        from apps.tenants.models import Tenant, Domain

        connection.set_schema('public')
        domain = options['domain']

        tenant, created = Tenant.objects.get_or_create(
            schema_name='public',
            defaults={'name': 'Public'},
        )

        if created:
            self.stdout.write(f'Created public tenant')
        else:
            self.stdout.write(f'Public tenant already exists')

        domain_obj, d_created = Domain.objects.get_or_create(
            domain=domain,
            defaults={'tenant': tenant, 'is_primary': True},
        )

        if d_created:
            self.stdout.write(self.style.SUCCESS(f'Created domain: {domain}'))
        else:
            self.stdout.write(f'Domain already exists: {domain}')
