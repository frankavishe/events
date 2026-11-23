import pytest
from rest_framework.test import APIClient


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client(api_client):
    """Return a factory that authenticates the shared APIClient as a given user via JWT."""
    from rest_framework_simplejwt.tokens import RefreshToken

    def _auth(user):
        token = RefreshToken.for_user(user).access_token
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return api_client

    return _auth
