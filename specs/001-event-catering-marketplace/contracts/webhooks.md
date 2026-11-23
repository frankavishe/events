# Inbound Webhooks & AI Tool Contracts

## WhatsApp (Meta Cloud API)

`GET /api/v1/webhooks/whatsapp/?hub.mode=subscribe&hub.verify_token=X&hub.challenge=Y`
→ 200 with body `Y` if the token equals `WHATSAPP_VERIFY_TOKEN`, else 403.

`POST /api/v1/webhooks/whatsapp/`
- Header `X-Hub-Signature-256: sha256=<hex HMAC-SHA256(raw_body, WHATSAPP_APP_SECRET)>`; mismatch → 403.
- Body: `entry[].changes[].value.messages[]` with `from`, `id` (wamid), `type`, `text.body`;
  `value.contacts[].profile.name`; `value.statuses[]` (delivery receipts, stored and ignored).
- Behaviour: for each message, insert `ChatMessage` (unique `wa_message_id`; duplicates skipped),
  enqueue `chatbot.process_message`, return 200 within 1 s. Non-text → canned "text only" reply.

## AzamPay callback

`POST /api/v1/webhooks/azampay/<AZAMPAY_CALLBACK_TOKEN>/` (wrong token → 404)
```json
{"msisdn":"2557...","amount":"15000","message":"...","utilityref":"<payment uuid>",
 "operator":"Mpesa","reference":"<azampay ref>","transactionstatus":"success",
 "submerchantAcc":null,"fspReferenceId":"..."}
```
- Lookup Payment by `utilityref`; unknown → 200 + log (avoid gateway retries storm).
- Amount mismatch → mark payment `failed`, flag for review, 200.
- `success` and payment pending → payment success, order `paid`, VendorEarning, notify. Already
  success → no-op (idempotent). `failure` → payment failed (never downgrades a success).

## Gemini tools (function declarations)

All tools call service functions; outputs are compact JSON; prices formatted `"TZS 15,000"`.

| Tool | Args | Returns |
|------|------|---------|
| `search_catalog` | `query?`, `kind? (food\|drink)`, `alcoholic? bool`, `service_area?`, `max_price?`, `limit≤10` | items + packages `[ {id, type, name, vendor, unit, price, min_quantity, alcoholic} ]` |
| `get_item_details` | `item_id` or `package_id` | full detail incl. vendor, availability |
| `list_vendors` | `service_area?`, `offers? (food\|drinks)` | `[ {id, name, areas, min_notice_days} ]` |
| `list_service_areas` | – | names |
| `register_client` | `full_name`, `preferred_language` | user id (phone = sender, implicit) |
| `create_event` | `event_type`, `title`, `starts_at` (ISO), `venue`, `guest_count`, `service_area?` | event id |
| `create_order` | `event_id`, `vendor_id`, `lines[{item_id?/package_id?, quantity}]`, `age_confirmed` | `{reference, total, status}` or validation error message |
| `start_payment` | `order_reference`, `method (mobile_money\|cash)`, `provider?`, `phone?` | status text |
| `get_order_status` | `order_reference?` (default: latest orders of sender) | `[ {reference, status, total, vendor, event_date} ]` |
| `cancel_order` | `order_reference` | new status |

The sender's identity is injected server-side; tools never accept a user id from the model, and order
tools only see the sender's own orders.
