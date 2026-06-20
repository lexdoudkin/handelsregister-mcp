"""Client for the German commercial register portal (https://www.handelsregister.de).

There is **no official API**. The portal is a JSF/PrimeFaces web application, so
every request must carry the server-side ViewState and the session cookie through
a multi-step form flow:

    1. GET  https://www.handelsregister.de            -> establishes session, loads `naviForm`
    2. POST naviForm (erweiterteSucheLink)            -> opens the advanced search, loads `form`
    3. POST form (keywords + options [+ filters])     -> renders the results grid (`ergebnissForm`)
    4. POST ergebnissForm (document command link)     -> streams the requested document

`mechanize` is used because it parses every hidden field (including
`javax.faces.ViewState`) out of the rendered form and resubmits them
automatically — which is exactly what JSF requires.

The search flow is adapted from the community project bundesAPI/handelsregister
(Apache-2.0 in the `deutschland` package). Document retrieval is layered on top.
"""

from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path

import mechanize
from bs4 import BeautifulSoup

BASE_URL = "https://www.handelsregister.de"

# keyword match mode -> portal radio value
KEYWORD_OPTIONS = {
    "all": "1",    # entries containing all keywords
    "min": "2",    # entries containing at least one keyword
    "exact": "3",  # entries matching the exact company name
}

# document/extract types offered per result row
DOCUMENT_TYPES = {
    "AD": "Aktueller Abdruck (current extract)",
    "CD": "Chronologischer Abdruck (chronological extract)",
    "HD": "Historischer Abdruck (historical extract)",
    "DK": "Dokumente (filed documents register)",
    "UT": "Unternehmensträgerdaten",
    "VÖ": "Veröffentlichungen (announcements)",
    "SI": "Strukturierte Inhalte (structured XML data)",
}

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/15.5 Safari/605.1.15"
)


class RegisterError(RuntimeError):
    """Raised when the portal cannot be queried or a document cannot be fetched."""


class HandelsregisterClient:
    """Stateful client. Create one per logical operation (search, then optionally
    fetch a document from that same result set)."""

    def __init__(self, download_dir: Path | None = None, debug: bool = False):
        self.download_dir = download_dir or (
            Path(tempfile.gettempdir()) / "handelsregister_mcp_downloads"
        )
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.browser = mechanize.Browser()
        self.browser.set_debug_http(debug)
        self.browser.set_debug_responses(debug)
        self.browser.set_handle_robots(False)
        self.browser.set_handle_equiv(True)
        self.browser.set_handle_gzip(True)
        self.browser.set_handle_refresh(False)
        self.browser.set_handle_redirect(True)
        self.browser.set_handle_referer(True)
        self.browser.addheaders = [
            ("User-Agent", _USER_AGENT),
            ("Accept-Language", "en-GB,en;q=0.9"),
            ("Accept-Encoding", "gzip, deflate, br"),
            ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
            ("Connection", "keep-alive"),
        ]

        # row_index -> { "AD": "<jsf control id>", ... } for document retrieval
        self._doc_controls: dict[int, dict[str, str]] = {}
        self._results_html: str | None = None
        # portal validation/info messages from the last search (e.g. "min keyword
        # mode requires an additional filter"), surfaced when there are no results
        self.messages: list[str] = []

    # ------------------------------------------------------------------ search

    def search(
        self,
        keywords: str,
        match: str = "all",
        *,
        register_type: str | None = None,
        register_number: str | None = None,
        postal_code: str | None = None,
        city: str | None = None,
    ) -> list[dict]:
        """Run an advanced search and return the parsed result rows.

        `match` is one of "all", "min", "exact". The remaining filters are applied
        only if the live form exposes the corresponding control (the portal markup
        changes occasionally), otherwise they are silently ignored.
        """
        if match not in KEYWORD_OPTIONS:
            raise ValueError(f"match must be one of {sorted(KEYWORD_OPTIONS)}")

        self.browser.open(BASE_URL, timeout=20)

        # Step 2: open the advanced search via the navigation form.
        self.browser.select_form(name="naviForm")
        self.browser.form.new_control(
            "hidden", "naviForm:erweiterteSucheLink",
            {"value": "naviForm:erweiterteSucheLink"},
        )
        self.browser.form.new_control("hidden", "target", {"value": "erweiterteSucheLink"})
        self.browser.submit()

        # Step 3: fill and submit the advanced search form.
        self.browser.select_form(name="form")
        self.browser["form:schlagwoerter"] = keywords
        self.browser["form:schlagwortOptionen"] = [KEYWORD_OPTIONS[match]]

        self._safe_set("form:registerArt_input", register_type)
        self._safe_set("form:registerNummer", register_number)
        self._safe_set("form:postleitzahl", postal_code)
        self._safe_set("form:ort", city)

        # Submit via the named search button so JSF knows which action fired.
        response = self.browser.submit(name="form:btnSuche")
        self._results_html = response.read().decode("utf-8", errors="replace")
        return self._parse_results(self._results_html)

    def _safe_set(self, control_name: str, value: str | None) -> None:
        if not value:
            return
        try:
            self.browser[control_name] = value
        except mechanize.ControlNotFoundError:
            pass  # filter not available in the current portal markup; ignore

    # --------------------------------------------------------------- documents

    def fetch_document(self, row_index: int, document_type: str) -> dict:
        """Download a document/extract for a previously searched result row.

        Must be called on the same client instance that ran `search()` (it reuses
        the live JSF session and ViewState). Returns metadata plus the on-disk path
        of the downloaded file and, for PDFs, extracted text.

        NOTE: document retrieval depends on PrimeFaces command-link ids parsed from
        the live results page. It is the most fragile part of the portal flow and
        may need adjustment if the markup changes — search is the battle-tested path.
        """
        document_type = document_type.upper()
        if document_type not in DOCUMENT_TYPES:
            raise ValueError(f"document_type must be one of {sorted(DOCUMENT_TYPES)}")

        controls = self._doc_controls.get(row_index)
        if not controls:
            raise RegisterError(
                f"No result row {row_index} in the last search, or it exposed no "
                f"document links. Run search() first and pick a valid row index."
            )
        control_id = controls.get(document_type)
        if not control_id:
            raise RegisterError(
                f"Document type {document_type} is not offered for row {row_index}. "
                f"Available: {sorted(controls)}"
            )

        # PrimeFaces command link -> non-ajax JSF postback that streams the file.
        self.browser.select_form(name="ergebnissForm")
        self.browser.form.new_control("hidden", "javax.faces.source", {"value": control_id})
        self.browser.form.new_control("hidden", control_id, {"value": control_id})
        response = self.browser.submit()

        data = response.read()
        info = response.info()
        content_type = info.get("Content-Type", "")
        disposition = info.get("Content-Disposition", "")

        if "text/html" in content_type and b"javax.faces" not in data[:200]:
            raise RegisterError(
                "Portal returned an HTML page instead of a document — the document "
                "command-link flow likely needs adjustment for the current markup."
            )

        ext = _guess_extension(content_type, disposition)
        filename = f"{document_type}_{int(time.time())}{ext}"
        path = self.download_dir / filename
        path.write_bytes(data)

        result = {
            "document_type": document_type,
            "description": DOCUMENT_TYPES[document_type],
            "content_type": content_type or "application/octet-stream",
            "path": str(path),
            "size_bytes": len(data),
        }
        if ext == ".pdf":
            result["text"] = _extract_pdf_text(path)
        elif ext in (".xml", ".txt"):
            result["text"] = data.decode("utf-8", errors="replace")
        return result

    # ----------------------------------------------------------------- parsing

    def _parse_results(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        self.messages = _extract_messages(soup)

        # The results table itself carries no stable id, but its data rows are the
        # only ones tagged with `data-ri` (the PrimeFaces row index), so select those
        # directly rather than guessing the enclosing table.
        results: list[dict] = []
        for row in soup.find_all("tr", attrs={"data-ri": True}):
            index = int(row["data-ri"])
            company, controls = _parse_row(row, index)
            self._doc_controls[index] = controls
            results.append(company)
        return results


def _parse_row(row, index: int) -> tuple[dict, dict[str, str]]:
    cells = [cell.get_text(strip=True) for cell in row.find_all("td")]
    court = cells[1] if len(cells) > 1 else ""
    state = cells[3] if len(cells) > 3 else None

    reg_match = re.search(r"(HRA|HRB|GnR|VR|PR)\s*\d+(\s+[A-Z]+)?(?!\w)", court)
    register_number = reg_match.group(0) if reg_match else None

    # The responsive layout prepends the state to the court cell; drop the duplicate.
    if state and court.startswith(state):
        court = court[len(state):].strip()

    company = {
        "row_index": index,
        "name": cells[2] if len(cells) > 2 else None,
        "court": court,
        "register_number": register_number,
        "state": state,
        "status": cells[4].strip() if len(cells) > 4 else None,
        "history": [],
    }

    # historical names/seats start after the fixed columns, in (name, location) pairs
    for i in range(8, len(cells) - 1, 3):
        if any(marker in cells[i] for marker in ("Branches", "Niederlassungen")):
            break
        company["history"].append({"name": cells[i], "location": cells[i + 1]})

    # Discover the document command-links in this row (PrimeFaces anchors). Their
    # ids look like `ergebnissForm:selectedSuchErgebnisFormTable:0:j_idt228:0:fade_`.
    controls: dict[str, str] = {}
    for anchor in row.find_all("a"):
        label = anchor.get_text(strip=True).upper()
        if label in DOCUMENT_TYPES and anchor.get("id"):
            controls[label] = anchor["id"]
    company["available_documents"] = sorted(controls)
    return company, controls


def _extract_messages(soup: BeautifulSoup) -> list[str]:
    """Pull PrimeFaces info/warn/error message text out of the rendered page."""
    messages: list[str] = []
    selectors = (
        ".ui-messages-error-detail, .ui-messages-warn-detail, "
        ".ui-messages-info-detail, .ui-message-error-detail"
    )
    for el in soup.select(selectors):
        text = el.get_text(strip=True)
        if text and text not in messages:
            messages.append(text)
    if not messages:
        for el in soup.select(".ui-messages li, .ui-messages span"):
            text = el.get_text(strip=True)
            if text and text not in messages:
                messages.append(text)
    return messages


def _guess_extension(content_type: str, disposition: str) -> str:
    name_match = re.search(r'filename="?([^";]+)', disposition or "")
    if name_match and "." in name_match.group(1):
        return "." + name_match.group(1).rsplit(".", 1)[1].strip().lower()
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return ".pdf"
    if "xml" in ct:
        return ".xml"
    if "zip" in ct:
        return ".zip"
    if "text" in ct:
        return ".txt"
    return ".bin"


def _extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:  # noqa: BLE001 - best-effort text extraction
        return f"(could not extract PDF text: {exc})"
