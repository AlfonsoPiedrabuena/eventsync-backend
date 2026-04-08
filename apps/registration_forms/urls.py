from rest_framework.routers import DefaultRouter
from .views import RegistrationFormFieldViewSet

router = DefaultRouter()
router.register(r'registration-form-fields', RegistrationFormFieldViewSet, basename='form-fields')

urlpatterns = router.urls
