"""Turn handelsregister documents into structured data.

Every document the portal hands back is unstructured (PDF) or semi-structured
(XJustiz XML). These parsers lift them into plain dicts/rows so the MCP tools can
return tables instead of raw text:

    parse_register_extract(text)   AD/CD/HD print -> company fields + management table
    parse_xjustiz_si(xml)          SI XJustiz XML  -> company fields + parties table
    parse_gesellschafterliste(text)  shareholder-list PDF -> shareholders table

`to_markdown_table` / `company_to_markdown` render any of these as inline tables.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

# ----------------------------------------------------------------- helpers


def _money_to_float(raw: str) -> float | None:
    """'1.000,00 EUR' / '25.000,00' -> 1000.0 (German number format)."""
    m = re.search(r"[\d.]+(?:,\d+)?", raw or "")
    if not m:
        return None
    num = m.group(0).replace(".", "").replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def _iso_date(raw: str) -> str | None:
    """'21.03.1999' -> '1999-03-21'; passes through values already in ISO form."""
    raw = raw or ""
    iso = re.search(r"\d{4}-\d{2}-\d{2}", raw)
    if iso:
        return iso.group(0)
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", raw)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _clean(text: str) -> str:
    return re.sub(r"[ \t]*\n[ \t]*", " ", (text or "").strip()).strip()


def _strip_trailing_marker(text: str) -> str:
    """Drop a section marker that bled in from the next field ('... 3.', '... b)')."""
    text = (text or "").strip()
    text = re.sub(r"\s+\d+\.\s*[a-z]?\)?\s*$", "", text)
    text = re.sub(r"\s+[a-z]\)\s*$", "", text)
    return text.strip()


# ---------------------------------------------------- register extract (AD/CD/HD)

# Standardised field labels of a German register print, in the order they appear.
# We locate each label and slice the text between consecutive labels, which is
# robust to the exact paragraph numbering (which differs HRB vs HRA vs VR).
_EXTRACT_LABELS: list[tuple[str, str]] = [
    ("entries_count", r"Anzahl der bisherigen Eintragungen"),
    ("name", r"(?<![a-zäöü])Firma(?![a-zäöü])"),
    ("seat", r"Sitz, Niederlassung[^\n]*"),
    ("purpose", r"Gegenstand des Unternehmens"),
    ("capital", r"Grund-?\s*oder\s*Stammkapital|Stammkapital|Grundkapital"),
    ("representation_rule", r"Allgemeine Vertretungsregelung"),
    ("management", r"Vorstand, Leitungsorgan[^\n]*|Inhaber\b|Persönlich haftende[r]? Gesellschafter"),
    ("legal_form", r"Rechtsform, Beginn[^\n]*"),
    ("last_entry_date", r"Tag der letzten Eintragung"),
]

_PERSON_RE = re.compile(
    r"^(?P<name>.+?),\s*\*\s*(?P<dob>\d{2}\.\d{2}\.\d{4})(?:,\s*(?P<city>[^\n]+?))?\s*$",
    re.MULTILINE,
)


def parse_register_extract(text: str) -> dict:
    """Parse an AD/CD/HD register print into structured company data."""
    text = text or ""
    # Find the position of every label that is present, in document order.
    hits: list[tuple[int, int, str]] = []
    for key, pattern in _EXTRACT_LABELS:
        m = re.search(pattern, text)
        if m:
            hits.append((m.start(), m.end(), key))
    hits.sort()

    sections: dict[str, str] = {}
    for i, (_, end, key) in enumerate(hits):
        nxt = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        sections[key] = text[end:nxt].strip()

    register_number = None
    rn = re.search(r"(HRA|HRB|GnR|VR|PR)\s*\d+(?:\s*[A-Z]+)?", text)
    if rn:
        register_number = _clean(rn.group(0))

    company: dict = {
        "name": _clean(sections.get("name", "").splitlines()[0]) if sections.get("name") else None,
        "register_number": register_number,
        "registered_office": None,
        "business_address": None,
        "purpose": _strip_trailing_marker(_clean(sections.get("purpose", ""))) or None,
        "capital": None,
        "capital_currency": None,
        "legal_form": None,
        "representation_rule": _strip_trailing_marker(_clean(sections.get("representation_rule", ""))) or None,
        "entries_count": None,
        "last_entry_date": _iso_date(sections.get("last_entry_date", "")),
        "management": [],
    }

    if sections.get("entries_count"):
        n = re.search(r"\d+", sections["entries_count"])
        company["entries_count"] = int(n.group(0)) if n else None

    # Seat block: the town is the first proper line (skip hyphenation remnants like
    # "lassungen" from "Zweignieder-\nlassungen"); an address line usually follows.
    if sections.get("seat"):
        lines = [l.strip() for l in sections["seat"].splitlines() if l.strip()]
        for l in lines:
            if re.match(r"^[A-ZÄÖÜ]", l) and not re.search(
                r"Geschäftsanschrift|empfangsberechtigt|Zweignieder", l
            ):
                company["registered_office"] = _strip_trailing_marker(l)
                break
        addr = [l for l in lines if re.search(r"\d{5}|straße|str\.|platz|weg|allee|campus|ring", l, re.I)]
        if addr:
            company["business_address"] = _strip_trailing_marker(", ".join(addr))

    if sections.get("capital"):
        company["capital"] = _money_to_float(sections["capital"])
        cur = re.search(r"\b(EUR|DEM|USD)\b", sections["capital"])
        company["capital_currency"] = cur.group(0) if cur else ("EUR" if company["capital"] else None)

    if sections.get("legal_form"):
        company["legal_form"] = _strip_trailing_marker(_clean(sections["legal_form"].splitlines()[0])) or None
        gv = re.search(r"Gesellschaftsvertrag vom:?\s*([\d.]+)", sections["legal_form"])
        am = re.search(r"(?:Zuletzt geändert|geändert) am:?\s*([\d.]+)", sections["legal_form"])
        if gv:
            company["articles_of_association_date"] = _iso_date(gv.group(1))
        if am:
            company["last_amended_date"] = _iso_date(am.group(1))

    # Management persons (Geschäftsführer / Vorstand / Prokuristen).
    mgmt_block = sections.get("management", "")
    for m in _PERSON_RE.finditer(mgmt_block):
        name = _clean(m.group("name"))
        # Drop any leading representation phrase that bled onto the name line.
        name = re.sub(r"^.*?(?:vertret(?:en|ung)|befugnis|abzuschließen)\s*", "", name, flags=re.I).strip()
        company["management"].append({
            "name": name,
            "date_of_birth": _iso_date(m.group("dob")),
            "city": _clean(m.group("city") or "") or None,
        })

    return company


# ------------------------------------------------------------- XJustiz SI XML

_XJ_NS = {"tns": "http://www.xjustiz.de"}


def _xj_text(el, *tags: str) -> str | None:
    for tag in tags:
        found = el.find(f".//tns:{tag}", _XJ_NS)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return None


# XJustiz register role codes (GDS.Beteiligtenrolle / register subset). Only the
# common ones are mapped; unmapped codes are returned as "role_<code>".
_XJ_ROLE_CODES = {
    "270": "Rechtsträger",
    "273": "Geschäftsführer",
    "274": "Vorstand",
    "275": "Prokurist",
    "276": "Aufsichtsrat",
    "279": "Inhaber",
    "280": "Liquidator",
    "287": "Gesellschaft",
    "288": "Persönlich haftender Gesellschafter",
}


def _xj_find(el, path: str):
    return el.find(path, _XJ_NS) if el is not None else None


def _xj_path_text(el, path: str) -> str | None:
    found = _xj_find(el, path)
    return found.text.strip() if found is not None and (found.text or "").strip() else None


def parse_xjustiz_si(xml: str | bytes) -> dict:
    """Parse the SI (Strukturierte Inhalte) XJustiz register message into a dict.

    Uses the concrete XJustiz 0400 register paths to extract company core data
    plus the involved parties (Beteiligte) — the most useful structured slice.
    """
    if isinstance(xml, bytes):
        xml = xml.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return {"error": f"invalid XJustiz XML: {exc}"}

    result: dict = {
        "name": None, "legal_form_code": None, "register_number": None,
        "register_type": None, "euid": None, "registered_office": None,
        "business_address": None, "capital": None, "capital_currency": None,
        "purpose": None, "parties": [],
    }

    # Map role number -> human role via the <beteiligung><rolle> entries.
    role_by_nr: dict[str, str] = {}
    for rolle in root.findall(".//tns:beteiligung/tns:rolle", _XJ_NS):
        nr = _xj_path_text(rolle, "tns:rollennummer") or _xj_path_text(rolle, "tns:nr")
        code = _xj_path_text(rolle, "tns:rollenbezeichnung/tns:code")
        if nr and code:
            role_by_nr[nr] = _XJ_ROLE_CODES.get(code, f"role_{code}")

    # The subject company (first organisation under a beteiligter).
    org = root.find(".//tns:beteiligter/tns:auswahl_beteiligter/tns:organisation", _XJ_NS)
    if org is not None:
        result["name"] = _xj_path_text(org, "tns:bezeichnung/tns:bezeichnung.aktuell") \
            or _xj_path_text(org, "tns:kurzbezeichnung")
        result["legal_form_code"] = _xj_path_text(org, ".//tns:angabenZurRechtsform/tns:rechtsform/tns:code")
        result["registered_office"] = _xj_path_text(org, "tns:sitz/tns:ort")
        result["register_number"] = _xj_path_text(org, ".//tns:registereintragung/tns:registernummer")
        result["register_type"] = _xj_path_text(org, ".//tns:registerart/tns:code")
        result["euid"] = _xj_path_text(org, ".//tns:registereintragung/tns:euid")
        an = _xj_find(org, "tns:anschrift")
        if an is not None:
            parts = [
                " ".join(p for p in (_xj_path_text(an, "tns:strasse"),
                                     _xj_path_text(an, "tns:hausnummer")) if p),
                " ".join(p for p in (_xj_path_text(an, "tns:postleitzahl"),
                                     _xj_path_text(an, "tns:ort")) if p),
            ]
            result["business_address"] = ", ".join(p for p in parts if p) or None

    # Register fach data: business purpose + share capital.
    result["purpose"] = _xj_path_text(root, ".//tns:basisdatenRegister/tns:gegenstand")
    kap = root.find(".//tns:kapitalgesellschaft/tns:kapital/tns:hoehe", _XJ_NS)
    if kap is not None:
        result["capital"] = _money_to_float(_xj_path_text(kap, "tns:zahl") or "")
        result["capital_currency"] = _xj_path_text(kap, ".//tns:waehrung/tns:code") or "EUR"

    # Parties: organisations + natural persons, with role where resolvable.
    for bet in root.findall(".//tns:beteiligter", _XJ_NS):
        nr = _xj_path_text(bet, "tns:beteiligtennummer")
        role = role_by_nr.get(nr)
        org_el = bet.find("./tns:auswahl_beteiligter/tns:organisation", _XJ_NS)
        per = bet.find("./tns:auswahl_beteiligter/tns:natuerlichePerson", _XJ_NS)
        if org_el is not None:
            result["parties"].append({
                "type": "organization", "role": role,
                "name": _xj_path_text(org_el, "tns:bezeichnung/tns:bezeichnung.aktuell")
                        or _xj_path_text(org_el, "tns:kurzbezeichnung"),
                "city": _xj_path_text(org_el, "tns:sitz/tns:ort"),
            })
        elif per is not None:
            title = _xj_path_text(per, "tns:vollerName/tns:titel")
            nachname = _xj_path_text(per, "tns:vollerName/tns:nachname")
            vorname = _xj_path_text(per, "tns:vollerName/tns:vorname")
            name = ", ".join(p for p in (nachname, " ".join(x for x in (title, vorname) if x)) if p.strip())
            result["parties"].append({
                "type": "person", "role": role, "name": name or None,
                "date_of_birth": _iso_date(_xj_path_text(per, "tns:geburt/tns:geburtsdatum") or ""),
                "city": _xj_path_text(per, "tns:anschrift/tns:ort"),
            })

    return result


# ----------------------------------------------------- Gesellschafterliste (PDF)

# A data row of the standard list pairs an amount (…€) with a percentage (…%).
_DATA_ROW_RE = re.compile(r"\d[\d.]*,\d{2}\s*€.*?\d+(?:,\d+)?\s*%")
_REGISTER_RE = re.compile(r"(?:AG|Amtsgericht)\s+.+?\b(?:HRA|HRB|GnR|VR|PR)\s*\d+\s*[A-Z]*", re.I)
_CHANGE_WORDS = re.compile(
    r"entstanden|Teilung|Abtretung|Übertragung|Kapitalerhöhung|Erstanmeldung|"
    r"unverändert|infolge|Neue Liste|geändert|Sonderrecht|Geschäftsanteil|Veränderung|Einziehung",
    re.I,
)


def parse_gesellschafterliste(text: str) -> dict:
    """Parse a shareholder list (Liste der Gesellschafter) into a table.

    Targets the standard notarial template (columns: lfd. Nummer · Nennbetrag ·
    %-Anteil · Summe der Nennbeträge · %-Anteil gesamt · Veränderung). Each
    shareholder block is the identity text *above* a numeric data row, parsed
    bottom-up: city, then register (for companies), then name. Always returns the
    raw text and a confidence flag so callers can fall back when layout is unusual.
    """
    text = text or ""
    # Join hyphenated line breaks: "haftungsbe-\nschränkt" -> "haftungsbeschränkt".
    joined = re.sub(r"(?<=[a-zäöüß])-\s*\n\s*(?=[a-zäöü])", "", text)
    lines = [l.strip() for l in joined.splitlines() if l.strip()]

    stammkapital = None
    sk = re.search(r"Stammkapital:?\s*([\d.]+,\d{2})\s*€", joined)
    if sk:
        stammkapital = _money_to_float(sk.group(1))

    # Index the data rows; everything before the first one is the header.
    data_idx = [i for i, l in enumerate(lines) if _DATA_ROW_RE.search(l)]
    shareholders: list[dict] = []
    prev = max([i for i, l in enumerate(lines)
                if re.search(r"Veränderung|Nennbetrag", l) and i < (data_idx[0] if data_idx else 0)],
               default=-1)

    for di in data_idx:
        block = [lines[j] for j in range(prev + 1, di)]
        prev = di
        # identity is at the bottom of the block; change-prose sits above it.
        city = register = None
        name_lines: list[str] = []
        idx = len(block) - 1
        if idx >= 0 and not _CHANGE_WORDS.search(block[idx]) and len(block[idx]) < 60:
            city = block[idx]; idx -= 1
        if idx >= 0 and _REGISTER_RE.search(block[idx]):
            register = _clean(block[idx]); idx -= 1
        while idx >= 0 and not _CHANGE_WORDS.search(block[idx]):
            name_lines.insert(0, block[idx]); idx -= 1
        name = _clean(" ".join(name_lines)) or None

        row = lines[di]
        lfd = re.match(r"\s*([\d.]+(?:\s*[-–]\s*[\d.]+)?)", row)
        amounts = re.findall(r"([\d.]+,\d{2})\s*€", row)
        percents = re.findall(r"(\d+(?:,\d+)?)\s*%", row)
        shareholders.append({
            "shareholder": name,
            "type": "company" if register else "person",
            "register": register,
            "city": city,
            "shares": _clean(lfd.group(1)) if lfd else None,
            "nominal_total_eur": _money_to_float(amounts[-1]) if amounts else None,
            "percent": (percents[-1] + "%") if percents else None,
        })

    # Sanity check: a clean parse has one tidy identity per data row. If a name
    # absorbed a register number or runs very long, the layout was likely garbled
    # (typical of OCR'd scans whose reading order differs from the visual table) —
    # flag it low so callers fall back to raw_text instead of trusting the table.
    garbled = any(
        s["shareholder"] and (len(s["shareholder"]) > 70 or _REGISTER_RE.search(s["shareholder"]))
        for s in shareholders
    )
    confidence = "high" if (shareholders and not garbled) else "low"
    return {
        "list_date": _iso_date(joined),
        "stammkapital_eur": stammkapital,
        "shareholders": shareholders,
        "confidence": confidence,
        "raw_text": text,
    }


# ----------------------------------------------------------------- rendering


def to_markdown_table(rows: list[dict], columns: list[str] | None = None) -> str:
    """Render a list of dicts as a GitHub-flavoured markdown table."""
    if not rows:
        return "_(no rows)_"
    columns = columns or list(rows[0].keys())
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        cells = []
        for col in columns:
            val = row.get(col, "")
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            cells.append("" if val is None else str(val).replace("|", "\\|"))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, sep, *body])


def company_to_markdown(company: dict) -> str:
    """Render parsed company core data + management as inline tables."""
    fields = [
        ("Name", company.get("name")),
        ("Register", company.get("register_number")),
        ("Legal form", company.get("legal_form")),
        ("Seat", company.get("registered_office")),
        ("Address", company.get("business_address")),
        ("Capital", f"{company['capital']:.2f} {company.get('capital_currency') or ''}".strip()
                    if company.get("capital") else None),
        ("Purpose", company.get("purpose")),
        ("Entries", company.get("entries_count")),
        ("Last entry", company.get("last_entry_date")),
    ]
    rows = [{"Field": k, "Value": v} for k, v in fields if v not in (None, "")]
    out = to_markdown_table(rows, ["Field", "Value"])
    if company.get("management"):
        out += "\n\n**Management**\n\n" + to_markdown_table(
            company["management"], ["name", "date_of_birth", "city"]
        )
    return out
