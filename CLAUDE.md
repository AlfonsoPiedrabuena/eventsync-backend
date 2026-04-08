# CLAUDE.md - EventSync Backend

Este archivo proporciona guías técnicas para Claude Code al trabajar en el backend de EventSync, una plataforma SaaS multi-tenant de gestión integral de eventos.

**Repo**: `eventsync-backend` (extraído del monorepo `eventsync/` en FEAT-04)
**API base URL (producción)**: `https://api.eventsync.app`
**Frontend companion repo**: `eventsync-frontend` → `https://app.eventsync.app`

---

## Stack Tecnológico

- **Framework**: Django 5.0+ (Python 3.11+)
- **API**: Django REST Framework (DRF)
- **Multi-tenancy**: django-tenants (PostgreSQL schema-based isolation)
- **Autenticación**: djangorestframework-simplejwt
- **Task Queue**: Celery + Redis (emails, sincronizaciones CRM)
- **Email**: django-anymail (Resend activo; soporte multi-provider: SendGrid, SES)
- **Base de Datos**: PostgreSQL 15+
- **Hosting**: Railway (con PostgreSQL managed + Redis managed)
- **File Storage**: AWS S3 o Railway Volumes (imágenes de eventos via URL de Firebase)
- **Monitoring**: Sentry (error tracking)

---

## Estructura del Proyecto

```
eventsync-backend/          # Raíz del repo (antes: backend/ en el monorepo)
├── config/                 # Configuración del proyecto Django
│   ├── __init__.py        # ⚠️ Importa celery_app — obligatorio para .delay()
│   ├── settings/
│   │   ├── base.py        # Settings compartidos
│   │   ├── development.py
│   │   ├── production.py
│   │   └── test.py
│   ├── celery.py          # App Celery + CELERY_BEAT_SCHEDULE
│   ├── urls.py            # URL routing principal
│   ├── wsgi.py
│   └── asgi.py
├── apps/                   # Django apps (módulos funcionales)
│   ├── tenants/           # Multi-tenancy: Tenant, Domain
│   ├── authentication/    # Auth + usuarios: User, Invitation, JWT
│   ├── events/            # Gestión de eventos: Event, estados, slug
│   ├── registrations/     # Registro de asistentes: Registration
│   ├── registration_forms/ # Campos dinámicos por evento: RegistrationFormField
│   ├── checkin/           # Check-in por QR: token, manual, stats
│   ├── communications/    # Emails y notificaciones: EmailLog, tasks Celery
│   ├── analytics/         # Dashboard stats: KPIs, timeline
│   └── billing/           # Billing y planes (E9) — stub
├── shared/                 # Código compartido cross-app
│   ├── authentication.py  # TenantAwareJWTAuthentication
│   ├── permissions/       # IsTenantAdmin, IsOrganizerOrAdmin, IsCheckInStaffOrAbove
│   ├── middleware/
│   ├── serializers/
│   └── utils/
├── templates/              # Email templates (Django templates)
│   └── emails/            # verification, password_reset, confirmation, cancellation, etc.
├── static/
├── media/                  # User uploads (solo desarrollo local)
├── requirements/
│   ├── base.txt           # Core: Django, DRF, Celery, postgres, jwt, anymail
│   ├── development.txt    # pytest, factory-boy, faker, black, isort, flake8
│   └── production.txt     # gunicorn, sentry
├── docs/                   # Guías técnicas (e.g. e4-checkin-validation-guide.md)
├── requerimientos/         # FEATs specs y contexto de producto
├── pytest.ini
├── manage.py
└── .env.example
```

---

## Decisiones Técnicas Clave

### Multi-tenancy con django-tenants

**Estrategia**: Schema-based isolation — cada tenant (organización) tiene su propio schema PostgreSQL.

```python
# config/settings/base.py
SHARED_APPS = (
    'django_tenants',
    'apps.tenants',
    'apps.authentication',  # ⚠️ User debe estar en SHARED_APPS (para Django Admin)
    'django.contrib.auth',
    # ...
)

TENANT_APPS = (
    'apps.authentication',  # También en TENANT_APPS para aislamiento de usuarios
    'apps.events',
    'apps.registrations',
    'apps.registration_forms',
    'apps.checkin',
    'apps.communications',
    'apps.analytics',
    # ...
)

TENANT_MODEL = "tenants.Tenant"
TENANT_DOMAIN_MODEL = "tenants.Domain"
```

**Comando correcto para migraciones**:
```bash
python manage.py migrate_schemas --shared  # schema público (SHARED_APPS)
python manage.py migrate_schemas           # todos los tenant schemas (TENANT_APPS)
```

### Multi-tenancy de Dominio Único (MVP)

Para el MVP, toda la API usa un único dominio central. El routing por subdominio queda para una fase posterior.

**Implementación**: `shared/authentication.py` — `TenantAwareJWTAuthentication`

```python
class TenantAwareJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        if user.tenant:
            connection.set_schema(user.tenant.schema_name)
        return user, token
```

- Captura `InvalidToken` y retorna `None` — permite que endpoints `AllowAny` funcionen con JWT vencido en el browser.
- Llama a `_sync_user_to_tenant_schema(user)` — lazy sync del usuario al schema del tenant (necesario para FKs como `events.organizer_id`).

**Regla crítica**: Toda view `AllowAny` que toque el modelo `User` DEBE llamar `connection.set_schema('public')` al inicio del método (LoginView, PasswordResetRequestView, EmailVerificationView, etc.).

### Autenticación JWT

- Access token: 15 minutos | Refresh token: 7 días con rotación
- Blacklist activado (logout invalida tokens)
- Token incluye `user_id` y `tenant_id` en payload

**Roles**:
```python
class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ('super_admin', 'Super Admin'),
        ('tenant_admin', 'Tenant Admin'),
        ('organizer', 'Organizador de Eventos'),
        ('checkin_staff', 'Staff de Check-in'),
    )
```

**Permissions custom**: `IsTenantAdmin`, `IsOrganizerOrAdmin`, `IsCheckInStaffOrAbove`

### Sistema de Comunicaciones (Celery)

```python
# apps/communications/tasks.py
@shared_task
def send_confirmation_email(registration_id): ...
@shared_task
def send_scheduled_reminder(event_id, reminder_type): ...
@shared_task
def sync_to_crm(registration_id): ...
```

**Celery Beat** para tareas programadas (recordatorios ±30 min, `finalize_past_events` diaria 1am).

**Email**: Resend vía `django-anymail[resend]`
- `EMAIL_BACKEND=anymail.backends.resend.EmailBackend` en `.env`
- Dominio verificado: `notifications.eventsync.cloud`
- `DEFAULT_FROM_EMAIL=EventSync <noreply@notifications.eventsync.cloud>`

### Endpoints Públicos (Cross-tenant)

Requests sin JWT llegan al schema `public` que no tiene tablas de negocio. Dos patrones:

**Solución A — Búsqueda cross-tenant** (GET público):
```python
# apps/events/views.py — PublicEventBySlugView
for schema_name in tenant_schemas:
    with schema_context(schema_name):
        event = Event.objects.filter(id=event_id, status='published').first()
        if event:
            return Response(EventDetailSerializer(event).data)
```

**Solución B — Switch permanente por request** (POST público):
```python
# apps/registrations/views.py
if db_conn.schema_name == 'public':
    for schema_name in tenant_schemas:
        with schema_context(schema_name):
            if Event.objects.filter(id=event_id).exists():
                db_conn.set_schema(schema_name)  # permanente para este request
                break
```

---

## Convenciones de Código

### Estructura de Apps Django

```
apps/events/
├── migrations/
├── models.py           # Modelos de dominio
├── serializers.py      # DRF serializers
├── views.py            # ViewSets
├── urls.py             # URL routing
├── permissions.py      # Custom permissions
├── services.py         # Lógica de negocio compleja
├── tasks.py            # Celery tasks
├── admin.py            # Django admin config
└── tests/
    ├── test_models.py
    ├── test_views.py
    └── test_services.py
```

### Naming Conventions

- Modelos: PascalCase singular (`Event`, `Registration`)
- Serializers: `{Model}Serializer`, `{Model}CreateSerializer`
- ViewSets: `{Model}ViewSet`
- URLs: kebab-case (`/api/events/`, `/api/events/{id}/registrations/`)
- Funciones/métodos: snake_case

### Docstrings

```python
def create_event(tenant, user, event_data):
    """
    Crea un nuevo evento en estado Borrador.

    Args:
        tenant (Tenant): Tenant propietario del evento
        user (User): Usuario creador (debe ser Organizer o Admin)
        event_data (dict): Datos del evento validados

    Returns:
        Event: Instancia del evento creado

    Raises:
        ValidationError: Si los datos no son válidos
        PermissionDenied: Si el usuario no tiene permisos
    """
```

### Tests

- Framework: `pytest` + `pytest-django`
- Fixtures: `factory_boy` (Factory pattern)
- Cobertura mínima: 80%
- **180 tests pasando** (models + services + views para E1-E6, FEAT-01, FEAT-02)

---

## Roadmap y Estado del Proyecto

**Última actualización**: 2026-04-07

### ✅ Completado

#### Sprints E1-E6 + FEATs

**E1 — Autenticación y Tenants**
- Modelos: `Tenant`, `Domain`, `User`, `Invitation`
- API REST completa:
  - `POST /api/auth/register/` — Registro de organización
  - `POST /api/auth/login/` — Login con JWT
  - `POST /api/auth/logout/` — Logout con blacklist
  - `GET /api/auth/verify-email/{token}/` — Verificación de email
  - `POST /api/auth/password-reset/` — Solicitud de reset
  - `POST /api/auth/password-reset/confirm/` — Confirmación de reset
  - `GET/POST /api/auth/invitations/` — Gestión de invitaciones
  - `POST /api/auth/invitations/accept/` — Aceptar invitación
  - `GET /api/auth/me/` — Datos del usuario autenticado
  - `POST /api/auth/token/refresh/` — Refresh JWT

**E2 — Gestión de Eventos**
- Modelo `Event`: máquina de estados (draft/published/closed/cancelled/finalized), slug único, hero_image_url
- `GET/POST /api/events/` — Listar (público: solo published + visibility=public) / Crear
- `GET/PATCH/DELETE /api/events/{id}/` — Detalle, editar, eliminar
- `POST /api/events/{id}/transition/` — Cambiar estado
- `GET /api/events/public/{slug}-{event_uuid}/` — Página pública (cross-tenant)

**E3 — Registro de Asistentes**
- Modelo `Registration`: estados (confirmed/waitlisted/cancelled), `qr_token`, `cancellation_token`, `form_responses` (JSON)
- `POST /api/registrations/` — Registrarse (público, cross-tenant)
- `GET /api/registrations/?event={id}` — Listar (organizador)
- `GET /api/registrations/?event={id}&export=csv` — Export CSV con BOM
- `POST /api/registrations/{id}/cancel/` — Cancelar (autenticado)
- `POST /api/registrations/cancel/` — Cancelar por token (público, cross-tenant)
- Capacidad máxima + lista de espera automática + promoción automática al cancelar
- Campo de teléfono con validación E.164 (regex en backend)

**E4 — Check-in por QR**
- `POST /api/checkin/` — Check-in por QR token (idempotente, advertencia `already_checked_in`)
- `POST /api/checkin/manual/` — Check-in por registration ID
- `GET /api/checkin/stats/?event={id}` — Estadísticas en tiempo real
- `GET /api/checkin/search/?event={id}&q={query}` — Búsqueda de asistentes
- Permiso `IsCheckInStaffOrAbove` (rol mínimo: `checkin_staff`)
- 38 tests pasando

**E5 — Comunicaciones**
- Modelo `EmailLog` (tipos: confirmation, reminder_24h, reminder_1h, post_event, manual, cancellation)
- Templates HTML + TXT: confirmación (con QR embebido base64), recordatorio, post-evento, manual, cancelación
- `GET /api/communications/events/{id}/logs/` — Historial de emails
- `POST /api/communications/events/{id}/send/` — Envío manual segmentado (all/confirmed/waitlisted/checked_in/no_show) — 202 async
- Recordatorios programados vía Celery Beat (ventana ±30 min)
- Email de cancelación automático + link de cancelación en email de confirmación
- 20 tests pasando

**E6 — Analytics**
- Dashboard global con KPIs: eventos, registros, check-ins, tasa de asistencia
- Breakdown por estado, próximos eventos, top eventos
- Analytics por evento: evolución de registros (diario + acumulado), barras de asistencia
- Pendiente: generación de reportes PDF, export de datos analíticos

**FEAT-01 — Visibilidad del Evento** (2026-04-07)
- Campos en `Event`: `visibility` (public/private), `audience_type` (internal/external), `target_company`
- Migración `events/0004`
- API filtra eventos privados en endpoints públicos

**FEAT-02 — Formulario de Registro Dinámico** (2026-04-07)
- App `registration_forms/` — `RegistrationFormField`: 7 tipos (text/textarea/email/phone/select/checkbox/number)
- CRUD + reorder en `/api/registration-form-fields/`
- Guard HTTP 409 si el evento tiene registros activos
- `create_event()` crea automáticamente 3 campos default (company, position, phone)
- `create_registration()` valida campos requeridos → 400 con `field_key` infractor
- 26 nuevos tests (180 total)

### 📋 Próximos Sprints

- **FEAT-03**: IA para descripción de evento (Claude API)
- **E9 (Sprint 19-20)**: Admin Multi-tenant, billing (Stripe)

---

## Lecciones Aprendidas y Notas Críticas

### `config/__init__.py` es obligatorio para Celery

Sin importar la app en `__init__`, Django no inicializa Celery al arrancar → `.delay()` usa AMQP en lugar de Redis.

```python
# config/__init__.py
from .celery import app as celery_app
__all__ = ('celery_app',)
```

### Reiniciar el worker SIEMPRE tras migraciones que eliminan columnas

El worker carga modelos en memoria. Si una migración elimina una columna, el worker falla con `ProgrammingError`. Solución:
```bash
pkill -f "celery -A config"
celery -A config worker -B -l info
```

### `.delay()` siempre fuera de `transaction.atomic()`

Si `.delay()` se llama dentro de un bloque atómico, el worker puede ejecutar la task antes del commit → datos no encontrados.

```python
with transaction.atomic():
    user = User.objects.create_user(...)
    user.save()
# ✅ Fuera del bloque
send_verification_email_task.delay(user.id, 'public')
```

### `development.py` no debe hardcodear `EMAIL_BACKEND`

Dejar que `base.py` resuelva el valor via `config('EMAIL_BACKEND', default='console')`. Así en dev se activa Resend solo cambiando el `.env`.

### FRONTEND_URL en `.env`

Si no se configura, el backend usa `http://localhost:3000` por defecto. Configurar explícitamente si el frontend corre en otro puerto:
```env
FRONTEND_URL=http://localhost:3001
```

### JWT Management

- Access token: 15 minutos | Refresh token: 7 días con rotación
- Blacklist activado
- Para desarrollo, aumentar temporalmente en `config/settings/development.py`:
```python
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
}
```

### Validación de Contraseñas

Django validators: mínimo 8 caracteres, no similar a atributos del usuario, no contraseña común, no completamente numérica. Aplicados en serializers con `validate_password()`.

### Email Verification Workflow

1. Registro → se genera `email_verification_token` (UUID)
2. Email con link → `GET /api/auth/verify-email/{token}/`
3. Backend marca `is_email_verified=True` y limpia el token

### Sistema de Invitaciones

- Token único UUID, expiración 48 horas
- Solo Tenant Admin puede crear invitaciones
- Al aceptar invitación → usuario se auto-verifica
- Estados: pending, accepted, expired, cancelled

### Patrón de migración con retrocompatibilidad (`is_virtual` → `modality`)

1. Agregar nuevo campo con default
2. `RunPython` para poblar desde el campo antiguo
3. Eliminar columna antigua
4. Mantener `@property` como derivado para retrocompatibilidad
5. En serializer: campo antiguo como `read_only=True`

### ⚠️ Cuidado con indentación en ViewSets

Al agregar vistas en el mismo archivo que un ViewSet, nunca indentar métodos del ViewSet dentro de la nueva clase — el router DRF no registrará las `@action`.

### Borrar un tenant completo vía shell

```python
with connection.cursor() as cursor:
    cursor.execute('DROP SCHEMA IF EXISTS schema_name CASCADE')
Domain.objects.filter(tenant=tenant).delete()
```

### CORS

`CORS_ALLOWED_ORIGINS` debe incluir el puerto exacto del frontend. `CORS_ALLOW_PRIVATE_NETWORK = True` configurado.

---

## Troubleshooting Común

### "relation 'users' does not exist" al migrar
`apps.authentication` debe estar en `SHARED_APPS`. Si no, recrear la DB:
```bash
dropdb eventsync && createdb eventsync
python manage.py migrate_schemas --shared
```

### "No tenant for hostname 'localhost'"
Crear tenant público:
```python
from apps.tenants.models import Tenant, Domain
public_tenant = Tenant.objects.create(schema_name='public', name='Public')
Domain.objects.create(domain='localhost', tenant=public_tenant, is_primary=True)
Domain.objects.create(domain='127.0.0.1', tenant=public_tenant)
```

### PostgreSQL no está corriendo
```bash
brew services start postgresql@14  # macOS Homebrew
```

### "role 'postgres' does not exist"
PostgreSQL con Homebrew usa tu usuario del sistema. Actualizar `.env`:
```env
DB_USER=tu_usuario_actual
DB_PASSWORD=
```

### Migraciones desincronizadas
```bash
dropdb eventsync && createdb eventsync
python manage.py migrate_schemas --shared
python manage.py migrate_schemas
```

---

## Variables de Entorno (.env)

```env
# Django
SECRET_KEY=
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
DB_NAME=eventsync
DB_USER=
DB_PASSWORD=
DB_HOST=localhost
DB_PORT=5432

# Redis
REDIS_URL=redis://localhost:6379/0

# Frontend
FRONTEND_URL=http://localhost:3000
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001

# Email (Resend en producción, console en desarrollo)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
RESEND_API_KEY=
DEFAULT_FROM_EMAIL=EventSync <noreply@notifications.eventsync.cloud>

# AWS S3 (imágenes — actualmente Firebase; S3 para Fase 2+)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_STORAGE_BUCKET_NAME=eventsync-media
AWS_S3_REGION_NAME=us-east-1

# Sentry
SENTRY_DSN=
```

---

## Comandos Útiles

### Setup Inicial

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements/development.txt
createdb eventsync
cp .env.example .env
# Editar .env con tus credenciales

# Migraciones
python manage.py migrate_schemas --shared
python manage.py migrate_schemas

# Crear tenant público
python manage.py shell
>>> from apps.tenants.models import Tenant, Domain
>>> t = Tenant.objects.create(schema_name='public', name='Public')
>>> Domain.objects.create(domain='localhost', tenant=t, is_primary=True)
>>> Domain.objects.create(domain='127.0.0.1', tenant=t)
```

### Desarrollo

```bash
python manage.py runserver          # Servidor Django
celery -A config worker -B -l info  # Celery worker + beat (desarrollo)
```

### Migraciones

```bash
python manage.py makemigrations {app}
python manage.py migrate_schemas --shared
python manage.py migrate_schemas
python manage.py showmigrations
```

### Testing

```bash
pytest                                    # Todos los tests
pytest apps/events/tests/                 # Tests de una app
pytest --cov=apps --cov-report=html       # Con cobertura
open htmlcov/index.html
```

### Code Quality

```bash
black apps/
isort apps/
flake8 apps/
```

### Base de Datos

```bash
psql eventsync                            # Conectarse
psql eventsync -c "\dn"                  # Ver schemas
psql eventsync -c "\dt"                  # Ver tablas del schema actual
```

---

## Consideraciones de Seguridad

- **SQL Injection**: Siempre usar ORM, nunca raw SQL sin parametrizar
- **Tenant Isolation**: NUNCA queries sin filtro de tenant — django-tenants lo maneja automáticamente via schema
- **Secrets**: Usar variables de entorno, NUNCA commitear `.env`

- **JWT**: Blacklist activado para invalidar tokens al logout

## Performance

- `select_related()` y `prefetch_related()` para evitar N+1 queries
- Redis para caché de queries frecuentes
- Siempre paginar listados (DRF pagination)

---

**Última actualización**: 2026-04-07
**Versión**: 1.0.0 — separado del monorepo en FEAT-04
