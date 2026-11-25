# WhatsApp webhook setup (Meta Cloud API)

How to connect a Meta app to this backend so that the assistant receives and answers messages.
What the endpoint does is specified in `specs/001-event-catering-marketplace/contracts/webhooks.md`.

Endpoint: `https://<your-domain>/api/v1/webhooks/whatsapp/` (keep the final slash)

## 1. Before you start

- A Meta business portfolio, and a Meta app with WhatsApp added.
- A business phone number registered for the Cloud API.
- A public HTTPS address with a valid certificate. Meta does not accept self-signed ones.
- A reverse proxy that allows 3 MB request bodies and keeps the `X-Hub-Signature-256` header.
  nginx allows 1 MB by default: set `client_max_body_size 3m;`.

## 2. Collect the values

| Variable | Where it comes from |
|----------|---------------------|
| `WHATSAPP_PHONE_NUMBER_ID` | App Dashboard > WhatsApp > API Setup. The ID, not the phone number |
| `WHATSAPP_APP_SECRET` | App Dashboard > App settings > Basic > App secret |
| `WHATSAPP_VERIFY_TOKEN` | You choose it; see below |
| `WHATSAPP_ACCESS_TOKEN` | A system user token; see below |
| `WHATSAPP_GRAPH_VERSION` | Leave the default in `.env.example` unless you are upgrading |

Also note the ID of the WhatsApp account (WABA) shown on the API Setup page, for step 6.

**Verify token:** any long random text. It is used only for the handshake in step 4.

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Access token:** in Business settings > System users:

1. Add a system user. Select it and choose **Assign assets**.
2. Select the app and grant **Manage app**.
3. Give the system user access to both the WhatsApp account and the Messaging account (Business
   settings > Accounts > select the account > People). Access to only one is not enough.
4. Choose **Generate token**, select the app and an expiration, and grant:
   - `whatsapp_business_messaging`: messages
   - `whatsapp_business_management`: the WhatsApp account, templates and step 6
5. Copy the token when it appears.

If the token expires, replies and notifications stop until it is replaced. The temporary token on the
API Setup page is only for trials.

## 3. Configure and start the backend

The web process, the Celery worker and beat need the same values:

```dotenv
DJANGO_ALLOWED_HOSTS=<your-domain>
MESSAGING_PROVIDER=whatsapp
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_APP_SECRET=
LLM_PROVIDER=gemini
GEMINI_API_KEY=
```

Never commit these values. Restart all three processes after changing them.

With `config.settings.prod`, the app does not start if a WhatsApp credential is missing. It also needs
`WHATSAPP_TEMPLATE_AUTH_CODE` and other settings: see "Production notes" in `README.md`.

## 4. Register the callback URL

The backend must be running, because Meta calls it when you save.

1. Open App Dashboard > WhatsApp > Configuration. If the app was created with the "Connect with
   customers through WhatsApp" use case, open Use cases > Customize > Configuration instead.
2. **Callback URL:** the endpoint above.
3. **Verify token:** the value of `WHATSAPP_VERIFY_TOKEN`.
4. Save.

To check the handshake yourself:

```powershell
curl.exe "https://<your-domain>/api/v1/webhooks/whatsapp/?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=12345"
```

Expected: status 200 and the body `12345`. A wrong token gives 403, and repeated failures give 429.

## 5. Subscribe to `messages`

In the same panel, subscribe to the **messages** field. It carries incoming messages and delivery
statuses. The backend ignores every other field, so no other subscription is needed.

## 6. Subscribe the app to the WhatsApp account

The app must also be subscribed to the WABA. The dashboard often does this; check it:

```powershell
$headers = @{ Authorization = "Bearer <access token>" }
$url = "https://graph.facebook.com/v26.0/<WABA ID>/subscribed_apps"
(Invoke-RestMethod $url -Headers $headers).data
Invoke-RestMethod $url -Headers $headers -Method Post   # only if your app is not listed
```

## 7. Go live

Switch the app to **Live** mode. In Dev mode some webhooks are not sent.

## 8. Test

1. Send a WhatsApp text to the business number from a personal phone.
2. The log shows `POST api/v1/webhooks/whatsapp/ 200`.
3. In `/admin/`, under Chatbot, the message and its conversation appear.
4. The assistant replies. The message becomes `processed` and the reply `sent`; its delivery status
   then changes to, for example, `delivered`.
5. Send an image: the reply says that only text is understood.

The **Test** button in the dashboard sends a sample with a made-up phone number ID. The backend answers
200 and logs `other phone number`. This proves that the signature is accepted, but nothing is stored.

### From a local machine

Use an HTTPS tunnel to port 8000 (for example `cloudflared tunnel --url http://localhost:8000`), add its
hostname to `DJANGO_ALLOWED_HOSTS`, and register its URL as in step 4. Use a separate Meta app with a
test number: changing the callback URL of the live app stops production messages. With
`LLM_PROVIDER=fake` the assistant sends a fixed placeholder answer.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Meta cannot verify the URL; 403 | `WHATSAPP_VERIFY_TOKEN` differs or is empty, or the app was not restarted |
| Meta cannot verify the URL; 400 | The domain is not in `DJANGO_ALLOWED_HOSTS` |
| 301 | The URL is not HTTPS, has no final slash, or the proxy does not set `X-Forwarded-Proto: https` |
| Every POST gives 403 | `WHATSAPP_APP_SECRET` is from another app, or the proxy changes the body or drops the signature |
| POST gives 413 or 400 | The proxy's body limit, or the host again |
| 429 | Too many rejected calls. Fix the cause of the 403; correctly signed calls are never limited |
| No requests arrive | Check steps 5 to 7, and that the proxy or firewall lets Meta in |
| Log: `other phone number` | Dashboard sample, or a wrong `WHATSAPP_PHONE_NUMBER_ID` |
| Log: `not about messages` | Another field is subscribed. Harmless |
| Message stays `received` | The Celery worker is not running, or cannot reach Redis |
| Log: `WhatsApp send returned HTTP 401` | The access token expired or was revoked |
| Other `WhatsApp send returned HTTP 4xx` | Missing permission or asset access, wrong phone number ID, or outside the 24 h window |
| User can browse but not book | Their phone is hidden, so Meta sends only a business-scoped ID |

If the endpoint does not answer 200, Meta retries for up to 7 days, so messages may arrive late. Duplicates
are skipped.

If you restrict addresses at the firewall, note that Meta's change. Meta recommends mutual TLS instead.

## Rotating secrets

- **Access token:** generate a new one, replace it, restart, then revoke the old one.
- **App secret:** reset it, then replace it and restart at once. Until then calls get 403, which Meta
  retries.
- **Verify token:** replace it, restart, then save it again in the Configuration panel.

## Meta's documentation

- [Webhooks overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview)
- [Create a webhook endpoint](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/create-webhook-endpoint)
- [Access tokens](https://developers.facebook.com/documentation/business-messaging/whatsapp/access-tokens)
