# Implementation Plan: Event Catering & Drinks Marketplace (Backend)

**Branch**: `001-event-catering-marketplace` | **Date**: 2026-11-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-event-catering-marketplace/spec.md`

## Summary

A backend-only marketplace API where vendors publish food and drink items or packages and clients
book them for events, paying online through AzamPay (mobile money or bank) or in cash. A WhatsApp
assistant powered by Google Gemini function calling answers questions and makes bookings in
English or Swahili, using only database data through the same service layer as the REST API.
Built as a modular Django + DRF monolith on PostgreSQL, with Celery and Redis for async work
(chat processing, order expiry, notifications).

## Technical Context

**Language/Version**: Python 3.12+ (dev on 3.14), managed with `uv`

**Primary Dependencies**: Django 5.2 LTS+, djangorestframework, djangorestframework-simplejwt,
drf-spectacular, django-filter, django-environ, psycopg[binary] 3, celery[redis],
django-celery-beat, httpx, google-genai, Pillow (item images)

**Storage**: PostgreSQL 16 (primary), Redis 7 (Celery broker/result, cache, throttling);
media files on local disk in dev (S3-compatible in prod, out of scope)

**Testing**: pytest, pytest-django, factory-boy, respx (httpx mocking), freezegun; ruff for lint/format

**Target Platform**: Linux server (Docker); local dev on Windows via `docker compose` for Postgres
and Redis

**Project Type**: web-service (REST API + webhooks)

**Performance Goals**: catalog list p95 < 300 ms at 50 rps; WhatsApp reply within 10 s for 95% of
messages (LLM-bound)

**Constraints**: free tiers of Gemini and the WhatsApp Cloud API (rate limits, so retries with
backoff); Meta webhook MUST get a 200 response quickly, so processing is async; money as Decimal TZS

**Scale/Scope**: launch target ≈ 200 vendors, 10k clients, 5k items, 1k orders/month; 9 Django apps

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How the design complies | Status |
|-----------|------------------------|--------|
| I. Backend-Only API | DRF under `/api/v1/`, webhooks under `/api/v1/webhooks/`, OpenAPI via drf-spectacular at `/api/schema/` + `/api/docs/`; admin only for operators | PASS |
| II. Test-First | Each task in tasks.md is preceded by a failing test task; AzamPay/Meta mocked with respx, Gemini via a `FakeLLM` implementing the LLM interface | PASS |
| III. Money Integrity | `DecimalField(max_digits=12, decimal_places=2)`; totals computed in `orders.services`; `Payment` success guarded by `select_for_update` + unique `gateway_reference`; `VendorEarning` OneToOne with `Order`; `OrderStatusChange` audit log | PASS |
| IV. Grounded Bilingual AI | Gemini function calling with tools that call `catalog`/`orders` services only; system prompt forbids answering prices without tool output; replies tested for language and grounding | PASS |
| V. Secure by Default | django-environ; JWT; role permission classes + queryset scoping; Meta HMAC check; AzamPay callback reconciled against stored externalId and amount + secret path token; 18+ flag enforced in service | PASS |
| VI. Simplicity & Pluggable | `PaymentGateway`, `LLMClient`, `MessagingClient` protocols with mock implementations; business logic in `services.py` per app | PASS |

Post-design re-check (after Phase 1): PASS — no violations; Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-event-catering-marketplace/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── rest-api.md      # REST endpoint contract (source of truth until OpenAPI is generated)
│   └── webhooks.md      # WhatsApp + AzamPay inbound contracts, and AI tool schemas
├── checklists/requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
pyproject.toml            # uv project, ruff + pytest config
docker-compose.yml        # postgres, redis (and optional web/worker/beat)
.env.example
manage.py
config/
├── settings/{base.py,dev.py,test.py,prod.py}
├── urls.py               # /api/v1/..., /api/schema/, /api/docs/, /admin/
├── celery.py
└── wsgi.py / asgi.py
apps/
├── common/               # BaseModel (uuid pk, timestamps), permissions, pagination, money utils
├── accounts/             # User (role, phone, language), auth endpoints, JWT
├── vendors/              # VendorProfile, ServiceArea, approval/suspension
├── catalog/              # Category, Item, Package, PackageItem; public browse/filter
├── events/               # Event
├── orders/               # Order, OrderLine, OrderStatusChange; services.py state machine; expiry task
├── payments/             # Payment; gateways/{base.py,azampay.py,mock.py}; callback view
├── ledger/               # CommissionSetting, VendorEarning, Payout; earnings summary
├── notifications/        # MessagingClient (WhatsApp send text/template), notify_* tasks
└── chatbot/              # WhatsApp webhook, Conversation, ChatMessage, llm/{base,gemini,fake}.py, tools.py, agent.py
tests/                    # mirrors apps/: tests/<app>/test_*.py; conftest.py with factories
```

**Structure Decision**: Single Django project with one app per bounded context under `apps/`.
Cross-app calls go through each app's `services.py`, not models directly. Chatbot tools and
REST views call the same services.

## Delivery Phases (human review + commit by owner after each)

| Phase | Scope | User stories |
|-------|-------|--------------|
| 1 | Setup + foundation: project scaffold, settings, docker, common, accounts/JWT, roles | (blocking) |
| 2 | Vendors, catalog, events | US1, part of US2 |
| 3 | Orders, payments (AzamPay + cash), ledger, expiry | US2, US3 |
| 4 | WhatsApp assistant + notifications | US4 |
| 5 | Earnings/payout admin, hardening, seed data, docs | US5, polish |

## Complexity Tracking

No constitution violations.
