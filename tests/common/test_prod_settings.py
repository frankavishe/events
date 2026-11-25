import os
import subprocess
import sys

import pytest

ENV = {
    "DJANGO_SECRET_KEY": "x",
    "DATABASE_URL": "postgres://x:x@localhost/x",
    "DJANGO_ALLOWED_HOSTS": "example.com",
    "DJANGO_NUM_PROXIES": "1",
    "PAYMENT_GATEWAY": "azampay",
    "AZAMPAY_CALLBACK_TOKEN": "x",
    "MESSAGING_PROVIDER": "whatsapp",
    "LLM_PROVIDER": "gemini",
    "WHATSAPP_ACCESS_TOKEN": "x",
    "WHATSAPP_PHONE_NUMBER_ID": "x",
    "WHATSAPP_VERIFY_TOKEN": "x",
    "WHATSAPP_APP_SECRET": "x",
    "GEMINI_API_KEY": "x",
}


@pytest.mark.parametrize(("template", "starts"), [("auth_code", True), ("", False)])
def test_auth_code_template_is_required(template, starts):
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings.prod"],
        env={**os.environ, **ENV, "WHATSAPP_TEMPLATE_AUTH_CODE": template},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is starts, result.stderr
    assert starts or "WHATSAPP_TEMPLATE_AUTH_CODE is required" in result.stderr
