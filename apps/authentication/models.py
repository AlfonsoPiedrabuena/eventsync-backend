"""
User model for authentication and authorization.
"""
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone


class UserManager(BaseUserManager):
    """Custom user manager for email-based authentication."""

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular user."""
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and save a superuser."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'super_admin')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for EventSync.

    Users are associated with a tenant (organization) and have a role
    that determines their permissions within that tenant.
    """
    ROLE_CHOICES = (
        ('super_admin', 'Super Admin'),  # Catalysis staff, global access
        ('tenant_admin', 'Tenant Admin'),  # Organization administrator
        ('organizer', 'Organizador de Eventos'),  # Event organizer
        ('checkin_staff', 'Staff de Check-in'),  # Check-in staff
    )

    # Basic fields
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)

    # Role and permissions
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='organizer'
    )

    # Tenant association (null for super_admin)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users'
    )

    # Email verification
    is_email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=100, blank=True)

    # Status fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['role']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.get_full_name()} ({self.email})"

    def get_full_name(self):
        """Return the user's full name."""
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        """Return the user's first name."""
        return self.first_name

    def is_tenant_admin(self):
        """Check if user is a tenant admin."""
        return self.role == 'tenant_admin'

    def is_organizer_or_above(self):
        """Check if user has organizer permissions or higher."""
        return self.role in ['tenant_admin', 'organizer', 'super_admin']

    def can_manage_event(self, event):
        """
        Check if user can manage a specific event.

        Args:
            event: Event instance

        Returns:
            bool: True if user can manage the event
        """
        if self.role == 'super_admin':
            return True
        if self.role == 'tenant_admin':
            return True
        if self.role == 'organizer':
            # TODO: Check if user is assigned to this event
            return True
        return False


class Invitation(models.Model):
    """
    User invitation model for tenant onboarding.

    When a tenant admin invites a new user, an invitation is created
    with a unique token. The invitee can use this token to complete
    their registration.
    """
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    )

    email = models.EmailField(db_index=True)
    first_name = models.CharField(max_length=50, blank=True)
    last_name = models.CharField(max_length=50, blank=True)
    role = models.CharField(
        max_length=20,
        choices=User.ROLE_CHOICES,
        default='organizer'
    )
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='invitations'
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_invitations'
    )

    token = models.CharField(max_length=100, unique=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'invitations'
        verbose_name = 'Invitation'
        verbose_name_plural = 'Invitations'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['token']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"Invitation to {self.email} for {self.tenant.name}"

    def is_expired(self):
        """Check if invitation has expired."""
        return timezone.now() > self.expires_at

    def is_valid(self):
        """Check if invitation is still valid."""
        return self.status == 'pending' and not self.is_expired()
