<!--
Sync Impact Report
- Version change: (template) → 1.0.0
- Principles defined: I. Backend-Only API, II. Test-First, III. Money Integrity,
  IV. Grounded Bilingual AI, V. Secure by Default, VI. Simplicity & Pluggable Integrations
- Added sections: Technology & Platform Constraints, Development Workflow & Quality Gates, Governance
- Removed sections: none
- Templates requiring updates: none (plan/spec/tasks templates read this file at runtime)
- Follow-up TODOs: none
-->

# Event Catering & Drinks Marketplace Constitution

## Core Principles

### I. Backend-Only API

- The product scope of this repository is the backend only. It MUST expose functionality
  through a versioned REST API (`/api/v1/...`) plus inbound webhooks (WhatsApp, payment gateway).
- No server-rendered client UI is built here; the Django admin is the only HTML interface and is
  for platform operators.
- Every endpoint MUST be described in the generated OpenAPI schema so frontend and mobile
  teams can integrate without reading source code.

Rationale: A separate frontend team (web/mobile) consumes the API; a clean contract keeps both
sides independent.

### II. Test-First (NON-NEGOTIABLE)

- For every task with behaviour, tests are written first and MUST fail before implementation.
- Every API endpoint MUST have tests covering success, permission denial, and validation errors.
- Order state transitions, payment callbacks, commission calculation, and AI tool functions
  MUST have unit tests.
- External services (AzamPay, Meta WhatsApp, Google Gemini) MUST be mocked in tests; the test
  suite MUST pass with no network access and no real credentials.

Rationale: Payments and bookings handle real money and real events; regressions are costly.

### III. Money Integrity

- All monetary amounts MUST use `Decimal` / `DecimalField` (never float), in Tanzanian
  Shillings (TZS) unless a currency field explicitly says otherwise.
- Order totals MUST be computed on the server from price snapshots stored on order items;
  client-supplied totals are ignored.
- Payment callbacks MUST be idempotent and verified; a payment can be marked successful at most
  once, and every status change MUST be recorded with timestamp and actor.
- Cash (offline) payments MUST be confirmed by an authorised vendor or admin user and audited.
- Commission and vendor earnings MUST be recorded in a ledger at the moment a payment succeeds,
  using the commission rate in effect at that time.

Rationale: Financial records must be reproducible and defensible in disputes.

### IV. Grounded Bilingual AI

- The WhatsApp assistant MUST answer questions about food, drinks, vendors, prices,
  availability, and orders only from the application's database, accessed through explicit
  tool/function calls. It MUST NOT invent items, prices, or vendors.
- When data is missing, the assistant MUST say so and offer alternatives that exist in the
  database.
- The assistant MUST support English and Swahili, replying in the language the user writes in.
- Bookings created through WhatsApp MUST go through the same service layer and validation as
  the REST API (no duplicate business logic).

Rationale: Wrong prices or phantom items destroy customer trust and cause financial disputes.

### V. Secure by Default

- Secrets (DB credentials, AzamPay keys, Meta tokens, Gemini key) MUST come from environment
  variables; they MUST NOT be committed. `.env.example` documents every variable.
- Authentication uses JWT; every endpoint declares explicit permissions by role
  (client, vendor, admin). Vendors may only access their own catalog, orders, and earnings.
- Incoming webhooks MUST be authenticated (Meta `X-Hub-Signature-256`; AzamPay callback
  verification against the gateway) before any state change.
- Alcoholic items MUST require an age confirmation (18+) from the client at order time.

Rationale: The system processes payments and personal data and sells age-restricted goods.

### VI. Simplicity & Pluggable Integrations

- Prefer Django/DRF built-ins over new dependencies; each added dependency MUST be justified.
- External integrations (payment gateway, LLM, messaging) MUST sit behind a small interface
  with a mock implementation, so providers can be swapped without touching business logic.
- Business logic lives in service modules, not in views or serializers.

Rationale: Free-tier providers change; the core marketplace must outlive any one of them.

## Technology & Platform Constraints

- Language/runtime: Python 3.12+ (developed on 3.14), dependencies managed with `uv`.
- Framework: Django + Django REST Framework; OpenAPI via drf-spectacular.
- Database: PostgreSQL. SQLite MUST NOT be used outside throwaway experiments.
- Async work (WhatsApp message processing, payment status polling, notifications): Celery with
  Redis.
- Payments: AzamPay (mobile money and bank checkout) for online payment; cash as offline payment.
- Messaging: Meta WhatsApp Cloud API. LLM: Google Gemini API (model name configurable).
- Locale: default timezone `Africa/Dar_es_Salaam`, default currency TZS, languages `en` and `sw`.

## Development Workflow & Quality Gates

- Work proceeds in phases defined in the feature's `tasks.md`. At the end of each phase,
  development stops for human review; the project owner performs all git commits.
- A phase is complete only when `uv run pytest` and `uv run ruff check` pass and migrations
  are generated and applied cleanly.
- Every schema change ships with a Django migration.
- Every feature updates the OpenAPI schema and, where relevant, `.env.example` and the README.

## Governance

- This constitution supersedes other practices in this repository. Specs, plans, and tasks MUST
  include a constitution check; deviations MUST be justified in the plan's Complexity Tracking
  section.
- Amendments are made via `/speckit-constitution`, documented in the Sync Impact Report, and
  versioned with semantic versioning (MAJOR: principle removal/redefinition; MINOR: new principle
  or materially expanded guidance; PATCH: clarifications).
- Reviewers verify compliance with these principles before each phase is committed.

**Version**: 1.0.0 | **Ratified**: 2026-11-23 | **Last Amended**: 2026-11-23
