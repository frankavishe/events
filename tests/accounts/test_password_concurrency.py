"""Real threads on committed rows; see tests/payments/test_concurrency.py."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import connection

from apps.accounts import services
from apps.accounts.models import PasswordCode, User
from tests.factories import ClientFactory


@pytest.fixture
def user(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        user = ClientFactory(phone="+255687000001", email="race@example.com")
        yield user
        User.objects.filter(pk=user.pk).delete()
        connection.close()


def race(code, passwords):
    user_phone, barrier = "+255687000001", Barrier(len(passwords))

    def run(password):
        try:
            barrier.wait(timeout=10)
            return services.set_password_with_code(user_phone, code, password)
        except services.InvalidCode as exc:
            return exc
        finally:
            connection.close()

    with ThreadPoolExecutor(len(passwords)) as pool:
        return list(pool.map(run, passwords))


def test_one_code_sets_one_password(user):
    results = race(services.issue_code(user), [f"Pilau-Tamu-202{n}" for n in range(6)])
    assert sum(isinstance(r, User) for r in results) == 1


def test_simultaneous_wrong_codes_are_all_counted(user):
    code = services.issue_code(user)
    race(f"{(int(code) + 1) % 1_000_000:06d}", ["Pilau-Tamu-2027"] * 4)
    assert PasswordCode.objects.get(user=user).attempts == 4
