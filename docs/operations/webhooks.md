# Webhooks

Each organization can post its signals (anomalies, budget alerts, key gaps) to one
Slack-compatible incoming webhook. This page states what the code does today, with the
file that does it. Egress is off until the operator lists hosts in
`COSTURA_WEBHOOK_HOSTS` ([configuration](configuration.md)).

## Destination rules

An owner saves the URL in Settings, Anomalies (`PUT /orgs/{org}/webhook`). The API checks it
in `check_url` (`apps/api/costura/delivery.py`):

| Rule                                          | Answer when broken                                    |
| --------------------------------------------- | ----------------------------------------------------- |
| `COSTURA_WEBHOOK_HOSTS` lists at least a host | 409, nothing can be saved                             |
| Scheme is `https` and the URL names a host    | 422                                                   |
| No user, no password, port 443 or none        | 422                                                   |
| The host is on `COSTURA_WEBHOOK_HOSTS`        | 422, the answer names the allowed hosts               |
| At most 2048 characters                       | 422                                                   |

The host match is exact (lowercased, trailing dot removed), not a suffix. The URL is stored
as Fernet ciphertext under `COSTURA_SECRET_KEY`; every answer shows the host only. Posts use
`httpx` with a 10 second timeout and `follow_redirects=False` (`http_post`), so a redirect
counts as a non-2xx answer and the request never reaches a second host. A host dropped from
`COSTURA_WEBHOOK_HOSTS` after the save stops the worker: its rows stay pending until the host
returns or another URL is saved, and the card shows the host as blocked.

## Payload

The body is one JSON object with one key, the Slack `text` field:

```json
{"text": "*Key without an owner* (anthropic) Key without an owner: orphan. At risk: 0.00 USD. Owner: nobody recorded. <https://costura.example.com/o/acme?next=%2Fkeys%2Fapikey_orphan|Open in Costura>"}
```

`message` in `delivery.py` builds it: the kind title in bold, the provider, the sentence (the
anomaly explanation, or the label and the gap), the money at risk, the owner, and a link to
the item through `{COSTURA_WEB_PUBLIC_URL}/o/{slug}?next=...` (`COSTURA_WEB_ORIGIN` when the
public URL is unset). The optional digest (`costura/digest.py`) posts the same shape with
`*Costura digest for {org}*` as its first line.

## Headers and signature

| Header                | Value                                                      |
| --------------------- | ---------------------------------------------------------- |
| `Content-Type`        | `application/json`                                         |
| `User-Agent`          | `Costura-Webhook/1`                                        |
| `X-Costura-Delivery`  | The delivery row id; `test` for the test message           |
| `X-Costura-Timestamp` | Unix seconds when the request was signed                   |
| `X-Costura-Signature` | `v1=` followed by the lowercase hex HMAC described below   |

`signed_headers` computes the signature as HMAC-SHA256 over the string
`{X-Costura-Timestamp}.{raw body}` with the organization's signing secret as the key. The
secret is generated on save (`secrets.token_urlsafe(32)`), returned once in the save answer and
stored encrypted; saving another URL issues a new one. Slack ignores these headers. A receiver
of your own compares the digests in constant time and rejects a timestamp outside a window
it chooses, since Costura does not send the same body twice with the same timestamp.

Python, standard library only:

```python
import hashlib, hmac, os

def verify(headers: dict[str, str], body: bytes) -> bool:
    secret = os.environ["COSTURA_WEBHOOK_SECRET"].encode()
    timestamp = headers.get("X-Costura-Timestamp", "")
    signature = headers.get("X-Costura-Signature", "")
    expected = hmac.new(secret, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, f"v1={expected}")
```

Node, `crypto` only:

```js
const { createHmac, timingSafeEqual } = require("node:crypto");

function verify(headers, body) {
  const secret = process.env.COSTURA_WEBHOOK_SECRET;
  const timestamp = headers["x-costura-timestamp"] ?? "";
  const given = Buffer.from(headers["x-costura-signature"] ?? "");
  const digest = createHmac("sha256", secret).update(`${timestamp}.`).update(body).digest("hex");
  const expected = Buffer.from(`v1=${digest}`);
  return given.length === expected.length && timingSafeEqual(given, expected);
}
```

`body` is the raw request body as bytes, before any JSON parsing.
[examples/slack-webhook-receiver](../../examples/slack-webhook-receiver/README.md) is a
complete receiver built on the Python snippet.

## Delivery and retries

The worker (`apps/api/costura/ops/worker.py`, `DELIVERY_INTERVAL_SECONDS = 60`) runs
`deliver_all` about once a minute. Each pass, per organization with a destination:

1. Every current signal gets one `webhook_deliveries` row, unique per organization and
   signal (anomaly id, budget alert id, or key id with the gap kind), so a signal is posted
   at most once. The `webhook_failing` signal itself is never posted.
2. Rows that are `pending` and due are claimed, 20 per pass (`BATCH`), with
   `FOR UPDATE SKIP LOCKED`, oldest first.
3. A row whose signal closed since it was recorded is marked `skipped` with the error
   `closed before delivery`.
4. The others are posted. A 2xx marks the row `sent`. A non-2xx answer records `HTTP {status}`;
   a transport error records the exception class (`ConnectError`, `ReadTimeout`). Neither
   records the URL.

The retry schedule is `BACKOFF` in `delivery.py`:

| Attempt | Outcome when it fails              |
| ------- | ---------------------------------- |
| 1       | Next attempt 1 minute later        |
| 2       | Next attempt 5 minutes later       |
| 3       | Next attempt 30 minutes later      |
| 4       | Next attempt 2 hours later         |
| 5       | The row is marked `failed`         |

`MAX_ATTEMPTS = 5`. The next attempt waits for the worker pass after the delay, so the
wall-clock gap is the delay plus up to a minute. The destination row keeps `last_success_at`,
`last_failure_at` and `last_error` across deliveries and test messages. The first 2xx after an
outage (a delivery, a test message or a resend) puts every `failed` row of the organization
back to `pending` with zero attempts (`revive_failed`); a signal that closed in the meantime is
skipped on the next pass.

Saving the first URL records the signals open at that moment as `skipped`, so only what
appears afterwards is posted. Removing the destination deletes the destination and all of its
delivery rows.

## The failing-webhook signal

While the destination's newest post failed (`last_failure_at` after `last_success_at`), the
organization has a `webhook_failing` signal (`apps/api/costura/spend/signals.py`) in the
Overview queue and the bell, with the host as its reference and no money at risk. It is not
posted to the webhook. It clears on the next 2xx. The `costura_webhook_deliveries{status}`
gauge counts rows per status ([monitoring](monitoring.md)).

## Test message and delivery history

`POST /orgs/{org}/webhook/test` (owner) posts
`Costura test message: new signals of this organization will arrive here.` with
`X-Costura-Delivery: test` and answers `{"delivered": true|false, "error": ...}`. A 2xx also
revives failed rows.

`GET /orgs/{org}/webhook` lists the 20 newest delivery rows (skipped ones left out) with `id`,
the signal (`kind`, `provider`, `reference`), `status`, `attempts`, `last_error`, `created_at`,
`sent_at` and `next_attempt_at`. Settings, Anomalies shows them under Deliveries.

`POST /orgs/{org}/webhook/deliveries/{id}/resend` (owner) posts one row again now. Payloads
are not stored: the message is rendered from the signal as it stands, with the same host and
URL rules as the worker (409 when the host left `COSTURA_WEBHOOK_HOSTS`). A signal that closed
since answers 422 and posts nothing; a row of another organization answers 404. The attempt
is counted on the row; a 2xx marks it `sent` and revives failed rows. The event is in the
audit trail as `webhook_resent`.

## Rate limits

Routes under `/api/v1` carry `RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset`,
and a 429 carries `Retry-After` ([monitoring](monitoring.md)).
