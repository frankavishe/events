# Data Model: Event Catering & Drinks Marketplace

Conventions: all models inherit `common.BaseModel` (`id` UUID pk, `created_at`, `updated_at`).
Money = `Decimal(12,2)` TZS. Phone numbers are stored in E.164 format (`+2557XXXXXXXX`).

## accounts

### User
| Field | Type | Rules |
|-------|------|-------|
| phone | str(16) | unique, required, E.164; USERNAME_FIELD |
| email | email | unique, nullable |
| full_name | str(150) | required |
| role | enum `client` \| `vendor` \| `admin` | default client |
| preferred_language | enum `en` \| `sw` | default `en` |
| is_active, is_staff | bool | |
| created_via | enum `api` \| `whatsapp` | default api |

WhatsApp-created users have an unusable password until they set one.

## vendors

### VendorProfile (1:1 User where role=vendor)
| Field | Type | Rules |
|-------|------|-------|
| user | OneToOne User | |
| business_name | str(150) | required |
| description | text | |
| contact_phone | str(16) | |
| status | enum `pending` \| `approved` \| `suspended` \| `rejected` | default pending |
| approved_by / approved_at | FK User / datetime | set on approve |
| min_notice_days | int ≥ 0 | default 2 |
| offers_food, offers_drinks | bool | at least one true |
| payout_method | enum `mobile_money` \| `bank` | |
| payout_account_name, payout_account_number, payout_provider | str | |

### ServiceArea
`name` (e.g. "Dar es Salaam – Kinondoni"), unique. VendorProfile M2M ServiceArea.

## catalog

### Category
`name_en`, `name_sw`, `kind` (`food`|`drink`), `slug` unique.

### Item
| Field | Type | Rules |
|-------|------|-------|
| vendor | FK VendorProfile | |
| category | FK Category | category.kind must equal item.kind |
| name, description | str/text | |
| kind | enum `food` \| `drink` | |
| is_alcoholic | bool | must be false when kind=food |
| unit | enum `plate` \| `person` \| `piece` \| `bottle` \| `crate` \| `litre` \| `kg` \| `tray` | |
| unit_price | Decimal | > 0 |
| min_quantity | int | ≥ 1, default 1 |
| is_available | bool | default true |
| image | image | optional |

Index: (vendor, is_available), (kind, is_alcoholic), GIN trigram on name (optional, Phase 5).

### Package
`vendor`, `name`, `description`, `pricing` (`per_guest`|`flat`), `price` (>0), `min_guests` (≥1),
`is_available`; `contains_alcohol` is derived from its items.

### PackageItem
`package` FK, `item` FK (same vendor), `quantity_note` str (e.g. "1 plate per guest").

Visibility rule: public queries only return items and packages where `is_available` is true and the
vendor's status is `approved`.

## events

### Event
`client` FK User, `event_type` enum (`wedding`, `birthday`, `corporate`, `funeral`, `graduation`,
`religious`, `other`), `title`, `starts_at` datetime (must be in the future on create), `venue`,
`service_area` FK nullable, `guest_count` int ≥ 1, `notes`.

## orders

### Order
| Field | Type | Rules |
|-------|------|-------|
| reference | str unique | `EVT-YYMMDD-XXXX` |
| event | FK Event nullable | event.client == client; null only if the event of a cancelled/declined/expired order was deleted |
| client | FK User | |
| vendor | FK VendorProfile | approved |
| status | enum (see state machine) | default pending |
| subtotal, total | Decimal | computed by server |
| contains_alcohol | bool | derived |
| age_confirmed | bool | required true if contains_alcohol |
| channel | enum `api` \| `whatsapp` | |
| expires_at | datetime | created_at + 24 h |
| notes | text | |

### OrderLine
`order` FK, exactly one of `item` FK / `package` FK (set null if the vendor later deletes it; snapshots remain), `name_snapshot`, `unit_snapshot`,
`unit_price_snapshot`, `quantity` (≥ item.min_quantity; for per-guest packages it is the guest count ≥ min_guests),
`line_total` = price × quantity.

### OrderStatusChange
`order` FK, `from_status`, `to_status`, `actor` FK User nullable (null = system), `note`, `created_at`.

### State machine
| From | To | Who |
|------|----|-----|
| pending | confirmed, declined | vendor (owner), admin |
| pending | expired | system (24 h) |
| pending, confirmed, awaiting_cash | cancelled | client (owner), admin |
| confirmed | awaiting_cash | client (chooses cash) |
| confirmed, awaiting_cash | paid | system (online success) / vendor or admin (cash confirm) |
| paid | fulfilled | vendor, admin |
| fulfilled | completed | vendor, admin, system (event date passed) |
| paid, fulfilled, completed | refunded | admin |

## payments

### Payment
| Field | Type | Rules |
|-------|------|-------|
| order | FK Order | |
| method | enum `online` \| `cash` | |
| provider | enum `mpesa` \| `tigo` \| `airtel` \| `halopesa` \| `azampesa` \| `bank` \| `cash` | |
| payer_phone | str | required for mobile money |
| amount | Decimal | = order.total |
| status | enum `pending` \| `success` \| `failed` \| `cancelled` | |
| gateway_reference | str | unique nullable |
| raw_callback | JSON | last callback payload |
| confirmed_by | FK User nullable | cash only |
| completed_at | datetime | |
| bank_name | enum `CRDB` \| `NMB` | bank only; account number and OTP are never stored |
| needs_review, review_reason | bool, enum `amount_mismatch` \| `order_not_payable` \| `duplicate_reference` \| `no_callback` | for operators |

Constraints: at most one `success` payment per order (partial unique index on `order` where
`status='success'`), and one `pending` payment per order and method.

A reported success that cannot be applied (wrong amount, order not payable, reused reference) is
stored as `failed` with `needs_review`, so every `success` payment has exactly one earning.

## ledger

### CommissionSetting
`rate` Decimal(5,4) (0.1000 = 10%), `effective_from` datetime, `set_by` FK User. The current rate is
the latest row with `effective_from <= now`. A data migration seeds 0.1000.

### VendorEarning (1:1 Order)
`vendor`, `order` OneToOne, `payment` FK, `channel` (`online`|`cash`), `gross`, `commission_rate`,
`commission_amount` (rounded half-up to 2 dp), `net` = gross − commission, `reversed` bool
(set on refund).

### Payout
`vendor`, `amount` > 0, `method`, `reference` (external transfer id), `paid_at`, `recorded_by` FK
admin, `note`.

Balance (computed, not stored): Σ net (online, not reversed) − Σ commission (cash, not reversed)
− Σ payouts. A payout is rejected if amount > balance.

## chatbot

### Conversation
`wa_id` (WhatsApp phone) unique, `user` FK nullable, `language` (`en`|`sw`),
`last_inbound_at` (for 24 h window), `state` JSON (draft booking: event details, selected lines).

### ChatMessage
`conversation` FK, `direction` (`in`|`out`), `wa_message_id` unique nullable (dedupe),
`text`, `role` (`user`|`model`|`tool`), `tool_name`, `payload` JSON, `status`
(`received`|`processed`|`failed`|`sent`).
History sent to the LLM = last 20 messages.
