---
description: "Task list for Event Catering & Drinks Marketplace (Backend)"
---

# Tasks: Event Catering & Drinks Marketplace (Backend)

**Input**: Design documents from `specs/001-event-catering-marketplace/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED. Constitution II (Test-First) applies, so each story's test tasks come first and
MUST fail before implementation.

**Organization**: Tasks are grouped by user story. A **🛑 REVIEW & COMMIT** checkpoint ends each
delivery phase. Implementation stops there until the project owner has reviewed and committed.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: US1–US5 from spec.md
- Paths are relative to the repository root (see plan.md → Project Structure)

---

## Phase 1: Setup (Shared Infrastructure) — Delivery Phase 1

- [x] T001 Initialize uv project with dependencies from plan.md and ruff/pytest config in pyproject.toml
- [x] T002 Create Django project `config/` with split settings in config/settings/base.py, dev.py, test.py, prod.py (django-environ, TZ Africa/Dar_es_Salaam, LANGUAGES en/sw)
- [x] T003 [P] Create docker-compose.yml with postgres:16 and redis:7 services
- [x] T004 [P] Create .env.example documenting every variable (DB, Redis, JWT, AZAMPAY_*, WHATSAPP_*, GEMINI_*, PAYMENT_GATEWAY, LLM_PROVIDER)
- [x] T005 [P] Create .gitignore (.env, media/, __pycache__, .venv, .claude/settings.local.json)
- [x] T006 Configure Celery in config/celery.py and config/__init__.py; CELERY_TASK_ALWAYS_EAGER in test settings
- [x] T007 Configure DRF, SimpleJWT, drf-spectacular, django-filter, and URL routing (/api/v1/, /api/schema/, /api/docs/) in config/settings/base.py and config/urls.py
- [x] T008 [P] Create tests/conftest.py with api_client fixture and pytest-django DB settings

## Phase 2: Foundational (Blocking Prerequisites) — Delivery Phase 1

- [x] T009 [P] Write tests for BaseModel, money helpers (round half-up, TZS formatting), and phone normalization in tests/common/test_utils.py
- [x] T010 Implement apps/common/ (BaseModel UUID+timestamps, money.py, phone.py, pagination.py, exceptions handler with error shape from contracts/rest-api.md)
- [x] T011 [P] Write tests for registration, token login by phone or email, /me/ in tests/accounts/test_auth_api.py
- [x] T012 Implement custom User model and manager (phone login, role, preferred_language, created_via) in apps/accounts/models.py; set AUTH_USER_MODEL; migration
- [x] T013 Implement auth serializers/views (/auth/register/, /auth/token/, /auth/token/refresh/, /me/) in apps/accounts/
- [x] T014 [P] Implement role permission classes IsClient, IsVendor, IsApprovedVendor, IsAdmin in apps/common/permissions.py with tests in tests/common/test_permissions.py
- [x] T015 Create tests/factories.py (UserFactory and role variants)
- [x] T016 Register User in admin (apps/accounts/admin.py); verify `/api/docs/` renders

**🛑 REVIEW & COMMIT — Delivery Phase 1** (gate: pytest, ruff, `makemigrations --check`)

---

## Phase 3: User Story 1 — Vendor registers and publishes a menu (P1) — Delivery Phase 2

**Goal**: Vendors register (pending), get approved, and manage their items and packages. The public catalog shows only approved, available items.
**Independent Test**: quickstart scenario 1.

### Tests (write first, must fail)
- [x] T017 [P] [US1] Vendor registration + admin approve/reject/suspend tests in tests/vendors/test_vendor_api.py
- [x] T018 [P] [US1] Vendor item/package CRUD + ownership isolation + validation (alcoholic only for drinks, category kind match) tests in tests/catalog/test_vendor_catalog_api.py
- [x] T019 [P] [US1] Public catalog visibility and filter tests (kind, is_alcoholic, category, vendor, service_area, price range, search) in tests/catalog/test_public_catalog_api.py

### Implementation
- [x] T020 [P] [US1] VendorProfile and ServiceArea models + migration in apps/vendors/models.py
- [x] T021 [P] [US1] Category, Item, Package, PackageItem models + migration + category seed data migration in apps/catalog/models.py
- [x] T022 [US1] Vendor services (register_vendor, approve, reject, suspend) in apps/vendors/services.py
- [x] T023 [US1] Vendor endpoints (/auth/register/vendor/, /vendor/profile/, /vendors/, /service-areas/, /admin/vendors/{id}/approve|reject|suspend/) in apps/vendors/views.py, serializers.py, urls.py
- [x] T024 [US1] Catalog query services (public_items, public_packages, search) in apps/catalog/services.py
- [x] T025 [US1] Vendor catalog endpoints (/vendor/items/, /vendor/packages/) scoped to request vendor in apps/catalog/views.py
- [x] T026 [US1] Public catalog endpoints + FilterSets (/categories/, /items/, /packages/) in apps/catalog/views.py, filters.py
- [x] T027 [P] [US1] Admin registrations for vendors and catalog with approve action in apps/vendors/admin.py, apps/catalog/admin.py

### Events (needed by US2, delivered with Phase 2)
- [x] T028 [P] [US2] Event CRUD + ownership + future-date tests in tests/events/test_events_api.py
- [x] T029 [US2] Event model + migration, serializers, /events/ viewset in apps/events/

**🛑 REVIEW & COMMIT — Delivery Phase 2**

---

## Phase 4: User Story 2 — Client books catering/drinks (P1) — Delivery Phase 3

**Goal**: Clients place orders with server-computed totals, and vendors confirm or decline them. Orders follow the state machine and expire after 24 hours.
**Independent Test**: quickstart scenarios 2 and 5.

### Tests
- [ ] T030 [P] [US2] State-machine unit tests (every allowed/forbidden transition × role, audit row written) in tests/orders/test_state_machine.py
- [ ] T031 [P] [US2] Order creation tests (totals, snapshots unaffected by later price change, min qty, min notice, unavailable item, unapproved vendor, mixed vendors rejected, 18+ rule, package per-guest pricing) in tests/orders/test_create_order.py
- [ ] T032 [P] [US2] Order API scoping and action endpoint tests (confirm/decline/cancel/fulfil/complete → 409 on invalid) in tests/orders/test_orders_api.py
- [ ] T033 [P] [US2] Expiry task test with freezegun in tests/orders/test_expiry.py

### Implementation
- [ ] T034 [US2] Order, OrderLine, OrderStatusChange models + migration (reference generator) in apps/orders/models.py
- [ ] T035 [US2] orders/services.py: create_order (validation + snapshots + totals), transition() with ALLOWED table, list scoping helpers
- [ ] T036 [US2] Order serializers and viewset with actions in apps/orders/views.py, serializers.py, urls.py
- [ ] T037 [US2] Celery beat task expire_pending_orders (every 15 min) in apps/orders/tasks.py and beat schedule in settings
- [ ] T038 [P] [US2] Order admin with status history inline in apps/orders/admin.py

## Phase 5: User Story 3 — Pay online or cash (P1) — Delivery Phase 3

**Goal**: Online payment via AzamPay (mock in dev and tests) and cash confirmation. Each successful payment creates exactly one ledger earning.
**Independent Test**: quickstart scenarios 3 and 4.

### Tests
- [ ] T039 [P] [US3] AzamPayGateway tests with respx (token caching, MNO checkout request shape, error → GatewayError) in tests/payments/test_azampay_gateway.py
- [ ] T040 [P] [US3] Pay endpoint tests (online 202, cash → awaiting_cash, not-confirmed → 409, already paid → 409, gateway down → 502 + order still payable) in tests/payments/test_pay_api.py
- [ ] T041 [P] [US3] Callback tests (bad token 404, success once, duplicate no-op, failure, amount mismatch, unknown ref, failure-after-success ignored) in tests/payments/test_azampay_callback.py
- [ ] T042 [P] [US3] Cash confirm tests (vendor owner ok, other vendor 403, client 403) in tests/payments/test_cash.py
- [ ] T043 [P] [US3] Ledger unit tests (commission rounding, rate at payment time, cash earning as commission owed, balance formula, refund reversal) in tests/ledger/test_ledger_services.py

### Implementation
- [ ] T044 [US3] Payment model + partial unique constraint + migration in apps/payments/models.py
- [ ] T045 [P] [US3] PaymentGateway protocol + GatewayError in apps/payments/gateways/base.py; MockGateway in gateways/mock.py; factory get_gateway() by settings
- [ ] T046 [US3] AzamPayGateway (token cache in Redis/Django cache, MNO + bank checkout) in apps/payments/gateways/azampay.py
- [ ] T047 [P] [US3] CommissionSetting (seed 10%), VendorEarning, Payout models + migration in apps/ledger/models.py
- [ ] T048 [US3] ledger/services.py: current_rate(), record_earning(payment), reverse_earning(order), vendor_balance(vendor)
- [ ] T049 [US3] payments/services.py: start_payment(), confirm_cash(), handle_gateway_result() (select_for_update, idempotent, calls orders.transition + ledger.record_earning)
- [ ] T050 [US3] Endpoints /orders/{id}/pay/, /orders/{id}/confirm-cash/, /payments/{id}/, /orders/{id}/refund/ and AzamPay callback view /api/v1/webhooks/azampay/<token>/ in apps/payments/views.py, urls.py
- [ ] T051 [US3] reconcile_pending_payments beat task (flag online payments pending >30 min) in apps/payments/tasks.py

**🛑 REVIEW & COMMIT — Delivery Phase 3** (+ optional AzamPay sandbox smoke test with owner's credentials)

---

## Phase 6: User Story 4 — WhatsApp assistant (P2) — Delivery Phase 4

**Goal**: A bilingual, grounded assistant answers and books through the same services as the API.
**Independent Test**: quickstart scenario 6.

### Tests
- [ ] T052 [P] [US4] Webhook tests (GET verify, bad signature 403, dedupe by wamid, non-text reply, returns 200 + enqueues) in tests/chatbot/test_webhook.py with payload fixtures in tests/chatbot/fixtures/
- [ ] T053 [P] [US4] Tool unit tests (each tool calls services, scoped to sender, price formatting, validation errors returned as messages) in tests/chatbot/test_tools.py
- [ ] T054 [P] [US4] Agent loop tests with FakeLLM (tool round-trips, max rounds, LLM failure → bilingual fallback, history window 20) in tests/chatbot/test_agent.py
- [ ] T055 [P] [US4] End-to-end chat booking test (unknown number → register → event → order → cash) in tests/chatbot/test_booking_flow.py
- [ ] T056 [P] [US4] MessagingClient tests with respx (text send, template send, 24 h window choice) in tests/notifications/test_whatsapp_client.py

### Implementation
- [ ] T057 [US4] Conversation and ChatMessage models + migration in apps/chatbot/models.py
- [ ] T058 [P] [US4] MessagingClient protocol, WhatsAppCloudClient (httpx), FakeMessagingClient in apps/notifications/clients.py
- [ ] T059 [P] [US4] LLMClient protocol, GeminiClient (google-genai function calling), FakeLLM in apps/chatbot/llm/
- [ ] T060 [US4] Tool declarations + implementations per contracts/webhooks.md in apps/chatbot/tools.py
- [ ] T061 [US4] Bilingual grounded system prompt in apps/chatbot/prompts.py and agent loop (history, tool dispatch, language update) in apps/chatbot/agent.py
- [ ] T062 [US4] Webhook view (verify + HMAC + persist + enqueue) in apps/chatbot/views.py; Celery task process_message in apps/chatbot/tasks.py
- [ ] T063 [US4] Notification tasks (vendor: new order; client: status change, payment result) wired via orders/payments services in apps/notifications/tasks.py
- [ ] T064 [US4] Grounding evaluation script with 50 EN/SW questions (SC-004, SC-006) in scripts/eval_chatbot.py (manual run with a real Gemini key)

**🛑 REVIEW & COMMIT — Delivery Phase 4** (+ live test with Meta test number via ngrok)

---

## Phase 7: User Story 5 — Earnings & administration (P3) — Delivery Phase 5

**Goal**: Vendors see earnings and balance. Admins manage commission and payouts.
**Independent Test**: quickstart scenario 7.

- [ ] T065 [P] [US5] Tests for /vendor/earnings/ summary, /vendor/payouts/, /admin/commission/, /admin/payouts/ (over-balance rejected), /admin/vendors/{id}/balance/ in tests/ledger/test_ledger_api.py
- [ ] T066 [US5] Ledger serializers, views, urls in apps/ledger/
- [ ] T067 [P] [US5] Ledger admin (earnings read-only, payouts, commission history) in apps/ledger/admin.py

## Phase 8: Polish & Cross-Cutting — Delivery Phase 5

- [ ] T068 [P] DRF throttling (anon/user, stricter on auth and webhooks) in config/settings/base.py with tests
- [ ] T069 [P] seed_demo management command (areas, vendors, Swahili/English items, packages) in apps/common/management/commands/seed_demo.py
- [ ] T070 [P] Structured logging (request id, payment/chat events) in config/settings/base.py
- [ ] T071 [P] Dockerfile + web/worker/beat services in docker-compose.yml
- [ ] T072 README.md with setup, env, architecture, and phase notes
- [ ] T073 Run full quickstart.md validation; generate OpenAPI file to docs/openapi.yaml

**🛑 REVIEW & COMMIT — Delivery Phase 5**

---

## Dependencies & Execution Order

- Setup (T001–T008) → Foundational (T009–T016) → all stories.
- US1 (T017–T027) and Events (T028–T029) → US2 (orders need items, vendors, events).
- US2 → US3 (payments need confirmed orders; ledger needs payments).
- US3 → US4 (chat booking reuses order + payment services) and US5 (ledger API).
- Polish after US5.
- Within a story: tests → models → services → views/endpoints → admin.

## Parallel Examples

- US1: T017, T018, T019 together; then T020 + T021 together.
- US3: T039–T043 together; T045 + T047 together.
- US4: T052–T056 together; T058 + T059 together.

## Implementation Strategy

- **MVP** = Delivery Phases 1–3 (accounts, catalog, booking, AzamPay + cash payment). This is enough
  for a web/mobile frontend to launch.
- Phase 4 adds the WhatsApp channel without changing the core logic. Phase 5 adds operations tooling.
- Stop at every 🛑 checkpoint; the owner reviews and commits; then continue.
