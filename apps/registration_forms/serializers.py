import re
from rest_framework import serializers
from .models import RegistrationFormField


class RegistrationFormFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegistrationFormField
        fields = (
            'id', 'label', 'field_type', 'placeholder',
            'is_required', 'is_enabled', 'order', 'options', 'field_key',
        )
        read_only_fields = ('id',)

    def validate_field_key(self, value):
        if not re.match(r'^[a-z0-9_-]+$', value):
            raise serializers.ValidationError(
                'field_key solo puede contener letras minúsculas, números, guiones y guiones bajos.'
            )
        return value

    def validate(self, attrs):
        field_type = attrs.get('field_type', getattr(self.instance, 'field_type', None))
        options = attrs.get('options', getattr(self.instance, 'options', []))
        if field_type == RegistrationFormField.FieldType.SELECT and not options:
            raise serializers.ValidationError(
                {'options': 'Un campo de tipo select requiere al menos una opción.'}
            )
        return attrs


class FormFieldReorderSerializer(serializers.Serializer):
    """Recibe lista de IDs en el nuevo orden."""
    field_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
    )
