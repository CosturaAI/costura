# Slack-compatible webhook receiver

A receiver for Costura's signal webhook in 40 lines of Python, standard library only. It
checks `X-Costura-Signature` with the organization's signing secret and prints each signal's
`text`. The headers, the signature and the retry schedule are in
[docs/operations/webhooks.md](../../docs/operations/webhooks.md).

## Run

```sh
COSTURA_WEBHOOK_SECRET=<the signing secret shown once on save> \
  python3 -I examples/slack-webhook-receiver/receiver.py 8089
```

The receiver listens on plain HTTP on port 8089 (or the port given). A post with a wrong
signature, or a timestamp more than 300 seconds off, answers 401.

Try it without Costura, with a signed sample:

```sh
body='{"text":"*Anomaly* (anthropic) sample"}'
ts=$(date +%s)
sig=$(printf '%s.%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$COSTURA_WEBHOOK_SECRET" | sed 's/.* //')
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8089/ \
  -H 'Content-Type: application/json' -H "X-Costura-Timestamp: $ts" \
  -H "X-Costura-Signature: v1=$sig" -H 'X-Costura-Delivery: sample' -d "$body"
```

## Point Costura at it

`check_url` in `apps/api/costura/delivery.py` accepts only an `https://` URL on port 443 (or
no port) whose host is on `COSTURA_WEBHOOK_HOSTS`, and the worker does not follow redirects.
A plain-HTTP receiver therefore sits behind a TLS terminator on 443 that the worker container
can reach by name, for example a Caddy or nginx host `hooks.example.com` with a certificate
the worker trusts, forwarding to this process on 8089. Costura does not provide that
terminator. Then, in the production `.env`:

```sh
COSTURA_WEBHOOK_HOSTS=hooks.example.com
```

Restart the API and the worker (`docker compose -f docker-compose.prod.yml up -d api worker`),
open Settings, Anomalies as an owner, save `https://hooks.example.com/costura`, copy the
signing secret into `COSTURA_WEBHOOK_SECRET` of the receiver, and press Send a test message.
The receiver prints `delivery test: Costura test message: ...`. Every new signal follows,
once each, with the row id as `X-Costura-Delivery`; the Deliveries list on the same card shows
the outcome and lets an owner resend a row.

For a local trial without a certificate authority, run the terminator with a self-signed
certificate and add its CA to the worker image's trust store; the worker uses the system
store through `httpx`. Local trials cannot use `http://`: the API refuses the URL.
