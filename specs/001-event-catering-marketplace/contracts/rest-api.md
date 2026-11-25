# REST API Contract (v1)

Base path `/api/v1/`. JSON. Auth: `Authorization: Bearer <access>` unless marked **public**.
Errors: `{"detail": "...", "code": "...", "errors": {field: [msg]}}`. Pagination:
`?page=&page_size=` → `{count, next, previous, results}`. Money fields are decimal strings (`"15000.00"`).
The generated OpenAPI (`/api/schema/`, Swagger `/api/docs/`) becomes the source of truth once
implemented.

## Auth & accounts
| Method | Path | Who | Notes |
|--------|------|-----|-------|
| POST | `/auth/register/` | public | `{full_name, phone, email?, password, preferred_language?}` → client user + tokens |
| POST | `/auth/register/vendor/` | public | user fields + `{business_name, description, offers_food, offers_drinks, service_area_ids, min_notice_days}` → vendor (status pending) + tokens |
| POST | `/auth/token/` | public | `{login (phone or email), password}` → `{access, refresh}` |
| POST | `/auth/token/refresh/` | public | 401 after a password change |
| POST | `/auth/password/code/` | public | `{login}` → always 202 `{detail}`; sends a WhatsApp code to an active client's or vendor's phone |
| POST | `/auth/password/` | public | `{login, code, password}` → `{access, refresh}`, other sessions end; 400 `invalid_code` (one answer for every reason). See `specs/002-account-recovery/` |
| GET/PATCH | `/me/` | any | own profile (name, email, preferred_language) |

## Vendors
| Method | Path | Who | Notes |
|--------|------|-----|-------|
| GET | `/vendors/` | public | approved only; filter `service_area`, `offers_food`, `offers_drinks`, `search` |
| GET | `/vendors/{id}/` | public | |
| GET/PATCH | `/vendor/profile/` | vendor | own profile incl. payout details |
| GET | `/service-areas/` | public | |
| POST | `/admin/vendors/{id}/approve/` \| `/reject/` \| `/suspend/` | admin | |

## Catalog
| Method | Path | Who | Notes |
|--------|------|-----|-------|
| GET | `/categories/` | public | |
| GET | `/items/` | public | filters: `kind`, `is_alcoholic`, `category`, `vendor`, `service_area`, `min_price`, `max_price`, `search`, `ordering=unit_price` |
| GET | `/items/{id}/` | public | |
| GET | `/packages/` , `/packages/{id}/` | public | same filters where applicable |
| GET/POST | `/vendor/items/` | approved vendor | own items |
| GET/PATCH/DELETE | `/vendor/items/{id}/` | vendor owner | 404 for other vendors' items |
| GET/POST, GET/PATCH/DELETE | `/vendor/packages/`, `/vendor/packages/{id}/` | vendor owner | `items: [{item_id, quantity_note}]` |

## Events
| Method | Path | Who |
|--------|------|-----|
| GET/POST | `/events/` | client (own) |
| GET/PATCH/DELETE | `/events/{id}/` | client owner; delete and changing `starts_at` blocked (409) unless all its orders are cancelled, declined or expired |

## Orders
| Method | Path | Who | Notes |
|--------|------|-----|-------|
| POST | `/orders/` | client | `{event_id, vendor_id, lines: [{item_id?, package_id?, quantity}], age_confirmed?, notes?}` → 201 order with computed totals |
| GET | `/orders/` | client: own; vendor: theirs; admin: all | filter `status`, `event` |
| GET | `/orders/{id}/` | scoped | includes lines, payments, status history |
| POST | `/orders/{id}/confirm/` \| `/decline/` | vendor owner, admin | decline takes `{reason}` |
| POST | `/orders/{id}/cancel/` | client owner, admin | |
| POST | `/orders/{id}/fulfil/` \| `/complete/` | vendor owner, admin | |
| POST | `/orders/{id}/refund/` | admin | `{note}` |

## Payments
| Method | Path | Who | Notes |
|--------|------|-----|-------|
| POST | `/orders/{id}/pay/` | client owner | `{method: "online", provider: "mpesa"\|"tigo"\|"airtel"\|"halopesa"\|"azampesa", phone}` or `{method:"online", provider:"bank", bank_name:"CRDB"\|"NMB", account_number, phone, otp}` → 202 `{payment_id, status:"pending", order_status}`; or `{method:"cash"}` → 200, order `awaiting_cash`. 409 `payment_in_progress` while an online payment is pending (< 30 min). OTP and account number are never stored |
| POST | `/orders/{id}/confirm-cash/` | vendor owner, admin | → order `paid`, earning created |
| GET | `/payments/{id}/` | scoped | poll status |

## Ledger
| Method | Path | Who |
|--------|------|-----|
| GET | `/vendor/earnings/` | vendor | list + `summary {gross, commission, net_online, commission_owed_cash, payouts, balance}` |
| GET | `/vendor/payouts/` | vendor |
| GET/POST | `/admin/commission/` | admin | current rate + history; POST `{rate}` |
| GET/POST | `/admin/payouts/` | admin | POST `{vendor_id, amount, method, reference, note}`; over balance → 400; same vendor, method and reference again → 409 `duplicate_payout` |
| GET | `/admin/vendors/{id}/balance/` | admin |

Status codes: 201 create, 202 async payment start, 400 validation, 401 unauthenticated,
403 wrong role, 404 not in scope, 409 invalid state transition, 429 too many requests (`throttled`,
with `Retry-After`), 502 gateway error. Valid webhooks are never limited. Every response has `X-Request-ID`.
