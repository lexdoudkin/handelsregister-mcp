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
    # "lassungen" from "Zweignieder-\nlassungen"). The domestic business address is
    # the next line(s) up to and including the first postal code — then stop, so
    # foreign branches (Zweigniederlassungen with their own EUIDs) aren't absorbed.
    if sections.get("seat"):
        lines = [l.strip() for l in sections["seat"].splitlines() if l.strip()]
        town_idx = None
        for i, l in enumerate(lines):
            if re.match(r"^[A-ZÄÖÜ]", l) and not re.search(
                r"Geschäftsanschrift|empfangsberechtigt|Zweignieder", l
            ):
                company["registered_office"] = _strip_trailing_marker(l)
                town_idx = i
                break
        if town_idx is not None:
            addr_lines: list[str] = []
            for l in lines[town_idx + 1:]:
                if re.search(r"EUID|Zweigniederlassung|Business Register|Handelsregister Abteilung", l, re.I):
                    break
                addr_lines.append(l)
                if re.search(r"\b\d{5}\b", l):  # postal code ends the domestic address
                    break
            addr = _strip_trailing_marker(", ".join(addr_lines))
            if addr and re.search(r"\d{5}|straße|str\.|platz|weg|allee|ring|campus", addr, re.I):
                company["business_address"] = addr

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

def _map_shareholder_columns(cells: list[str]) -> dict:
    """Map a (bilingual) header row to column roles by keyword."""
    roles: dict[str, int] = {}
    for i, cell in enumerate(cells):
        c = (cell or "").lower()
        if "gesellschafter" in c or "shareholder" in c:
            roles.setdefault("name", i)
        elif "summe der nennbet" in c or "total nominal" in c:
            roles.setdefault("total_nominal", i)
        elif "gesamt" in c or "total percentage" in c:
            roles.setdefault("total_percent", i)
        elif "lfd" in c or "seq" in c or "nr. der" in c:
            roles.setdefault("shares", i)
    return roles


def parse_gesellschafterliste_pdf(path) -> dict:
    """Coordinate-aware shareholder extraction using pdfplumber's table model.

    Reconstructs columns from the PDF's ruling lines / text positions, so it
    handles multi-column and bilingual lists (where flat text extraction garbles
    the reading order). Falls back to {} when pdfplumber is unavailable or the PDF
    has no detectable table (e.g. scanned images).
    """
    try:
        import pdfplumber
    except ImportError:
        return {"shareholders": [], "confidence": "low", "method": "pdfplumber-unavailable"}

    shareholders: list[dict] = []
    roles: dict | None = None
    stammkapital = None
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    for row in table or []:
                        cells = [(c or "").replace("\n", " ").strip() for c in row]
                        joined = " ".join(cells).lower()
                        if "stammkapital" in joined or "share capital" in joined:
                            sk = re.search(r"([\d.]+,\d{2})\s*€", joined)
                            if sk and stammkapital is None:
                                stammkapital = _money_to_float(sk.group(1))
                        if roles is None and ("gesellschafter" in joined or "shareholder" in joined):
                            roles = _map_shareholder_columns(cells)
                            continue
                        if not roles:
                            continue
                        name_cell = _cell(cells, roles.get("name"))
                        total = _cell(cells, roles.get("total_nominal"))
                        if not name_cell or not re.search(r"\d", total):
                            continue
                        party = _parse_shareholder_party(name_cell)
                        shareholders.append({
                            "shareholder": party["name"],
                            "type": party["type"],
                            "city": party["city"],
                            "register": party["register"],
                            "date_of_birth": party["date_of_birth"],
                            "shares": _clean(_cell(cells, roles.get("shares"))) or None,
                            "nominal_total_eur": _money_to_float(total),
                            "percent": _clean(_cell(cells, roles.get("total_percent"))) or None,
                        })
    except Exception as exc:  # noqa: BLE001 - any pdfplumber failure -> let caller fall back
        return {"shareholders": [], "confidence": "low", "method": f"pdfplumber-error: {exc}"}

    confidence = "high" if shareholders else "low"
    return {
        "shareholders": shareholders,
        "stammkapital_eur": stammkapital or (
            round(sum(s["nominal_total_eur"] for s in shareholders if s["nominal_total_eur"]), 2)
            or None
        ),
        "confidence": confidence,
        "method": "pdfplumber",
    }


def _cell(cells: list[str], idx: int | None) -> str:
    return cells[idx] if idx is not None and 0 <= idx < len(cells) else ""


_GERMAN_MONTHS = {
    "januar": "01", "februar": "02", "märz": "03", "april": "04", "mai": "05",
    "juni": "06", "juli": "07", "august": "08", "september": "09",
    "oktober": "10", "november": "11", "dezember": "12",
}


def _parse_shareholder_party(cell: str) -> dict:
    """Split a (bilingual) shareholder cell into name/city/register/type/DOB.

    Cells look like: "<Name> mit Sitz in <Stadt> with registered office in <City>
    <Registergericht> <num> ..." for companies, or "<Name> geboren am <Datum>
    born on ... wohnhaft in <Stadt> ..." for natural persons.
    """
    text = re.sub(r"\s+", " ", cell.replace("\n", " ")).strip()

    # Name is everything before the first locality/birth marker (German or English).
    name = re.split(
        r"\bmit Sitz\b|\bwith registered office\b|\bgeboren am\b|\bborn on\b|"
        r"\bwohnhaft\b|\bhandelnd durch\b|\bvertreten durch\b",
        text,
    )[0].strip(" ,")

    is_person = bool(re.search(r"\bgeboren am\b|\bborn on\b", text))

    city = None
    cm = (re.search(r"mit Sitz (?:in|auf)\s+(.+?)\s+with registered office", text)
          or re.search(r"wohnhaft in\s+(.+?)\s+resident in", text))
    if cm:
        city = cm.group(1).strip(" ,")

    register = None
    rm = re.search(r"Amtsgericht\s+[\wäöüß./-]+\s+(?:HRA|HRB|GnR|VR|PR)\s*\d+\s*[A-Z]{0,2}\b", text)
    if rm:
        register = rm.group(0).strip()

    dob = None
    dm = re.search(r"geboren am\s+(\d{1,2})\.\s*([A-Za-zäöü]+)\s+(\d{4})", text)
    if dm and dm.group(2).lower() in _GERMAN_MONTHS:
        dob = f"{dm.group(3)}-{_GERMAN_MONTHS[dm.group(2).lower()]}-{int(dm.group(1)):02d}"

    return {
        "name": _clean(name) or None,
        "type": "person" if is_person else "company",
        "city": city,
        "register": register,
        "date_of_birth": dob,
    }


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


def extract_shareholders(pdf_path, text: str, text_source: str = "text-layer") -> dict:
    """Layered shareholder extraction, best engine first.

    1. coordinate-aware table parsing (pdfplumber) — best for digital, multi-column
       and bilingual lists where flat text loses the column structure;
    2. flat-text line heuristic — the simple notarial template;
    3. give up cleanly — return the best partial result plus `raw_text`, flagged
       low so the caller (or an LLM fallback) can take over.
    """
    table = parse_gesellschafterliste_pdf(pdf_path)
    if table.get("confidence") == "high":
        table["list_date"] = _iso_date(text or "")
        return table

    heur = parse_gesellschafterliste(text or "")
    if heur.get("confidence") == "high":
        heur["method"] = "line-heuristic"
        return heur

    best = table if table.get("shareholders") else heur
    best["method"] = best.get("method", "none")
    best["confidence"] = "low"
    best["raw_text"] = text
    best["text_source"] = text_source
    return best


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
