# Event Catering & Drinks Marketplace: backend

REST API and WhatsApp assistant for booking food and drinks for events in Tanzania. Clients book
vendors, pay online (AzamPay) or in cash, and the platform keeps a commission ledger.

Backend only: web and mobile apps use the API; the Django admin is for operators.

## Setup

Needs Python 3.12+, [uv](https://docs.astral.sh/uv/) and Docker.

```powershell
Copy-Item .env.example .env        # then set DJANGO_SECRET_KEY
docker compose up -d db redis
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py seed_demo  # optional; prints a password for the demo users
uv run python manage.py runserver
uv run celery -A config worker -l info -P solo   # second terminal (-P solo on Windows)
uv run celery -A config beat -l info              # third terminal
```

Or run everything in containers: `docker compose up -d --build`.

- API docs: <http://localhost:8000/api/docs/>; schema: `docs/openapi.yaml`
- Admin: <http://localhost:8000/admin/>
- Walkthrough: `specs/001-event-catering-marketplace/quickstart.md`

## Environment

Every variable is in `.env.example`. With `PAYMENT_GATEWAY=mock`, `MESSAGING_PROVIDER=fake` and
`LLM_PROVIDER=fake` no outside account is needed.

## Architecture

Django + DRF, PostgreSQL, Redis and Celery. Business logic is in each app's `services.py`; views,
the admin and the WhatsApp assistant all call it.

| App | Responsibility |
|-----|----------------|
| `accounts` | Users (client, vendor, admin), JWT login by phone or email |
| `vendors` | Vendor profiles, approval, service areas |
| `catalog` | Categories, items, packages |
| `events` | Clients' events |
| `orders` | Orders, price snapshots, state machine, expiry |
| `payments` | Online and cash payments; gateways (AzamPay, mock) |
| `ledger` | Commission, earnings, payouts, balances |
| `notifications` | Outgoing WhatsApp messages |
| `chatbot` | WhatsApp webhook and assistant (Gemini) |
| `common` | Money, phones, permissions, throttling, logging |

Money is `Decimal` TZS. A vendor's balance is net online earnings, minus commission owed on cash
orders, minus payouts. Payouts are made outside the system and then recorded.

## Quality gate

```powershell
uv run ruff check . ; uv run ruff format --check .
uv run pytest
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py spectacular --validate --fail-on-warn --file docs/openapi.yaml
```

Tests need the `db` container, and no network or credentials.

## Production notes

- Use `DJANGO_SETTINGS_MODULE=config.settings.prod`. It refuses mock and fake providers and
  missing credentials.
- Set `DJANGO_NUM_PROXIES` to the number of proxies in front of the app. Too low and clients share
  one request limit; too high and they can forge their address. Let only the proxy reach the app:
  it must set `X-Forwarded-Proto` and `X-Forwarded-For` itself.
- Turn off or redact path logging in the proxy: AzamPay callback paths contain a secret. The
  app's own logs (JSON, one line per request) use the route and redact the token.
- Requests are counted in Redis; without Redis the API does not answer.
- The admin login is not rate limited. Restrict `/admin/` at the proxy.
- Uploaded images are written to `media/`, which the app serves only in development. Put it on
  shared storage and serve it from the proxy.
- Run one `beat` only, and apply migrations before starting the new version.

## Delivery phases

1. Setup, accounts. 2. Vendors, catalog, events. 3. Orders, payments, ledger.
4. WhatsApp assistant. 5. Earnings and payouts API, limits, logging, demo data, containers.

Details: `specs/001-event-catering-marketplace/`.
