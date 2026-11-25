# Feature Specification: Account recovery and claim

**Created**: 2026-11-25 | **Status**: Implemented

## User stories
1. **Forgotten password (P1)**: a client or vendor asks for a code, receives it on WhatsApp and sets
   a new password.
2. **Claim (P1)**: a client created by the WhatsApp assistant, who has no password, does the same and
   can then sign in to web and mobile.

## Requirements
- **FR-101**: Codes MUST be sent only to the account's phone, even when the login is an email.
- **FR-102**: Answers MUST NOT reveal whether an account exists.
- **FR-103**: Only active clients and vendors may use codes; operators may not.
- **FR-104**: A code has 6 digits, lasts 10 minutes, works once, allows 5 wrong attempts and is
  cancelled by a newer one. It is stored only as a keyed hash and never logged, queued or added to
  the chat history.
- **FR-105**: Code requests and attempts MUST be limited per account and per address.
- **FR-106**: Setting a password MUST end every other session.

## Out of scope
Changing a password while signed in, phone verification at registration, SMS or email fallback.
