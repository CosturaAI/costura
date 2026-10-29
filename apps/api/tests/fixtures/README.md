# API test fixtures

These JSON files are synthetic. They were written for the test suite and do not contain
customer data, live account ids, or real provider keys. Names such as `Example Labs` and
addresses under `.example` are placeholders.

## Captured fixtures

A captured fixture is a real provider response with its personal values replaced. Synthetic
files show the shapes the connector expects; captured files show the shapes a provider sends
today, including fields and nulls nobody wrote by hand. Both are one response body per file,
the JSON object the client reads, served by the `httpx.MockTransport` handlers in
`apps/api/tests/conftest.py`.

Capture from an install that has synced the account (`just dev`, connect the key, sync):

```
just api::capture-fixtures anthropic ./captured --org default --pages 3
```

The recipe reads the pages the newest run of each endpoint stored in `provider_report_pages`
and writes `./captured/<provider>/<endpoint>_page<N>.json` plus `index.json`, which names
the endpoint, page index and request parameters behind each file. It calls no provider, reads
no key and uploads nothing. Pages past `COSTURA_RAW_PAGE_RETENTION_DAYS` are gone; sync again
first. The output directory must be new or empty.

Redaction is on by default and deterministic within one capture:

| Value | Becomes |
| --- | --- |
| e-mail, anywhere in a string | `user1@example.com`, `user2@example.com`, ... |
| id fields (`id`, `*_id`, `hash`) and page cursors | `<prefix>_redacted_N` (`wrkspc_01ABC` -> `wrkspc_redacted_1`); integer ids become `1001`, `1002`, ... |
| names (`name`, `*_name`, `title`, `organization`) | `Name N` |
| logins and people (`login`, `slug`, `user`, `owner`, `actor` as text) | `login-N` |
| keys, tokens, hints (`*_key`, `*_token`, `label`, `partial_key_hint`, `redacted_value`, `sk-...`) | `[redacted]` |
| URLs (`*url`, `href`) | `https://example.com/redacted/N` |
| other text with spaces or symbols | `Text N` |

The same id maps to the same placeholder in every file of one capture, so a workspace id in
a cost page still matches the workspace listing and a `next_page` cursor still matches the
next request's `page`. Numbers, dates, booleans, model names, enum values and the structure
stay as received; fields the normalizers branch on (`model`, `description`, `line_item`,
`sku`, `token_type`, `client_id` and others in `KEPT` in
`apps/api/costura/ops/capture_fixtures.py`) are kept apart from e-mails and keys inside them.

Redaction goes by field name and value shape. Read every file before attaching it to an
issue or pull request, and replace anything that still names a person, a company or an
account.

To turn a capture into a regression test, copy the files into `tests/fixtures/<provider>/`
under a name that says what they cover (`usage_report_captured_page1.json`), name them in the
provider's handler or in the test, and assert what the normalizer produces from them. Keep
the synthetic files: they pin cases a live account may not have.
