# Implementation Plan: Account recovery and claim

- `accounts.PasswordCode`: one row per user, replaced by each new code. Checked under a row lock.
- The code is generated in `notifications.tasks.send_password_code`; the queue carries the user id.
- `MessagingClient.send_auth_code` sends Meta's copy-code authentication template.
- SimpleJWT `CHECK_REVOKE_TOKEN` ties tokens to the password; the refresh serializer checks it too.
- Accepted: tokens from before deployment stop working once; someone who knows a phone number can
  use up its hourly codes.

## Constitution check
I API only, in OpenAPI: pass. II tests first, no network: pass. III no money: n/a. IV the assistant
only points to the app: pass. V no secret stored, explicit permissions: pass. VI no new dependency,
logic in services: pass.
