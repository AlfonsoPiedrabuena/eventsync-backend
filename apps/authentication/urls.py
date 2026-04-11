"""
URL configuration for Authentication app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    TenantRegistrationView,
    LoginView,
    LogoutView,
    EmailVerificationView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    InvitationListCreateView,
    InvitationAcceptView,
    CurrentUserView,
    TeamViewSet,
)

app_name = 'authentication'

router = DefaultRouter()
router.register(r'team', TeamViewSet, basename='team')

urlpatterns = [
    # Registration and login (E1)
    path('register/', TenantRegistrationView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # JWT token refresh
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Email verification
    path('verify-email/<str:token>/', EmailVerificationView.as_view(), name='verify-email'),

    # Password reset
    path('password-reset/', PasswordResetRequestView.as_view(), name='password-reset'),
    path('password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),

    # Invitations
    path('invitations/', InvitationListCreateView.as_view(), name='invitations'),
    path('invitations/accept/', InvitationAcceptView.as_view(), name='invitation-accept'),

    # Current user
    path('me/', CurrentUserView.as_view(), name='current-user'),

    # Team management (FEAT-07)
    path('', include(router.urls)),
]
