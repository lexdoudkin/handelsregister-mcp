"""Optional LLM fallback — use Claude to *analyze* documents the deterministic
parsers can't handle (scanned/complex/unusual shareholder lists).

This is the "Analyze" path: when pdfplumber and the text heuristic both come back
low-confidence, hand the document to Claude — as page **images** (vision) when a
PDF is available, otherwise as recovered text — and have it extract the structured
shareholder table. Off unless ANTHROPIC_API_KEY is set.

Config:
  HANDELSREGISTER_LLM        auto (default; on when a key is present) | off
  HANDELSREGISTER_LLM_MODEL  default "claude-opus-4-8"
"""

from __future__ import annotations

import base64
import json
import os

# JSON schema for structured output — kept simple (only `shareholder` required,
# no unsupported numeric/string constraints) so it validates without surprises.
_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "shareholders": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "shareholder": {"type": "string"},
                    "type": {"type": "string", "enum": ["company", "person"]},
                    "city": {"type": "string"},
                    "register": {"type": "string"},
                    "date_of_birth": {"type": "string"},
                    "shares": {"type": "string"},
                    "nominal_total_eur": {"type": "number"},
                    "percent": {"type": "string"},
                },
                "required": ["shareholder"],
            },
        },
        "stammkapital_eur": {"type": "number"},
    },
    "required": ["shareholders"],
}

_INSTRUCTION = (
    "This is a German commercial-register shareholder list (Liste der Gesellschafter / "
    "Gesellschafterliste). Extract every shareholder into structured rows — one row per "
    "shareholder. For each: `shareholder` (company or person name, de-hyphenated), `type` "
    "('company' or 'person'), `city` (seat/Wohnort), `register` (e.g. 'Amtsgericht München "
    "HRB 226829' for companies), `date_of_birth` (YYYY-MM-DD, for persons), `shares` (the "
    "lfd. Nummer / share-number range), `nominal_total_eur` (Summe der Nennbeträge as a "
    "number), and `percent`. Also extract total `stammkapital_eur`. Use ONLY data present "
    "in the document; omit any field you cannot read. Do not invent shareholders."
)


def llm_available() -> tuple[bool, str]:
    """Return (is_available, reason)."""
    if os.environ.get("HANDELSREGISTER_LLM", "auto").lower() == "off":
        return False, "disabled (HANDELSREGISTER_LLM=off)"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY not set"
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "anthropic SDK not installed (pip install handelsregister-mcp[llm])"
    return True, "ok"


def _render_pages(pdf_path, max_pages: int = 12, dpi: int = 150) -> list[bytes]:
    import fitz

    doc = fitz.open(str(pdf_path))
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pages = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pages.append(page.get_pixmap(matrix=matrix).tobytes("png"))
    finally:
        doc.close()
    return pages


def extract_shareholders_llm(pdf_path=None, text: str | None = None) -> dict | None:
    """Extract a shareholder table via Claude. Returns None if unavailable/failed."""
    ok, _ = llm_available()
    if not ok:
        return None
    import anthropic

    model = os.environ.get("HANDELSREGISTER_LLM_MODEL", "claude-opus-4-8")
    content: list[dict] = []

    images: list[bytes] = []
    if pdf_path:
        try:
            images = _render_pages(pdf_path)
        except Exception:  # noqa: BLE001 - fall back to text if rendering fails
            images = []
    for png in images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png",
                       "data": base64.standard_b64encode(png).decode()},
        })

    instruction = _INSTRUCTION
    if text and not images:
        instruction += "\n\nDOCUMENT TEXT:\n" + text[:120_000]
    content.append({"type": "text", "text": instruction})

    try:
        client = anthropic.Anthropic()
        with client.messages.stream(
            model=model,
            max_tokens=16000,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        ) as stream:
            message = stream.get_final_message()
    except Exception:  # noqa: BLE001 - any API failure -> caller keeps the deterministic result
        return None

    raw = next((b.text for b in message.content if b.type == "text"), "")
    try:
        data = json.loads(raw)
    except ValueError:
        return None

    shareholders = data.get("shareholders", [])
    return {
        "shareholders": shareholders,
        "stammkapital_eur": data.get("stammkapital_eur"),
        "confidence": "high" if shareholders else "low",
        "method": f"llm:{model}" + ("+vision" if images else "+text"),
    }
