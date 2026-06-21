"""Optional OCR fallback for image-only (scanned) PDFs.

Many handelsregister filings — older Gesellschafterlisten, annual accounts,
pre-digital articles — are scanned images with no embedded text layer, so
``pypdf`` extracts nothing from them. When OCR is available (PyMuPDF to rasterise
+ Tesseract with a German language pack) we render each page and OCR it.

All OCR dependencies are OPTIONAL. If any is missing, ``ocr_available`` reports
why and callers fall back to whatever text layer exists — nothing crashes.
Install with: ``pip install handelsregister-mcp[ocr]`` (plus the system Tesseract
binary and its ``deu`` language pack, e.g. ``brew install tesseract tesseract-lang``).
"""

from __future__ import annotations

import io
from pathlib import Path


def ocr_available() -> tuple[bool, str]:
    """Return (is_available, reason). Reason explains what's missing if not."""
    try:
        import fitz  # noqa: F401  (PyMuPDF)
    except ImportError:
        return False, "PyMuPDF not installed (pip install handelsregister-mcp[ocr])"
    try:
        import pytesseract
    except ImportError:
        return False, "pytesseract not installed (pip install handelsregister-mcp[ocr])"
    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:  # noqa: BLE001 - tesseract binary missing/broken
        return False, f"Tesseract binary not found: {exc}"
    return True, "ok"


def ocr_pdf(path: str | Path, lang: str = "deu", dpi: int = 300, max_pages: int = 40) -> str:
    """Rasterise a PDF and OCR every page. Raises if OCR deps are unavailable."""
    ok, reason = ocr_available()
    if not ok:
        raise RuntimeError(reason)

    import fitz
    import pytesseract
    from PIL import Image

    doc = fitz.open(str(path))
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pages: list[str] = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(matrix=matrix)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            pages.append(pytesseract.image_to_string(img, lang=lang))
    finally:
        doc.close()
    return "\n".join(pages).strip()
