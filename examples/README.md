# Examples

This directory contains two different kinds of examples. Keep their endpoints
and claims separate.

## DigiScope application examples

[`sample-calls.md`](sample-calls.md) demonstrates the DigiScope REST API, CSV,
operator commands, coverage interpretation, and authenticated manual collection.
Use these examples for the dashboard application.

## Direct upstream MCP diagnostics

[`mcp.json`](mcp.json) is a client configuration for connecting directly to:

```text
https://digikala-mcp.mmdju.workers.dev/mcp
```

[`python.py`](python.py) is a standard-library diagnostic client for that hosted
MCP service. It initializes MCP, lists tools, runs `search_digikala`, and reads
one product. It does **not** use DigiScope's database, collection service,
analytics, authentication, or REST API.

Run it only when direct upstream diagnosis is useful:

```bash
python examples/python.py
```

For DigiScope's contract-aware check, prefer:

```bash
python -m scripts.check_mcp
python -m scripts.check_mcp --call-data
```

## Data warning

Example IDs, prices, and titles are illustrative unless a command is run against
a live service. Prices and availability can change. Neither the examples nor
DigiScope infer historical rank or units sold.
