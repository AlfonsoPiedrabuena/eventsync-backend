#!/bin/bash
set -e

python manage.py migrate_schemas --shared
python manage.py migrate_schemas --tenant
python manage.py create_public_tenant --domain localhost

exec "$@"
