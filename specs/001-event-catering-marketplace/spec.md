# Feature Specification: Event Catering & Drinks Marketplace (Backend)

**Feature Branch**: `001-event-catering-marketplace`

**Created**: 2026-11-23

**Status**: Draft

**Input**: User description: "Food and drinks web app: people with any kind of event can request and
pay for catering for their events and can order drinks, both alcoholic and non-alcoholic. Different
vendors can register to offer their food and drink services and get their own accounts. A WhatsApp
AI chatbot lets users request services, learn prices and book through WhatsApp in English and
Swahili, answering from the app's food and drink data. Payment online through a payment gateway,
and cash (offline) payment is also allowed. Backend only."

## Clarifications

### Session 2026-11-23

- Q: How is commission collected on cash orders? → A: Recorded as owed by the vendor and
  netted against their next payout from online payments.
- Q: What is the default commission rate? → A: 10%, admin-configurable.
- Q: What happens if a vendor never responds to a new order? → A: Pending orders auto-expire
  (declined) after 24 hours and the client is notified.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Vendor registers and publishes a menu (Priority: P1)

A caterer or drinks supplier creates a vendor account, submits business details, and, once
approved by a platform admin, publishes food items, drink items (marked alcoholic or
non-alcoholic) and packages with prices, units and minimum quantities.

**Why this priority**: Without vendors and their offerings there is nothing to browse, book, or
ask the chatbot about.

**Independent Test**: Register a vendor, approve it as admin, add items, and confirm the items
appear in the public catalog; an unapproved vendor's items do not appear.

**Acceptance Scenarios**:

1. **Given** a new visitor, **When** they register as a vendor with business name, phone and
   service area, **Then** a vendor account is created with status "pending approval".
2. **Given** a pending vendor, **When** an admin approves it, **Then** the vendor's available
   items become visible in the public catalog.
3. **Given** an approved vendor, **When** they create, edit, mark unavailable, or delete their own
   item, **Then** the change is reflected in the catalog; they cannot modify another vendor's items.
4. **Given** a drink item, **When** the vendor saves it, **Then** it is classified as either
   alcoholic or non-alcoholic.

---

### User Story 2 - Client browses and books catering/drinks for an event (Priority: P1)

A client registers, describes their event (type such as wedding, birthday, corporate, funeral,
graduation or other; date; venue; guest count), browses food and drinks by type, vendor, and price,
and places an order with one vendor for that event.

**Why this priority**: This is the core marketplace transaction.

**Independent Test**: As a client, create an event, browse the catalog, place an order, and
see the order with a server-calculated total; the vendor sees the order and confirms it.

**Acceptance Scenarios**:

1. **Given** a registered client, **When** they create an event with a future date, **Then** the
   event is saved under their account.
2. **Given** a client browsing, **When** they filter by food/drink, alcoholic/non-alcoholic,
   vendor, or price range, or search by name, **Then** only matching available items from
   approved vendors are returned.
3. **Given** an event, **When** the client orders items from one vendor with quantities at or
   above each item's minimum, **Then** an order is created in "pending" status with the total
   calculated from current prices, and later price changes do not alter it.
4. **Given** an order containing alcoholic items, **When** the client has not confirmed they are
   18 or older, **Then** the order is rejected with a clear message.
5. **Given** a pending order, **When** the vendor accepts or declines it, **Then** the order moves
   to "confirmed" or "declined" and the client can see the new status.
6. **Given** a pending order, **When** the vendor has not responded within 24 hours, **Then** the
   order moves to "expired" and the client is notified.
7. **Given** a pending or confirmed but unpaid order, **When** the client cancels it, **Then** it
   moves to "cancelled".

---

### User Story 3 - Client pays online or chooses cash (Priority: P1)

For a confirmed order the client either pays online with mobile money or bank via the payment
gateway, or chooses cash, which the vendor or admin later confirms as received.

**Why this priority**: The platform earns its commission through payments, and vendors need
assurance they will be paid.

**Independent Test**: Pay one confirmed order online (simulated gateway success) and another by
cash (vendor confirms receipt); both orders become "paid" and vendor earnings are recorded with
commission deducted.

**Acceptance Scenarios**:

1. **Given** a confirmed order, **When** the client chooses online payment with a mobile money
   provider and phone number, **Then** a payment request is sent to their phone and the payment
   is "pending" until the gateway reports the outcome.
2. **Given** a pending online payment, **When** the gateway reports success, **Then** the payment
   becomes "successful", the order becomes "paid", and a vendor earning record (order amount minus
   platform commission) is created exactly once even if the gateway notifies more than once.
3. **Given** a pending online payment, **When** the gateway reports failure, **Then** the payment
   becomes "failed" and the client can retry.
4. **Given** a confirmed order, **When** the client chooses cash, **Then** the order becomes
   "awaiting cash payment"; **When** the vendor or an admin confirms receipt, **Then** the order
   becomes "paid", the confirming user and time are recorded, and a vendor earning is created.
5. **Given** a paid order, **When** the vendor marks it fulfilled and the event date has passed,
   **Then** the order can be marked "completed".

---

### User Story 4 - Client asks and books via WhatsApp in English or Swahili (Priority: P2)

A client messages the platform's WhatsApp number in English or Swahili to ask what food and
drinks are available, what they cost, and which vendors serve their area, then books and chooses a
payment method entirely in chat.

**Why this priority**: WhatsApp is the main channel many customers use; it widens reach, but the
web API flows (P1) must exist first.

**Independent Test**: Send sample WhatsApp messages ("Bei ya soda ni kiasi gani?", "Show me
wedding catering packages") and verify replies are in the same language and quote only prices
that exist in the catalog; complete a booking in chat and verify the order exists in the system.

**Acceptance Scenarios**:

1. **Given** catalog data, **When** a user asks about the price of an item in Swahili, **Then** the
   reply is in Swahili and states the exact price from the catalog.
2. **Given** a question about an item that does not exist, **When** the assistant replies,
   **Then** it says it is not available and suggests existing similar items; it never invents
   items or prices.
3. **Given** an unknown WhatsApp number, **When** the user wants to book, **Then** the assistant
   collects their name and creates a client account linked to that number.
4. **Given** the user provides event details and chosen items, **When** they confirm, **Then** an
   event and order are created with the same validation as the web flow (minimum quantities, 18+
   confirmation for alcohol), and the assistant replies with the order reference and total.
5. **Given** a confirmed order, **When** the user chooses mobile money, **Then** a payment request
   is pushed to their phone; **When** they choose cash, **Then** the order is marked
   awaiting cash payment.
6. **Given** an existing order, **When** the user asks about its status, **Then** the assistant
   reports the current status from the system.

---

### User Story 5 - Vendor earnings and platform administration (Priority: P3)

Vendors see their orders and earnings (gross, commission, net, paid out, balance). Admins
approve vendors, set the commission rate, see all orders and payments, and record payouts to
vendors.

**Why this priority**: Needed for operating the business, but bookings and payments can be
demonstrated before payout tooling exists.

**Independent Test**: After several paid orders, the vendor's earnings summary matches the sum of
paid orders minus commission; after an admin records a payout, the vendor's balance decreases.

**Acceptance Scenarios**:

1. **Given** paid orders, **When** a vendor views earnings, **Then** they see per-order gross,
   commission and net amounts and totals for only their own orders.
2. **Given** an admin, **When** they change the commission rate, **Then** only payments that
   succeed after the change use the new rate.
3. **Given** an outstanding vendor balance, **When** an admin records a payout with a reference,
   **Then** the vendor's available balance decreases by that amount; a payout greater than the
   balance is rejected.

### Edge Cases

- Ordering items from an unapproved or deactivated vendor, or items marked unavailable: rejected.
- Event date in the past, or sooner than the vendor's minimum notice period: order rejected.
- Quantity below an item's minimum order quantity: rejected with the minimum stated.
- Duplicate or out-of-order payment notifications from the gateway: processed once and do not
  regress a successful payment.
- Gateway unreachable when starting a payment: the client receives an error, the order stays
  payable, and the client may choose cash instead.
- A client tries to pay for an order that is not confirmed or is already paid: rejected.
- The WhatsApp message is not text (image or voice): the assistant replies that it currently
  understands text only.
- The AI service is unavailable or rate-limited: the user receives a short fallback message in
  their language and the message is not lost.
- A message mixes English and Swahili: reply in the dominant language.
- A vendor tries to confirm cash for another vendor's order: forbidden.

## Requirements *(mandatory)*

### Functional Requirements

**Accounts & roles**

- **FR-001**: System MUST support three roles: client, vendor, and admin.
- **FR-002**: Users MUST be able to register and sign in with phone number or email and password,
  and receive tokens for API access.
- **FR-003**: Vendor accounts MUST start in "pending" status and only become visible to clients
  after admin approval; admins MUST be able to suspend vendors.
- **FR-004**: Each user MUST have a preferred language (English or Swahili).

**Catalog**

- **FR-005**: Approved vendors MUST be able to create, update, deactivate and delete their own
  items, each with name, description, category, type (food or drink), alcoholic flag (drinks),
  unit (e.g. per plate, per crate, per bottle), unit price in TZS, minimum order quantity,
  availability and optional image.
- **FR-006**: Vendors MUST be able to define packages (named bundles with a fixed price per guest
  or per package) composed of their items.
- **FR-007**: Clients and anonymous visitors MUST be able to list, search and filter available items
  and packages from approved vendors by type, alcoholic flag, category, vendor, service area and
  price range.
- **FR-008**: Vendors MUST be able to state service areas and minimum notice (days before event).

**Events & orders**

- **FR-009**: Clients MUST be able to create, view, update and delete their events (type, title,
  date and time, venue/location, guest count, notes).
- **FR-010**: Clients MUST be able to place an order for an event containing items and/or
  packages from a single vendor; a client may place multiple orders (with different vendors) for
  one event.
- **FR-011**: The system MUST compute order totals from prices at the time of ordering and store
  those prices on the order.
- **FR-012**: Orders containing alcoholic items MUST require the client's confirmation that they
  are 18 or older.
- **FR-013**: Orders MUST follow the lifecycle: pending → confirmed, declined, or expired (no
  vendor response within 24 hours); confirmed →
  awaiting cash payment or paid; paid → fulfilled → completed; pending, confirmed or awaiting cash
  payment → cancelled. Invalid transitions MUST be rejected, and each transition MUST be logged
  with actor and time.
- **FR-014**: Vendors MUST see only orders placed with them; clients only their own orders.

**Payments & ledger**

- **FR-015**: Clients MUST be able to pay a confirmed order online through the payment gateway
  using mobile money (at minimum M-Pesa, Tigo Pesa/Mixx, Airtel Money, HaloPesa) or bank checkout.
- **FR-016**: The system MUST accept and verify payment outcome notifications from the gateway and
  process each payment's success at most once.
- **FR-017**: Clients MUST be able to choose cash payment; only the order's vendor or an admin may
  confirm cash receipt.
- **FR-018**: On successful payment (online or cash), the system MUST record a vendor earning with
  gross amount, commission rate, commission amount and net amount.
- **FR-019**: Admins MUST be able to set the platform commission rate (default 10%).
- **FR-020**: Admins MUST be able to record payouts to vendors; vendors MUST be able to view
  earnings, payouts and outstanding balance. Vendor balance = net earnings from online payments
  − commission owed on cash orders − payouts already made.
- **FR-021**: Admins MUST be able to mark a paid order as refunded (refund performed outside the
  system), which reverses the corresponding vendor earning.

**WhatsApp assistant**

- **FR-022**: The system MUST receive WhatsApp text messages from users and reply via WhatsApp.
- **FR-023**: The assistant MUST understand and reply in English and Swahili, matching the user's
  language.
- **FR-024**: The assistant MUST answer questions about items, packages, prices, vendors,
  service areas and order status using only data from the system; it MUST NOT state prices or
  items that are not in the system.
- **FR-025**: The assistant MUST be able to create a client account for an unknown WhatsApp
  number, create an event and an order, and start online or cash payment, applying all the same
  business rules as the API.
- **FR-026**: The system MUST store conversation history per WhatsApp user so that follow-up
  messages keep context.
- **FR-027**: The system MUST notify a vendor by WhatsApp when a new order is placed with them,
  and notify a client when their order status changes.

**Platform**

- **FR-028**: All functionality MUST be accessible through a documented API for separate web
  and mobile frontends.

### Key Entities

- **User**: A person who signs in; has role (client/vendor/admin), name, phone, email,
  preferred language.
- **Vendor Profile**: A vendor's business: name, description, contact, service areas, minimum
  notice, approval status, payout details (mobile money number or bank account).
- **Category**: A grouping of items (e.g. Main dishes, Soft drinks, Beer, Wine, Spirits).
- **Item**: Something a vendor sells: food or drink, alcoholic flag, unit, unit price, minimum
  quantity, availability.
- **Package**: A vendor's named bundle of items with a set price per guest or per package.
- **Event**: A client's occasion: type, date, venue, guest count.
- **Order / Order Line**: A client's request to one vendor for one event; lines hold item or
  package, quantity, and price snapshot; order holds status, total, age confirmation.
- **Order Status Change**: Audit record of each transition with actor and time.
- **Payment**: An attempt to pay an order: method (online/cash), provider, amount, status,
  gateway reference, confirming user (cash).
- **Commission Setting**: The current platform commission rate and its history.
- **Vendor Earning**: Ledger entry per paid order: gross, commission, net.
- **Payout**: Money sent to a vendor, recorded by an admin with reference.
- **Conversation / Chat Message**: WhatsApp thread per phone number with message history,
  detected language, and linked user.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new vendor can register and publish their first item in under 10 minutes
  (excluding admin approval wait).
- **SC-002**: A client can create an event and place an order in under 5 minutes.
- **SC-003**: 100% of successful payments produce exactly one vendor earning record, including when
  payment notifications are duplicated.
- **SC-004**: 100% of prices quoted by the WhatsApp assistant in a test set of 50 questions (25
  English, 25 Swahili) match the catalog, with zero invented items.
- **SC-005**: The WhatsApp assistant replies to 95% of messages within 10 seconds.
- **SC-006**: 95% of WhatsApp replies are in the same language as the user's message.
- **SC-007**: A client can complete a booking entirely in WhatsApp in under 10 message exchanges.
- **SC-008**: Vendor earnings summaries match the sum of their paid orders minus commission with
  zero discrepancy.

## Assumptions

- Primary market is Tanzania; currency is TZS, timezone East Africa Time, and online payment uses
  AzamPay (mobile money and bank), chosen by the project owner.
- The platform collects online payments and pays vendors after deducting a configurable
  commission (default 10%); cash is paid to the vendor directly, and the commission on cash
  orders is recorded as owed by the vendor (netted against future payouts). A vendor balance may
  therefore be negative.
- An order belongs to exactly one vendor; multi-vendor events use multiple orders (no shared cart).
- Delivery and logistics are arranged between vendor and client; delivery fees, if any, are built
  into items or packages in v1.
- Refunds are performed manually outside the system; the system only records them.
- Age verification is a self-declaration (18+), not ID verification.
- The WhatsApp assistant handles text messages only in v1; voice and images are out of scope.
- Free tiers of the WhatsApp Cloud API and Google Gemini API are sufficient for launch volume.
- Frontend (web/mobile) and push notifications are out of scope; this feature is backend only.
- Vendor notifications use WhatsApp; email notifications are optional.
