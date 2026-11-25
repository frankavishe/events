FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Base settings with throwaway values: production settings require real credentials.
RUN DJANGO_SETTINGS_MODULE=config.settings.base \
    DJANGO_SECRET_KEY=build-only \
    DATABASE_URL=postgres://build:build@localhost/build \
    python manage.py collectstatic --noinput

RUN useradd --create-home app && mkdir -p media && chown app:app media
USER app

EXPOSE 8000

# No access log: paths can contain the AzamPay callback token. The app logs each request itself.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
