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

Every tool returns **structured data** — search rows, parsed company fields, and
shareholder/management **tables** — not raw document dumps. Document tools also include
a ready-to-render `markdown` table and keep the source text for verification.

| Tool | What it does |
|------|--------------|
| `search_company(keywords, match="all", similar=False, max_results=20)` | Search by name/keywords. `match` ∈ `all` \| `min` \| `exact`. `similar=True` enables phonetic matching. Supports `*` and `?` wildcards. |
| `get_company(name)` | Name lookup. Exact name → the record; inexact/ambiguous → `found: false` + ranked **`suggestions`**. |
| `get_shareholders(company, which="latest")` | **Shareholders as a table** — resolves the name (suggests if inexact), downloads the filed Gesellschafterliste, and extracts `{shareholder, type, city, register, date_of_birth, shares, nominal_total_eur, percent}`. |
| `list_filed_documents(company)` | List everything filed in the DK register, grouped by category (shareholder lists, articles of association, annual accounts, …) with dates. |
| `fetch_filed_document(company, category, which="latest")` | Download any filed document by category and return its text (+ shareholder table for share lists). |
| `fetch_document(keywords, document_type="AD", ...)` | Download a register extract. `AD`/`CD`/`HD` return parsed company fields + management table; `SI` returns parsed XJustiz data. |
| `rate_limit_status()` | Remaining requests in the current hour. |

### Fuzzy name resolution

`get_company` and `get_shareholders` don't need the exact registered name. They try an
exact match first; if that misses, they fall back to keyword + the portal's phonetic search,
rank the candidates, and return **`suggestions`** so the agent (or user) can pick — e.g.
`get_shareholders("Trade Republic")` → suggestions `["Trade Republic Bank GmbH", …]`.

**Document types:** `AD` current extract · `CD` chronological extract · `HD` historical extract ·
`SI` structured XML (XJustiz) · `VÖ` announcements · `UT` holder data. (`DK`, the filed-documents
register, is accessed via `list_filed_documents` / `get_shareholders` / `fetch_filed_document`.)

`get_shareholders("Art of X UG (haftungsbeschränkt)")` returns:

```json
{
  "company": {"name": "Art of X UG (haftungsbeschränkt)", "register_number": "HRB 266185"},
  "source_document": {"label": "List of shareholders … on 17/10/2025", "date": "2025-10-17"},
  "stammkapital_eur": 1000.0,
  "shareholders": [
    {"shareholder": "Studio Friedrich von Borries UG (haftungsbeschränkt)",
     "type": "company", "register": "AG Charlottenburg HRB 277734 B", "city": "Berlin",
     "shares": "3 - 502", "nominal_total_eur": 500.0, "percent": "50%"},
    {"shareholder": "IKAROS Ventures GmbH", "type": "company",
     "register": "AG Frankfurt/Oder HRB 19554 FF", "city": "Biesenthal",
     "shares": "503 - 1.002", "nominal_total_eur": 500.0, "percent": "50%"}
  ],
  "confidence": "high",
  "markdown": "| shareholder | type | … |"
}
```

> **Shareholders are not in the register extract** for a GmbH/UG — they exist only in the
> separately filed Gesellschafterliste, which `get_shareholders` downloads and parses. Layouts
> vary by notary; the parser flags `confidence: "low"` and returns `raw_text` when unsure.

## How shareholder extraction works (layered)

The Gesellschafterliste has no standard layout, so extraction is layered — strongest engine
first, each only used if the previous one isn't confident:

1. **Coordinate-aware table parsing** (`pdfplumber`) — rebuilds columns from the PDF's ruling
   lines / text positions. Handles complex and **bilingual** cap tables (e.g. Trade Republic's
   74-shareholder German/English list) where flat text extraction garbles the column order.
2. **Text heuristic** — the standard single-language notarial template.

The response's `method` field tells you which engine produced the table (`pdfplumber` or
`line-heuristic`).

**This server is deterministic — it does not call an LLM.** When neither parser is confident
(`confidence: "low"`), it doesn't guess: it returns the `raw_text` and the downloaded PDF
`path`, and an agent consuming this MCP can read those and extract the table itself. The
"analyze the hard ones" intelligence lives in the calling agent, not inside the data tool.

## OCR (scanned / image-only documents)

Newer filings are "digitally born" and have a text layer that `pypdf` reads directly. Older or
scanned documents (many Gesellschafterlisten, annual accounts, pre-digital articles) are
**image-only PDFs with no text layer**. For those, the server falls back to **OCR** (Tesseract,
German), so document tools still return text. The result carries `text_source: "text-layer" | "ocr" | "none"`.

OCR is an **optional extra** (kept out of the core install):

```bash
pip install "handelsregister-mcp[ocr]"          # python libs (pymupdf, pytesseract, Pillow)
brew install tesseract tesseract-lang           # the Tesseract binary + language packs (macOS)
```

| Env var | Default | Purpose |
|---|---|---|
| `HANDELSREGISTER_OCR` | `auto` | `auto` (OCR only when the text layer is empty), `always`, or `off`. |
| `HANDELSREGISTER_OCR_LANG` | `deu` | Tesseract language(s), e.g. `deu+eng`. |

**Caveat — OCR recovers *text*, not table *structure*.** A scanned page is read in a different
spatial order than a digital one, so the shareholder-table parser can't reliably reconstruct
columns from OCR output. When it detects this it sets `confidence: "low"` and returns `raw_text`,
leaving the final extraction to the calling model rather than emitting a confidently-wrong table.
(Coordinate-based table reconstruction via Tesseract TSV is a possible future improvement.)

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
