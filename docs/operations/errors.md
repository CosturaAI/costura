# Errors

The API answers a refusal with the HTTP status of the error and a JSON body with two fields:
`detail`, the message for the person who sent the request, and `code`, a stable name for the
kind of error. Validation failures keep FastAPI's list of field errors in `detail` and add
`code: "validation_failed"`. The web app shows `code` under "Technical details" on its error
page, and "Copy details" there and on Run history copies route, status, code, message, digest,
`COSTURA_VERSION` and time as Markdown for an issue or a support thread.

```json
{ "detail": "organization 'acme' already exists", "code": "duplicate_slug" }
```

Codes come from the `DomainError` subclasses in `apps/api/costura`;
`apps/api/tests/test_errors_doc.py` fails when this page and the code disagree. Symptoms that
are not API refusals (a stack that does not start, a cookie that does not stick) are in
[troubleshooting](troubleshooting.md).

## Error schema

### `budget_needs_provider`

- **Status:** 400
- **Message:** choose a provider: this budget needs one of [...]
- **Suggested action:** An organization or workspace budget was requested under the `all`
  provider scope. Repeat the request with one provider name from the list in the message.

### `signup_closed`

- **Status:** 403
- **Message:** this e-mail domain is not allowed to sign up; sign-up is by invitation on this
  instance
- **Suggested action:** Ask an owner of the organization for an invitation. The operator
  opens sign-up with `COSTURA_SIGN_UP=open` or lists domains in
  `COSTURA_ALLOWED_EMAIL_DOMAINS` ([configuration](configuration.md)).

### `not_found`

- **Status:** 404
- **Message:** anomaly not found; team not found; no user {id}; or the name of the missing key,
  workspace or person
- **Suggested action:** The organization has no such row. Check the identifier in the URL and
  the provider scope; a row under one provider is not visible under another.

### `unknown_account`

- **Status:** 404
- **Message:** no {provider} account {id} in this organization
- **Suggested action:** List the provider's accounts in Settings, Connections and use an id
  from that list.

### `unknown_credit_account`

- **Status:** 404
- **Message:** no account {id} in this organization
- **Suggested action:** Use the id of a Codex account of this organization from Settings,
  Connections.

### `unknown_credit_price`

- **Status:** 404
- **Message:** credit price {id} not found
- **Suggested action:** The price row was already deleted or belongs to another account.
  Reload the credit price list before deleting again.

### `unknown_member`

- **Status:** 404
- **Message:** this person is not a member of the organization
- **Suggested action:** Reload Settings, Members; the person left or was removed before the
  request.

### `unknown_organization`

- **Status:** 404
- **Message:** unknown organization '{slug}'
- **Suggested action:** Check the slug in the URL against the organizations the signed-in
  user belongs to (`GET /api/v1/orgs`).

### `unknown_person`

- **Status:** 404
- **Message:** person not found
- **Suggested action:** No user in the provider scope has that e-mail address. Check the
  address and the provider filter; people appear after an import that names them.

### `account_in_use`

- **Status:** 409
- **Message:** {provider} account '{label}' is still connected
- **Suggested action:** Disconnect the key on the account's card first, or repeat the removal
  with `force` to drop the account together with its rows and credential.

### `already_invited`

- **Status:** 409
- **Message:** {email} already has a pending invitation
- **Suggested action:** Share the existing invitation link from Settings, Members, or revoke
  it there and invite again.

### `already_member`

- **Status:** 409
- **Message:** {email} is already a member of the organization
- **Suggested action:** Change the person's role in Settings, Members instead of inviting
  them again.

### `demo_busy`

- **Status:** 409
- **Message:** another demo refresh is running; try again when it finishes
- **Suggested action:** Wait for the running refresh of the sample organization to finish,
  then run the seed again.

### `demo_slug_taken`

- **Status:** 409
- **Message:** organization 'demo' exists and is not the sample organization; costura never
  publishes an existing organization. Rename it (or delete it) before seeding the demo.
- **Suggested action:** Rename or delete the organization that uses the `demo` slug, then seed
  the sample organization again.

### `duplicate_slug`

- **Status:** 409
- **Message:** organization '{slug}' already exists
- **Suggested action:** Choose another slug, or ask an owner of the existing organization for
  an invitation.

### `last_owner`

- **Status:** 409
- **Message:** this is the last owner of the organization; make someone else an owner first
- **Suggested action:** Promote another member to owner in Settings, Members, then repeat the
  role change or removal.

### `organization_busy`

- **Status:** 409
- **Message:** organization sync is active; wait for it to finish; or organization sync is
  {status} (scheduler run {id}); wait for it to finish
- **Suggested action:** A reset cannot run while the organization has queued or running sync
  work. Wait for the run named in the message to finish (Data health, Sync status) and retry.

### `organization_claimed`

- **Status:** 409
- **Message:** organization '{slug}' already has members; manage them in the web app
- **Suggested action:** The first-owner claim applies only to an organization without
  members. Ask an existing owner for an invitation.

### `reserved_slug`

- **Status:** 409
- **Message:** organization slug '{slug}' is reserved for this deployment; choose another
  address
- **Suggested action:** Choose a slug that is not the sample organization's or another
  reserved address of this instance.

### `several_accounts`

- **Status:** 409
- **Message:** {provider} has several accounts; use the accounts routes
- **Suggested action:** The provider-level key route handles one account per provider. Use the
  account's own card in Settings, Connections, or the `/accounts/{id}` routes with the account
  id.

### `sync_active`

- **Status:** 409
- **Message:** sync running (scheduler run {id})
- **Suggested action:** The account has a queued or running sync and cannot be removed yet.
  Wait for the run to finish in Data health, Sync status, then disconnect again.

### `sync_already_queued`

- **Status:** 409
- **Message:** sync already {status} for {provider} (scheduler run {id})
- **Suggested action:** Sync now was pressed while a sync of the same account was queued or
  running. Follow the run named in the message in Data health, Run history.

### `webhooks_off`

- **Status:** 409
- **Message:** outbound webhooks are off on this stack; the operator lists allowed hosts in
  COSTURA_WEBHOOK_HOSTS
- **Suggested action:** The operator sets `COSTURA_WEBHOOK_HOSTS` to the hosts the stack may
  post to ([configuration](configuration.md)) and restarts the API and the worker.

### `invitation_unavailable`

- **Status:** 410
- **Message:** this invitation is no longer valid; ask an owner for a new one
- **Suggested action:** The invitation does not exist, was revoked, was accepted or has
  expired. Ask an owner of the organization for a new link.

### `duplicate_effective_date`

- **Status:** 422
- **Message:** a credit price already starts on {date}
- **Suggested action:** Edit the existing price for that date, or choose another
  `effective_from`.

### `duplicate_key`

- **Status:** 422
- **Message:** this key already connects the {provider} account {label}
- **Suggested action:** Each key connects one account of a provider. Replace the key on the
  account the message names, or connect a different key.

### `duplicate_label`

- **Status:** 422
- **Message:** a {provider} account labelled '{label}' already exists
- **Suggested action:** Choose a label that no other account of the same provider carries.

### `effective_date_out_of_range`

- **Status:** 422
- **Message:** effective_from must be between {date} and {date}
- **Suggested action:** Use an `effective_from` inside the range the message names, counted
  from today.

### `invalid_budget`

- **Status:** 422
- **Message:** at least one threshold is required; thresholds must be between 1 and 200;
  scope_kind must be one of [...]; period must be one of [...]; a {scope} budget is monthly;
  and the other `scope_id` rules
- **Suggested action:** The message names the field and the accepted values. Correct the
  budget form and submit again.

### `invalid_credential`

- **Status:** 422
- **Message:** the {key type} is empty; {provider} rejected the key (HTTP {status}). Check that
  it is a {key type} ({prefix}...), not a regular API key, and that it was not revoked.;
  {provider} accepted the key but {reason}
- **Suggested action:** Paste the key type the message names ([provider keys](../security/provider-keys.md));
  a key the provider rejected is revoked or of the wrong type, and a key the provider
  accepted but cannot use lacks the scope the import needs.

### `invalid_credit_account`

- **Status:** 422
- **Message:** credit prices apply only to Codex accounts
- **Suggested action:** Credit prices are a Codex concept. Select a Codex account.

### `invalid_credit_price`

- **Status:** 422
- **Message:** price_per_credit must be a positive finite amount
- **Suggested action:** Enter a price above zero.

### `invalid_input`

- **Status:** 422
- **Message:** a sentence naming the refused value: an unknown dimension, a malformed filter, a
  date range out of order, an address that is not an e-mail, a webhook URL that is too long
- **Suggested action:** The message names the parameter and the accepted form. Correct the
  value and send the request again.

### `invalid_label`

- **Status:** 422
- **Message:** the account label is required; the account label is longer than {n} characters
- **Suggested action:** Give the account a non-blank label within the length the message
  names.

### `invalid_name`

- **Status:** 422
- **Message:** name must be 1 to {n} characters after trimming
- **Suggested action:** Enter a display name within that length.

### `invalid_role`

- **Status:** 422
- **Message:** invalid role '{role}': one of owner, member, viewer
- **Suggested action:** Use one of the roles the message lists.

### `invalid_slug`

- **Status:** 422
- **Message:** invalid organization slug '{slug}': lowercase letters, digits and hyphens, 2 to
  63 characters, starting with a letter or digit
- **Suggested action:** Choose a slug that matches that shape.

### `no_credential`

- **Status:** 422
- **Message:** no {provider} {key type} for this account; connect one in the web settings page
- **Suggested action:** Connect a key on the account's card in Settings, Connections before
  running a sync or validation.

### `validation_failed`

- **Status:** 422
- **Message:** a list of field errors, each with `loc`, `msg` and `type`
- **Suggested action:** The request body or query did not match the schema. Each entry names
  the field in `loc` and the rule in `msg`; the OpenAPI document (`/docs` on the API) lists the
  expected shape.

### `provider_protocol_error`

- **Status:** 502
- **Message:** {provider} returned an unexpected response while validating the key: {reason}
- **Suggested action:** The provider answered with something other than an authentication
  result. Retry; if it repeats, open an issue with the message (it is already redacted).

### `provider_unavailable`

- **Status:** 503
- **Message:** {provider} could not validate the key because the provider is temporarily
  unavailable: {reason}
- **Suggested action:** Retry in a moment; the key was not stored. The provider's status page
  tells whether the outage is on their side.
