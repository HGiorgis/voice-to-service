# SMTP email on Render (verification codes)

Gmail and many consumer SMTP hosts often fail on platform hosts with **`Network is unreachable`**. Use a **transactional email provider** with a relay that allows cloud IPs.

## Free tier expectations

| Provider   | Typical free limit   | Notes                                      |
|-----------|----------------------|--------------------------------------------|
| **Brevo** | **~300 emails / day** | Long-running free plan; SMTP included      |
| SendGrid  | ~100 / day (check current pricing) | Works well from Render            |
| Mailjet   | ~200 / day           | SMTP available                             |

There is no mainstream **500/day forever free with no cap** product; **Brevo’s ~300/day** is the strongest common fit for OTP volume. Unused quota usually does not roll over; the limit resets daily.

---

## Step 1 — Create a Brevo account

1. Open [https://www.brevo.com](https://www.brevo.com) and sign up (free plan).
2. Complete email verification for your Brevo login.

---

## Step 2 — Add a sender you can use in “From”

1. In Brevo: **Settings → Senders & IP → Senders**.
2. Add and **verify** an email address (or domain) you will use as `DEFAULT_FROM_EMAIL`.
3. Until this is verified, messages may be blocked or delayed.

Use the **same** address in Render: `DEFAULT_FROM_EMAIL=Verified Name <you@yourdomain.com>`  
(or `you@yourdomain.com` if you keep the display name in `DEFAULT_FROM_NAME`).

---

## Step 3 — Create SMTP credentials (not the REST API key)

1. Go to **SMTP & API** → **SMTP** (or **Settings → SMTP & API → SMTP**).
2. Generate or copy:
   - **SMTP server**: `smtp-relay.brevo.com`
   - **Login** (sometimes shown as “Username”): often your Brevo account email or a dedicated SMTP login — use **exactly** what Brevo shows.
   - **SMTP key** (password): a long secret — **not** your Brevo login password.

---

## Step 4 — Map to Django / Render env vars

Set these in the Render dashboard (**Environment**) for your web service:

| Render key              | Value |
|-------------------------|--------|
| `EMAIL_BACKEND`         | `django.core.mail.backends.smtp.EmailBackend` |
| `EMAIL_HOST`            | `smtp-relay.brevo.com` |
| `EMAIL_PORT`            | `587` |
| `EMAIL_USE_TLS`         | `True` |
| `EMAIL_USE_SSL`         | `False` |
| `EMAIL_HOST_USER`       | *SMTP login from Brevo* |
| `EMAIL_HOST_PASSWORD`   | *SMTP key from Brevo* |
| `EMAIL_TIMEOUT`         | `15` |
| `DEFAULT_FROM_EMAIL`    | *Verified sender*, e.g. `noreply@yourdomain.com` |
| `DEFAULT_FROM_NAME`     | `Voice To Service` (optional) |
| `FRONTEND_URL`          | `https://your-app.onrender.com` (no trailing slash) |

**If port 587 fails** from Render, try **`EMAIL_PORT=2525`** (still with TLS as in our settings).

---

## Step 5 — Redeploy and test

1. Save env vars → **Manual Deploy** (or push) so the service restarts.
2. Register a test user or use **Resend code** on the verify page.
3. Watch Render **Logs**: you should **not** see `Network is unreachable` if SMTP is correct.
4. Check inbox and spam for the code.

---

## Step 6 — Brevo free plan caveats

- Daily cap (~300); OTP bursts are usually fine for small apps.
- Free campaigns may show **Brevo** branding on **marketing** emails; **transactional** templates are separate—check current Brevo policy for your template type.
- Keep `FRONTEND_URL` and links in emails on your real HTTPS host.

---

## Quick reference (copy-paste block)

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=your-smtp-login-from-brevo
EMAIL_HOST_PASSWORD=your-smtp-key-from-brevo
EMAIL_TIMEOUT=15
DEFAULT_FROM_EMAIL=noreply@your-verified-domain.com
DEFAULT_FROM_NAME=Voice To Service
FRONTEND_URL=https://your-app.onrender.com
```

---

## Still failing?

- Confirm **sender** is verified in Brevo.
- Try `EMAIL_PORT=2525`.
- Temporarily set `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend` and confirm the app runs; codes appear only in logs (debug only).
