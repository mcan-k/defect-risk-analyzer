# Security Policy

## What this project does with your data

### Credentials

Credentials are the Jira API token, the LLM provider key (Groq or OpenAI) and
the webhook server's own `API_KEY`. Everything else in `.env` is a setting.

**Where they live.** On a desktop install with the `desktop` extra
(`pip install -e ".[desktop]"`), they are stored in the operating system's
credential store through `keyring`. Without that extra — and in Docker and in
CI — they stay in `.env` in plain text. The Settings page states which of the
two your install is actually using, and names the resolved backend. It is
reported rather than assumed: `PYTHON_KEYRING_BACKEND` and `keyringrc.cfg` can
both redirect the choice, so no claim made at install time would be reliable.

**When they move.** Opening the dashboard migrates any credential still in
`.env` into the credential store, once, at startup. Nothing is removed from
`.env` until the store has been written AND read back successfully — a store
that accepts a write and returns nothing is the failure this guards against.
If the store cannot take a value, it stays in `.env` and you are told. If the
store took it but `.env` could not be updated, the credential is in both
places and you are told that too.

The API server and the CI analyzer never migrate anything. Neither has a
credential store available, and neither has anywhere to report what it did.

**Which copy wins.** A non-empty value in `.env` takes precedence over the
credential store, and the store is consulted only for values `.env` does not
have. This keeps a hand-edited file meaningful and keeps a half-finished
migration working. It has a consequence worth knowing: if you paste an old key
into `.env`, it silently shadows a newer one in the store. Clear the line to
go back to the stored value.

**Saving from the Settings page** writes credentials to whichever layer is in
use, and clears the `.env` line when the store took the value — otherwise the
file would shadow what you just saved. If the store refuses, the value goes to
`.env` rather than being lost.

`.env` is excluded from git (`.gitignore`) and from the Docker build context
(`.dockerignore`). Writes go through a temp file and `os.replace`, and POSIX
permission bits are carried over.

Docker and CI pass credentials as environment variables by definition —
`docker-compose.yml` hands `.env` to both services with `env_file`, and
`python:3.11-slim` has no credential store. The guarantee above is scoped to
the desktop layer, and this is why.

### Masking before an external call

When `ANONYMIZE_DATA` is on (default), the following are replaced with
reversible tokens before any text is sent to an LLM provider:

| Category | Example |
|---|---|
| E-mail addresses | `[EMAIL_001]` |
| IPv4 addresses | `[IP_001]` |
| URLs | `[URL_001]` |
| Phone numbers | `[PHONE_001]` |
| `Bearer` tokens | `[TOKEN_001]` |
| Known API-key prefixes (`gsk_`, `sk-`, `xoxb-`, `xoxp-`, `ghp_`, `glpat-`, `ATATT`) and `key=value` secrets | `[APIKEY_001]` |

**Person names are not masked.** No name recogniser ships with this project.

Pattern-based masking is a reduction, not a guarantee, and it errs in both
directions. Things that should be masked and are not: IPv6, unusual phone
formats, and identifiers these patterns have never seen. And things that are
masked and should not be: a numeric identifier shaped like a phone number — an
order reference such as `555-1234-5678` — is replaced with a `[PHONE_001]`
token too, so that value disappears from the text the model reads and the
analysis is written without it. Shape alone cannot separate the two.

The token mapping exists only for the duration of a single analysis call and is
never written to disk. Versions before this release persisted it to
`data/anon_map.json`; that file is deleted on first start and is no longer
created.

### What is stored on disk

`data/analysis_results.json` holds the analysis history. Two of its fields
carry text rather than derived numbers: `query` is stored **unmasked**, and
`reasoning` is stored **after** the tokens have been replaced with the original
values. If a bug summary or a free-text query contains personal data, it is on
disk in plain text.

The runtime files under `data/` — including `analysis_results.json` — are
excluded from git and from the Docker build context by name. Under Docker they
live in the `app-data` volume, which both services share. `data/sample_bugs.json`
is deliberately committed; it is demo data about a fictional product.

### Logging

Log files (`data/*.log`) are excluded from git and from the Docker build
context.

**This project's own code never passes a credential value to a logging call.**
That is a property of the source, and it is the only logging guarantee offered
here — it does not extend to text this project did not compose. Specifically,
when an LLM provider returns an error, the provider's message is logged and
shown on the Settings page; what that message contains is the provider's
choice, not ours. See the next section.

### Provider error messages

Both SDKs build their exception text from the HTTP **response body** only; the
request headers, which carry the API key, do not reach it. This was verified in
the SDK source (`openai` 1.58.1, `groq` 0.13.0), not by making a live request.

Whether a provider — or a proxy in front of one — ever echoes a credential back
in a response body has **not** been measured, and this project cannot control
it. If it happened, that body would reach the log file and the Settings page.
Read error text before pasting it into a public issue.

### API authentication

Thirteen of the fourteen endpoints require an `X-API-Key` header; `GET /health`
is the only open one. A server with no key configured rejects every request
with 503 rather than running unauthenticated. The comparison is constant-time.

## Reporting a vulnerability

Please report security issues privately through GitHub's security advisory
channel for this repository, not by opening a public issue.

This is a single-maintainer open-source project. No response-time commitment is
made, because none could be honoured reliably.
