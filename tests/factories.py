import factory
from django.contrib.auth import get_user_model

User = get_user_model()

DEFAULT_PASSWORD = "Chakula-Bora-2026"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    phone = factory.Sequence(lambda n: f"+2557{n:08d}")
    full_name = factory.Faker("name")
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    role = User.Role.CLIENT
    preferred_language = "en"
    is_active = True

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        self.set_password(extracted or DEFAULT_PASSWORD)
        if create:
            self.save(update_fields=["password"])


class ClientFactory(UserFactory):
    role = User.Role.CLIENT


class VendorUserFactory(UserFactory):
    role = User.Role.VENDOR


class AdminFactory(UserFactory):
    role = User.Role.ADMIN
    is_staff = True
