# Research: Event Catering & Drinks Marketplace

All Technical Context items are resolved. External API details below MUST be re-checked against the
provider's current docs when the integration is implemented (Phases 3 and 4), because providers change
endpoints and versions.

## R1. Framework and API stack
- **Decision**: Django 5.2 LTS (or 6.x if all deps support it at scaffold time) + DRF + SimpleJWT
  + drf-spectacular + django-filter.
- **Rationale**: User-mandated Django/Postgres; DRF is the de-facto REST layer; spectacular gives
  OpenAPI for frontend teams (Constitution I).
- **Alternatives**: Django Ninja (less ecosystem for permissions/filters); session auth (bad for
  mobile clients).

## R2. Auth identifiers
- **Decision**: Custom `User(AbstractBaseUser)` with `phone` (E.164, unique, primary login) and
  optional unique `email`; login accepts either. JWT access 30 min / refresh 7 days with rotation.
- **Rationale**: In Tanzania phone is the main identity and matches WhatsApp numbers, so
  chat-created accounts and web accounts are the same user.
- **Alternatives**: email-only login (doesn't match WhatsApp users).

## R3. Online payments — AzamPay
- **Decision**: `AzamPayGateway` implementing `PaymentGateway`:
  - Token: `POST {AUTH_BASE}/AppRegistration/GenerateToken` with `appName`, `clientId`,
    `clientSecret` → bearer token (cached in Redis until expiry).
  - MNO checkout: `POST {CHECKOUT_BASE}/azampay/mno/checkout` with `accountNumber` (payer phone),
    `amount`, `currency: "TZS"`, `externalId` (our Payment UUID), `provider`
    (`Mpesa|Tigo|Airtel|Halopesa|Azampesa`), headers `Authorization: Bearer`, `X-API-Key`.
  - Bank checkout: `POST {CHECKOUT_BASE}/azampay/bank/checkout` (merchant account/mobile, OTP flow).
  - Callback: AzamPay POSTs to our registered callback URL with fields including `utilityref`
    (our externalId), `amount`, `transactionstatus` (`success`/`failure`), `reference`,
    `msisdn`, `operator`.
  - Sandbox bases: `https://authenticator-sandbox.azampay.co.tz`, `https://sandbox.azampay.co.tz`;
    configured by env.
- **Callback trust**: AzamPay callbacks are not HMAC-signed, so we (a) use an unguessable secret
  path segment `/api/v1/webhooks/azampay/<AZAMPAY_CALLBACK_TOKEN>/`, (b) match `utilityref` to an
  existing pending Payment and require amount equality, (c) optionally restrict source IPs in prod,
  (d) process idempotently under `select_for_update`.
- **Rationale**: Owner chose AzamPay; it covers all major Tanzanian mobile money operators.
- **Alternatives**: Selcom, Flutterwave. Both are possible later behind the same interface.

## R4. Cash payments and commission
- **Decision**: Cash payment = `Payment(method=cash, status=pending)` → confirmed by the order's
  vendor or admin → `success`. Ledger records `VendorEarning(channel=cash)`: the vendor already
  holds the gross, so the commission becomes a debit against their balance.
  Balance = Σ net(online) − Σ commission(cash) − Σ payouts. A balance may be negative.
- **Rationale**: Clarification session 2026-11-23.

## R5. LLM — Google Gemini
- **Decision**: `google-genai` SDK, model from env `GEMINI_MODEL` (default a current "flash" model,
  `gemini-3.8-flash`; 2.5 is closed to new projects, checked 2026-11-24), manual function-calling loop (max 5 tool rounds) so every tool call is
  logged and testable. Model default temperature.
- **Thought signatures**: Gemini 3 rejects function calls replayed without them or out of order, so each
  model message is stored whole and replayed unchanged.
- **Grounding**: The system prompt (bilingual) states that the assistant may only state items,
  prices, vendors and statuses returned by tools, and must say "not available" otherwise. Tools return
  compact JSON from services. Price strings are formatted by our code (`TZS 15,000`), not the model.
- **Language**: The model is instructed to reply in the user's language. `Conversation.language` is
  updated from the model's `detected_language` tool argument or a lightweight heuristic fallback
  (Swahili keyword list). This is used for templated fallback messages.
- **Alternatives**: Automatic function calling in the SDK (less control and harder to test); RAG over
  embeddings (unnecessary since the data is structured and queryable).

## R6. Messaging — Meta WhatsApp Cloud API
- **Decision**: Webhook `GET` verification (`hub.mode`, `hub.verify_token`, `hub.challenge`);
  `POST` verified with `X-Hub-Signature-256` HMAC-SHA256 of the raw body using the app secret.
  Store the inbound `wamid` with a unique constraint (dedupe retries), enqueue a Celery task, and return 200.
  Send via `POST https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages`.
- **Version**: `v26.0` (v21.0 is removed 2027-01-21). Not yet tried against the live API.
- **24-hour rule**: Free-form replies are only allowed within 24 h of the user's last message.
  Proactive vendor/client notifications (FR-027) use pre-approved **template messages**
  (names configured in env); free-form messages are used when inside the window.
- **Alternatives**: Twilio WhatsApp (paid); not chosen because the owner wants the free Meta API.

## R7. Async and scheduling
- **Decision**: Celery + Redis; django-celery-beat runs `expire_pending_orders` every 15 min
  (24 h rule) and `reconcile_pending_payments` (marks stale online payments for review after 30 min).
- **Tests**: `CELERY_TASK_ALWAYS_EAGER=True` in test settings.

## R8. Order state machine
- **Decision**: Plain transition table in `orders/services.py` (`ALLOWED = {from: {to: roles}}`),
  plus `transition(order, to, actor, note)` which validates, saves, and writes `OrderStatusChange`
  in one transaction. No FSM library is needed (Constitution VI).

## R9. IDs and references
- **Decision**: UUID primary keys; human order reference `EVT-YYMMDD-XXXX` (unique, used in
  chat and SMS) generated in service.

## R10. Testing external services
- **Decision**: respx for httpx (AzamPay, Graph API), `FakeLLM` scripted responses for Gemini,
  `MockGateway` selectable with `PAYMENT_GATEWAY=mock` for local dev without credentials.
