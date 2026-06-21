# handelsregister-mcp

**An open-source [Model Context Protocol](https://modelcontextprotocol.io) server for the German Commercial Register — [handelsregister.de](https://www.handelsregister.de).**

Give your AI agents first-class access to official German company data: search the register, read register extracts with management and capital, list filed documents, and pull the **shareholder list (Gesellschafterliste)** — all returned as **structured data and tables**, not raw HTML.

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-000000.svg)](https://modelcontextprotocol.io)
[![Built in](https://img.shields.io/badge/built%20in-Neuland-black.svg)](#das-internet-ist-für-uns-alle-neuland)

---

### „Das Internet ist für uns alle Neuland.“

In 2013, a German Federal Chancellor stood next to the US President and described the internet as *Neuland* — uncharted new territory. The line became a national meme.

More than a decade later, the official Handelsregister is a living monument to that *Neuland* era: a JavaServer Faces application that threads a server-side `ViewState` through every click, a lazy-loaded PrimeFaces document tree, a strict **60-requests-per-hour** limit baked into its terms of use, and **no public API whatsoever**. Since 2022 the data is free and public by law — yet it stays locked behind a portal that no machine was ever meant to talk to.

That gap is exactly why MCP servers need to exist. An LLM agent can reason brilliantly about a company — *if* something hands it the company's data. This project is that something: a small, deterministic bridge from a relic of *Neuland* to the agents of today.

---

## Features

- 🔎 **Company search** — by name/keywords, with exact, all-keyword, and phonetic matching, plus **fuzzy resolution** that returns ranked suggestions when the name isn't exact.
- 📄 **Register extracts** (AD / CD / HD) — parsed into structured fields: name, register number, seat, address, capital, business purpose, dates, and a **management table** (Geschäftsführer / Vorstand with birthdates).
- 🧬 **Structured XJustiz data** (SI) — the machine-readable register payload, parsed.
- 👥 **Shareholders as a table** — finds and downloads the filed Gesellschafterliste and extracts `{shareholder, type, city, register, date_of_birth, shares, nominal_total_eur, percent}`. Handles complex, multi-page, **bilingual** cap tables.
- 🗂️ **Filed-document register** — list everything on file (shareholder lists, articles of association, annual accounts, …) and download any of it.
- 🧾 **OCR fallback** — scanned/image-only PDFs are run through Tesseract so text still comes out.
- ⏱️ **Polite by design** — a shared 60 req/hour limiter, on-disk caching, descriptive User-Agent.
- 🧱 **Fully deterministic** — no LLM lives inside the server (see [Design](#design-a-deterministic-tool)).

## How it works

handelsregister.de exposes **no REST API** — only a JSF/PrimeFaces web form. Every request must carry a session cookie and a server-generated `ViewState` through a multi-step submission. This server reproduces that browser flow with [`mechanize`](https://github.com/python-mechanize/mechanize) and turns the rendered HTML/PDF/XML into clean structured data.

Since **1 August 2022** (the DiRUG law), both searches and document downloads are **free of charge**.

## ⚠️ Legal & rate limits — read this first

The Handelsregister is public, but not a free-for-all to scrape:

- Its **Nutzungsordnung** (terms of use, per **§9 HGB**) forbids **more than 60 retrievals per hour**, and the portal FAQ warns that automated mass querying may be treated as a criminal offence (**§§303a, b StGB**).
- This server enforces a shared **60 requests/hour** limit by default. **Do not raise it to abuse the portal.** For high-volume or commercial use, use a licensed data provider (e.g. [OpenRegister](https://openregister.de), [handelsregister.ai](https://handelsregister.ai)) instead of scraping.
- Register data contains **personal data** (managing directors, shareholders, birthdates). Handle it under the GDPR and use it only for the informational purposes the register is intended for.

This is a tool for legitimate, measured lookups — diligence, research, journalism, compliance — not bulk harvesting.

## Install

```bash
git clone https://github.com/lexdoudkin/handelsregister-mcp.git
cd handelsregister-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e .

# optional: OCR for scanned documents
pip install -e ".[ocr]"
brew install tesseract tesseract-lang   # macOS; provides the Tesseract binary + German pack
```

> **License note on the OCR extra:** `[ocr]` pulls in [PyMuPDF](https://pymupdf.readthedocs.io),
> which is **AGPL-3.0 / commercial** dual-licensed. The core package (without `[ocr]`) is fully
> permissive. If you redistribute a product built on the OCR path, mind AGPL's terms or obtain a
> commercial PyMuPDF license.

## Connect it to an MCP client

**Claude Code**

```bash
claude mcp add handelsregister -- handelsregister-mcp
```

**Claude Desktop** — add to your MCP config (see [`examples/claude_desktop_config.json`](examples/claude_desktop_config.json)):

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

Then just ask your agent things like *"Who are the shareholders of Trade Republic Bank GmbH?"* or *"Get the register details and managing directors of GASAG AG."*

## Tools

Every tool returns **structured data** — search rows, parsed company fields, and shareholder/management **tables** — plus a ready-to-render `markdown` table for document tools.

| Tool | What it does |
|------|--------------|
| `search_company(keywords, match="all", similar=False, max_results=20)` | Search by name/keywords. `match` ∈ `all` \| `min` \| `exact`. `similar=True` enables phonetic matching. `*` and `?` wildcards. |
| `get_company(name)` | Name lookup. Exact name → the record; inexact/ambiguous → `found: false` + ranked **`suggestions`**. |
| `get_shareholders(company, which="latest")` | **Shareholders as a table** — resolves the name, downloads the filed Gesellschafterliste, and extracts structured rows. |
| `list_filed_documents(company)` | List everything filed in the DK register, grouped by category, with dates. |
| `fetch_filed_document(company, category, which="latest")` | Download any filed document by category (+ shareholder table for share lists). |
| `fetch_document(keywords, document_type="AD", ...)` | Download a register extract. `AD`/`CD`/`HD` → company fields + management table; `SI` → XJustiz data. |
| `rate_limit_status()` | Remaining requests in the current hour. |

**Document types:** `AD` current extract · `CD` chronological extract · `HD` historical extract · `SI` structured XML (XJustiz) · `VÖ` announcements · `UT` holder data. (`DK`, the filed-documents register, is reached via `list_filed_documents` / `get_shareholders` / `fetch_filed_document`.)

### Example: `get_shareholders`

```jsonc
// get_shareholders("Trade Republic Bank GmbH")
{
  "company": { "name": "Trade Republic Bank GmbH", "register_number": "HRB 244347" },
  "source_document": { "label": "List of shareholders … on 15/06/2026", "date": "2026-06-15" },
  "method": "pdfplumber",
  "confidence": "high",
  "stammkapital_eur": 96293600.0,
  "shareholders": [
    { "shareholder": "Accel Holdings-TR LLC", "type": "company", "city": "Palo Alto, USA",
      "nominal_total_eur": 13008200.0, "percent": "12,7936%" },
    { "shareholder": "Creandum V, L.P.", "type": "company", "city": "St. Peter Port",
      "nominal_total_eur": 12936200.0, "percent": "12,7228%" }
    // … 74 shareholders total
  ]
}
```

### Fuzzy name resolution

`get_company` and `get_shareholders` don't need the exact registered name. Exact match → they proceed; otherwise they fall back to keyword + phonetic search, rank the candidates, and return **`suggestions`** — e.g. `get_shareholders("Trade Republic")` → `["Trade Republic Bank GmbH", "Trade Republic Service GmbH", …]`.

## Shareholder extraction (layered & deterministic)

The Gesellschafterliste has no standard layout, so extraction is layered — strongest engine first:

1. **Coordinate-aware table parsing** ([`pdfplumber`](https://github.com/jsvine/pdfplumber)) — rebuilds columns from the PDF's ruling lines / text positions. Handles complex and **bilingual** cap tables (e.g. Trade Republic's 74-shareholder German/English list) that flat text extraction garbles.
2. **Text heuristic** — the standard single-language notarial template.

The `method` field tells you which engine produced the table.

> **Shareholders are not in the register extract** for a GmbH/UG — they exist only in this separately filed list, which `get_shareholders` downloads and parses.

## Design: a deterministic tool

An MCP server is consumed *by* an LLM agent — so it would be redundant (and non-deterministic) to call another LLM inside it. **This server never calls an LLM.** When neither parser is confident (`confidence: "low"`), it doesn't guess: it returns the `raw_text` and the downloaded PDF `path`, and the calling agent — which is already an LLM — reads those and extracts the table itself. Intelligence lives in the caller; the tool just fetches data, faithfully.

OCR is the one heavyweight step, and it's deterministic too: scanned PDFs are rasterised and run through **Tesseract** (German) so text still comes out.

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `HANDELSREGISTER_MAX_PER_HOUR` | `60` | Hourly request cap. **Do not exceed the portal limit.** |
| `HANDELSREGISTER_DOWNLOAD_DIR` | system temp dir | Where downloaded documents are written. |
| `HANDELSREGISTER_OCR` | `auto` | OCR for scanned PDFs: `auto` (only when the text layer is empty), `always`, or `off`. |
| `HANDELSREGISTER_OCR_LANG` | `deu` | Tesseract language(s), e.g. `deu+eng`. |

## Use as a library

```python
from handelsregister_mcp import HandelsregisterClient

client = HandelsregisterClient()
hits = client.search("GASAG AG", match="exact")
doc = client.fetch_document(hits[0]["row_index"], "AD")
print(doc["structured"]["management"])
```

## Project layout

```
src/handelsregister_mcp/
├── server.py      # MCP tools (FastMCP)
├── client.py      # the JSF/PrimeFaces portal client (search + documents)
├── parsers.py     # register extract, XJustiz SI, shareholder-list parsing
├── ocr.py         # optional Tesseract OCR fallback
└── ratelimit.py   # shared 60/hour limiter
```

## Known limitations

- **Scanned tables**: OCR recovers *text* but not table *structure* — those parse low-confidence and return `raw_text` for the caller. Coordinate-based OCR table reconstruction (Tesseract TSV) is a possible future improvement.
- **Pagination**: fuzzy suggestions are drawn from the first results page; a very common partial query may miss a match that sits on a later page.
- **Portal markup drift**: the document-register flow depends on the live HTML; if the portal changes, parsing may need a tweak. PRs welcome.

## Contributing

Issues and pull requests are welcome — especially for parser robustness across the many notarial Gesellschafterliste templates, and for additional register document types. Please keep changes deterministic and respectful of the portal's rate limits.

## Credits

The portal search flow is adapted from the excellent [bundesAPI/handelsregister](https://github.com/bundesAPI/handelsregister) / [`deutschland`](https://github.com/bundesAPI/deutschland) project (Apache-2.0), part of the [bund.dev](https://bund.dev) effort to document and open up Germany's public APIs.

## License

[Apache-2.0](LICENSE).

## Disclaimer

Not affiliated with the Handelsregister, the German Federal States, or any official body. Use it lawfully and within the portal's terms of use. The maintainers accept no liability for how the data is obtained or used.
