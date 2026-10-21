# DigiScope security policy

## Supported versions

DigiScope is currently an early MVP. Security fixes are applied to the latest
`0.1.x` release line and the `main` branch only.

| Version | Supported |
|---|---|
| 0.1.x | Yes |
| Older or unreleased snapshots | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use this repository's
private [GitHub security advisory form](https://github.com/AmiraliGhamkhar/digi-scop/security/advisories/new).

Include, when possible:

- the affected endpoint, command, or file;
- the DigiScope version or commit;
- reproduction steps that do not expose real credentials or personal data;
- impact and any suggested mitigation.

Issues in the independently hosted Digikala MCP service should be reported to
that project's owner through the
[`mmdju/digikala-mcp` security page](https://github.com/mmdju/digikala-mcp/security).

## Security model

### Administrative collection

`POST /api/collection/run` is the only administrative REST action. It requires a
configured `ADMIN_TOKEN` in the `X-Admin-Token` header and compares it with
constant-time semantics. Production startup rejects a missing token when
collection is enabled and rejects tokens shorter than 24 characters.

- Send the token only over HTTPS.
- Keep `.env` outside the public document root and mode-restrict it.
- Rotate the token after suspected disclosure.
- Never put the token in URLs, browser storage, screenshots, source control, or
  reverse-proxy access logs.
- Prefer cron invoking `python -m scripts.collect` locally when an HTTP trigger is
  unnecessary.

DigiScope does not implement multi-user accounts or authorization roles. Put the
whole application behind an additional access control layer if its read APIs
must not be public.

In `0.1.x`, `COLLECTION_ENABLED` is a production token-validation policy, not a
runtime kill switch. A read-only deployment must set it to `false`, omit
`ADMIN_TOKEN`, and disable cron. Leaving a token configured keeps the HTTP trigger
usable even when that flag is false.

### Input and output boundaries

- FastAPI and Pydantic validate query parameters, request bodies, periods,
  limits, sort fields, and category IDs.
- Upstream URLs are fixed by configuration; callers cannot supply arbitrary
  outbound URLs.
- The normalizer accepts product links only when they are canonical Digikala
  URLs. Frontend links are validated again and opened with `noopener`.
- User-visible product text is inserted with DOM `textContent`, not executable
  HTML.
- CSV values beginning with spreadsheet formula characters are escaped.
- SQLAlchemy expressions and explicit sort allowlists prevent raw query input
  from becoming SQL.
- Browser responses set a restrictive Content Security Policy, MIME sniffing
  protection, a referrer policy, and frame restrictions. CORS is not enabled.

### Secrets and logging

- DigiScope requires no Digikala API key.
- `ADMIN_TOKEN` is represented as a Pydantic secret and is never returned by an
  API.
- Logs include request paths, durations, status codes, collection counts, tool
  names, and exception classes. They intentionally omit query strings, MCP tool
  arguments, environment values, tokens, and complete upstream payloads.
- Stored collection errors are truncated and should still be treated as
  operationally sensitive.

### Persistence and personal data

DigiScope stores public marketplace product data and collection diagnostics. It
is not designed to collect customer accounts, orders, addresses, buyer profiles,
or other personal information.

The SQLite database, backups, logs, lock files, and `.env` must live outside any
public static directory. The supplied backup command writes mode `0600` files
and performs an integrity check. Operators remain responsible for filesystem
permissions, encrypted off-host backups, retention, and secure deletion.

### Network and dependency assumptions

- The application makes outbound HTTPS requests only to the configured MCP URL.
- The upstream MCP and Digikala public API are outside DigiScope's trust boundary
  and may return malformed, stale, or unavailable data.
- HTTP, JSON-RPC, MCP tool, timeout, and rate-limit errors are bounded and
  sanitized before browser exposure.
- Vendored Chart.js and Vazirmatn license notices are stored beside their assets.
  Python dependency updates should be reviewed and tested before deployment.

## Deployment checklist

1. Set `APP_ENV=production` and a random `ADMIN_TOKEN` of at least 24 characters.
2. Terminate TLS at a maintained reverse proxy and do not expose Uvicorn directly.
3. Run the app as an unprivileged user with one web worker for SQLite.
4. Keep `data/`, `.env`, backups, and logs outside the web root.
5. Restrict file and directory permissions to the service account.
6. Allow outbound HTTPS only where required and verify the MCP destination.
7. Configure log rotation, backup retention, monitoring, and patching.
8. Run `alembic upgrade head`, `pytest -q`, and `/ready` before accepting traffic.
9. Use one scheduler host; filesystem locks do not coordinate multiple machines.

More operational guidance is in [`docs/operations.md`](docs/operations.md) and
[`docs/deployment.md`](docs/deployment.md).
