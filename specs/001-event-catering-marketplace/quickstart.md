# Quickstart & Validation Guide

## Prerequisites
- Python 3.12+ and `uv`; Docker Desktop (Postgres 16 + Redis 7).
- Copy `.env.example` → `.env`. For local dev keep `PAYMENT_GATEWAY=mock`, `MESSAGING_PROVIDER=fake` and `LLM_PROVIDER=fake`
  until real credentials exist.

## Setup
```powershell
docker compose up -d db redis
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py seed_demo        # Phase 5: demo vendors, items, areas
uv run python manage.py runserver
uv run celery -A config worker -l info -P solo   # separate terminal (Windows needs -P solo)
uv run celery -A config beat -l info              # separate terminal
```
API docs: http://localhost:8000/api/docs/

## Quality gate (every phase)
```powershell
uv run ruff check . ; uv run ruff format --check .
uv run pytest
uv run python manage.py makemigrations --check --dry-run
```

## Validation scenarios
1. **Vendor onboarding (US1)**: `POST /auth/register/vendor/` → status pending; `GET /items/` has none
   of their items; admin `POST /admin/vendors/{id}/approve/`; vendor `POST /vendor/items/`; item
   now visible in `GET /items/?kind=drink&is_alcoholic=false`.
2. **Booking (US2)**: client registers, `POST /events/`, `POST /orders/` with lines → 201, total =
   Σ price×qty. Alcoholic line without `age_confirmed` → 400. Vendor `confirm/` → confirmed.
3. **Online payment (US3)**: `POST /orders/{id}/pay/` (mock or AzamPay sandbox) → 202; simulate the callback:
   ```powershell
   curl -X POST http://localhost:8000/api/v1/webhooks/azampay/<token>/ -H "Content-Type: application/json" `
     -d '{"utilityref":"<payment_id>","amount":"<total>","transactionstatus":"success","reference":"T1"}'
   ```
   Order → paid; `GET /vendor/earnings/` shows net = 90%. Repeat the callback → no duplicate earning.
4. **Cash (US3)**: `pay/` with `{method:"cash"}` → awaiting_cash; vendor `confirm-cash/` → paid; vendor
   balance decreases by 10% commission.
5. **Expiry**: create an order, advance time 24 h (freezegun in tests) and run `expire_pending_orders` → expired.
6. **WhatsApp (US4)**: post the sample payloads in `tests/chatbot/fixtures/` to `/api/v1/webhooks/whatsapp/`
   with a valid signature; with `LLM_PROVIDER=gemini` and a real key, ask "Bei ya soda ni kiasi gani?"
   → Swahili reply with the catalog price. Live test: ngrok + Meta test number.
   Evaluation: `uv run python -m scripts.eval_chatbot` (needs `GEMINI_API_KEY`; changes no data).
7. **Payout (US5)**: admin `POST /admin/payouts/` ≤ balance → 201; > balance → 400.
