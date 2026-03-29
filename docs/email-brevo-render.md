# Transactional email on Render (Brevo API)

Hosted platforms often block or flake on **SMTP** (ports 25 / 587 / 465). This project sends mail through **Brevo’s HTTPS API** (`api.brevo.com`, port **443** only).

## 1. Brevo account and sender

1. Create or open a [Brevo](https://www.brevo.com/) account.
2. Verify your **sender domain** or at least the address you use as `DEFAULT_FROM_EMAIL` (Brevo → **Senders & IPs**).

## 2. API key

1. Brevo → **SMTP & API** → **API keys** → create a **v3** key.
2. Copy the key once; store it only in environment variables (never commit it).

## 3. Environment variables (local `.env` and Render)

| Variable | Required | Notes |
|----------|----------|--------|
| `BREVO_API_KEY` | Yes (production) | Enables `BrevoApiEmailBackend`. |
| `DEFAULT_FROM_EMAIL` | Yes | Must match a **verified sender** in Brevo. |
| `DEFAULT_FROM_NAME` | Optional | Shown as the inbox “From” name. |
| `EMAIL_TIMEOUT` | Optional | HTTP timeout for Brevo calls (default `15` seconds). |
| `FRONTEND_URL` | Yes | Base URL for links in verification emails (no trailing slash). |

**Remove from Render / `.env` if you were using SMTP before:**  
`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`.  
They are no longer read by this app.

**Do not set** `EMAIL_BACKEND` to the SMTP backend unless you maintain a custom setup; the default is Brevo API when `BREVO_API_KEY` is set.

## 4. Check configuration

From the project root (Render Shell or local):

```bash
python manage.py email_config_check
python manage.py email_config_check --connection-test
```

`--connection-test` calls Brevo `GET /v3/account` (no email sent).

## 5. Troubleshooting

- **401 / 403 on `--connection-test`:** wrong or revoked API key.
- **Send succeeds but mail bounces or is blocked:** verify `DEFAULT_FROM_EMAIL` in Brevo and DNS (SPF/DKIM) if using your domain.
- **Console backend locally:** leave `BREVO_API_KEY` unset to print emails to the terminal; or set the key to send real mail.
