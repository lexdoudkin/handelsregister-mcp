# handelsregister-mcp

An open-source **[Model Context Protocol](https://modelcontextprotocol.io) server** for the
German commercial register, **[handelsregister.de](https://www.handelsregister.de)**.

It lets AI agents do the two things people actually use the register for — **search for a
company** and **retrieve its register documents** — through a clean MCP tool interface,
instead of clicking through the portal's legacy JSF/PrimeFaces web form by hand.

> **Status:** company search is solid and built on the well-tested
> [bundesAPI/handelsregister](https://github.com/bundesAPI/handelsregister) flow.
> Document download is wired up but is the most fragile part (it depends on the portal's
> command-link markup) — verify it against the live portal and open an issue if the IDs drift.

## Why this exists

handelsregister.de has **no official API**. It is a server-side JSF application, so every
request has to carry a session cookie and a server-generated `ViewState` through a multi-step
form submission. This server reproduces that browser flow with [`mechanize`](https://github.com/python-mechanize/mechanize)
and exposes the result as MCP tools.

Since **1 August 2022** (the DiRUG law) both searches and document downloads are **free of charge**.

## Tools

| Tool | What it does |
|------|--------------|
| `search_company(keywords, match="all", max_results=20)` | Search by name/keywords. `match` ∈ `all` \| `min` \| `exact`. Supports `*` and `?` wildcards. |
| `get_company(name)` | Exact-name lookup; returns the single best match. |
| `fetch_document(keywords, document_type="AD", match="exact", result_index=0)` | Download an extract/document and return its extracted text + local path. |
| `rate_limit_status()` | Remaining requests in the current hour. |

**Document types:** `AD` current extract · `CD` chronological extract · `HD` historical extract ·
`DK` filed-documents register · `SI` structured XML data · `VÖ` announcements · `UT` holder data.

A search result row looks like:

```json
{
  "row_index": 0,
  "name": "GASAG AG",
  "court": "Amtsgericht Charlottenburg (Berlin) HRB 44343 B",
  "register_number": "HRB 44343 B",
  "state": "Berlin",
  "status": "currently registered",
  "history": [],
  "available_documents": ["AD", "CD", "DK", "HD", "SI", "UT"]
}
```

## ⚠️ Legal & rate limits — read this

- The portal's **Nutzungsordnung** (terms of use, per **§9 HGB**) forbids **more than 60
  retrievals per hour**. The portal FAQ warns that automated mass querying beyond this may be
  treated as a criminal offence (**§§303a, b StGB**).
- This server enforces a shared **60 requests/hour** sliding-window limit by default. Do **not**
  raise it to abuse the portal. For high-volume or commercial use, use a licensed data provider
  (e.g. [OpenRegister](https://openregister.de), [handelsregister.ai](https://handelsregister.ai))
  instead of scraping.
- Register data can contain **personal data** — handle it in line with the GDPR and use it only
  for the informational purposes the register is intended for.

## Install

```bash
git clone <your-fork-url> handelsregister-mcp
cd handelsregister-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Run

```bash
handelsregister-mcp        # serves over stdio
```

### Claude Desktop / Claude Code

Add to your MCP config (see [`examples/claude_desktop_config.json`](examples/claude_desktop_config.json)):

```json
{
  "mcpServers": {
    "handelsregister": {
      "command": "handelsregister-mcp",
      "env": { "HANDELSREGISTER_MAX_PER_HOUR": "60" }
    }
  }
}
```

For Claude Code: `claude mcp add handelsregister -- handelsregister-mcp`.

### Use the library directly

```python
from handelsregister_mcp import HandelsregisterClient

client = HandelsregisterClient()
hits = client.search("GASAG", match="exact")
doc = client.fetch_document(hits[0]["row_index"], "AD")
print(doc["text"][:500])
```

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `HANDELSREGISTER_MAX_PER_HOUR` | `60` | Hourly request cap (do not exceed the portal limit). |
| `HANDELSREGISTER_DOWNLOAD_DIR` | system temp dir | Where downloaded documents are written. |

## Credits

Search flow adapted from [bundesAPI/handelsregister](https://github.com/bundesAPI/handelsregister)
/ the [`deutschland`](https://github.com/bundesAPI/deutschland) package (Apache-2.0).

## License

[Apache-2.0](LICENSE).
