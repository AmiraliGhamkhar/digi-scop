# DigiScope documentation

This directory contains the maintained technical documentation for DigiScope and
an explicitly marked snapshot of its upstream MCP contract.

## Start here

| Document | Audience | Contents |
|---|---|---|
| [Main README](../README.md) | Everyone | Features, quick start, commands, and limits |
| [راهنمای فارسی](../README_FA.md) | Persian readers | Setup, collection, reports, and limitations |
| [Architecture](architecture.md) | Engineers | Components, flows, persistence, concurrency, trust boundaries |
| [REST API](api.md) | API consumers | Parameters, response semantics, errors, and examples |
| [Data integrity](data-integrity.md) | Analysts and engineers | Fact/derivation boundary, formulas, coverage, missing data |
| [Operations](operations.md) | Operators | Migrations, collection, scopes, cron, backup, recovery, troubleshooting |
| [Deployment](deployment.md) | Operators | VPS/shared-host prerequisites, TLS, process model, checklist |
| [Testing](testing.md) | Contributors | Test layout, commands, live checks, and release validation |
| [Security policy](../SECURITY.md) | Operators and reporters | Threat model, token handling, reporting process |
| [Changelog](../CHANGELOG.md) | Everyone | DigiScope release history |
| [License status](../LICENSE) | Everyone | Inherited terms and the unresolved DigiScope-source notice |

## Upstream MCP contract material

These files document the independently hosted data source. They are not
DigiScope REST endpoints:

| Document | Purpose |
|---|---|
| [MCP integration report](MCP_INTEGRATION_REPORT.md) | Inspection findings, transport, relevant tools, limits, live status |
| [Upstream MCP tool reference](tools.md) | Snapshot of all 19 documented read-only tools |
| [`card.d.ts`](card.d.ts) | Upstream compact product-card shape |
| [Direct MCP examples](../examples/README.md) | Diagnostic examples for the upstream service |

## Inherited repository assets

`assets/` holds an illustration inherited from the upstream showcase repository.
It is **not** a DigiScope screenshot and is not embedded in DigiScope
documentation. Do not reuse it as product imagery without the original owner's
permission.

## Documentation rules

When application behaviour changes:

1. update the relevant focused document and README command examples;
2. update `CHANGELOG.md` under `Unreleased`;
3. keep upstream capabilities separate from DigiScope capabilities;
4. never describe current data as historical, rank as units sold, or incomplete
   coverage as complete;
5. include exact tested commands and avoid claiming deployment or live MCP access
   that has not been verified;
6. run the checks in [testing.md](testing.md), including documentation link and
   stale-wording searches where applicable.

Vendored license texts under `app/static` are legal notices and must not be
rewritten as project documentation.
