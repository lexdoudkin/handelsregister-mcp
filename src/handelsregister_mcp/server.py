"""MCP server exposing the German commercial register (handelsregister.de) to agents.

Tools:
    search_company      - keyword search (all / at-least-one / exact match)
    get_company         - convenience: exact-name lookup, returns the best match
    fetch_document      - download an extract/document (AD, CD, HD, DK, SI, ...) for a hit
    rate_limit_status   - inspect the remaining hourly request budget

All portal-touching tools consume from a shared 60-requests/hour budget, in line
with the handelsregister.de terms of use. Configure with HANDELSREGISTER_MAX_PER_HOUR.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .client import (
    DOCUMENT_TYPES,
    KEYWORD_OPTIONS,
    HandelsregisterClient,
    RegisterError,
)
from .ratelimit import RateLimiter, RateLimitError

mcp = FastMCP("handelsregister")

_max_per_hour = int(os.environ.get("HANDELSREGISTER_MAX_PER_HOUR", "60"))
_download_dir = (
    Path(os.environ["HANDELSREGISTER_DOWNLOAD_DIR"])
    if os.environ.get("HANDELSREGISTER_DOWNLOAD_DIR")
    else None
)
_limiter = RateLimiter(max_per_hour=_max_per_hour)


def _new_client() -> HandelsregisterClient:
    return HandelsregisterClient(download_dir=_download_dir)


@mcp.tool()
def search_company(keywords: str, match: str = "all", max_results: int = 20) -> dict:
    """Search the German commercial register (Handelsregister) for companies.

    Args:
        keywords: Company name or search terms. Wildcards `*` and `?` are supported.
        match: How keywords are matched — "all" (contains every keyword, default),
            "min" (contains at least one), or "exact" (exact company name).
        max_results: Cap on returned rows (the portal page holds up to ~100).

    Returns a dict with the query echo, a result count, the remaining hourly request
    budget, and `results`: a list of companies with name, court, register_number,
    state, status, historical names, and `available_documents` (the document types
    that can be passed to `fetch_document`).
    """
    if match not in KEYWORD_OPTIONS:
        return {"error": f"match must be one of {sorted(KEYWORD_OPTIONS)}"}
    try:
        _limiter.check_and_consume()
    except RateLimitError as exc:
        return {"error": str(exc), "retry_after_seconds": exc.retry_after_seconds}

    client = _new_client()
    try:
        results = client.search(keywords, match=match)
    except RegisterError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - surface portal/markup failures to the agent
        return {"error": f"Portal request failed: {exc}"}

    response = {
        "query": {"keywords": keywords, "match": match},
        "count": len(results),
        "results": results[:max_results],
        "rate_limit": _limiter.status(),
    }
    # Surface portal hints (e.g. "min mode needs an extra filter") when nothing matched.
    if not results and client.messages:
        response["portal_messages"] = client.messages
    return response


@mcp.tool()
def get_company(name: str) -> dict:
    """Look up a single company by its exact name and return the best match.

    Convenience wrapper over `search_company` with match="exact". Use this when you
    already know the precise company name and just want one record (including the
    document types available for `fetch_document`).
    """
    try:
        _limiter.check_and_consume()
    except RateLimitError as exc:
        return {"error": str(exc), "retry_after_seconds": exc.retry_after_seconds}

    try:
        results = _new_client().search(name, match="exact")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Portal request failed: {exc}"}

    if not results:
        return {"found": False, "query": name, "rate_limit": _limiter.status()}
    return {"found": True, "company": results[0], "rate_limit": _limiter.status()}


@mcp.tool()
def fetch_document(keywords: str, document_type: str = "AD", match: str = "exact",
                   result_index: int = 0) -> dict:
    """Retrieve a register document/extract for a company and return its text.

    Runs a search, picks `result_index` from the hits, then downloads the requested
    document type from that same portal session. Document types:
        AD - current extract        CD - chronological extract
        HD - historical extract     DK - filed documents register
        SI - structured XML data    VÖ - announcements    UT - holder data

    Returns the local file `path`, `content_type`, `size_bytes`, and (for PDF/XML)
    extracted `text`. Document retrieval is the most fragile part of the portal flow;
    if it fails, the error explains what happened.
    """
    document_type = document_type.upper()
    if document_type not in DOCUMENT_TYPES:
        return {"error": f"document_type must be one of {sorted(DOCUMENT_TYPES)}"}
    try:
        _limiter.check_and_consume()
    except RateLimitError as exc:
        return {"error": str(exc), "retry_after_seconds": exc.retry_after_seconds}

    client = _new_client()
    try:
        results = client.search(keywords, match=match)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Portal search failed: {exc}"}

    if not results:
        return {"error": f"No company found for {keywords!r} (match={match})."}
    if result_index >= len(results):
        return {"error": f"result_index {result_index} out of range (got {len(results)} hits)."}

    target = results[result_index]
    try:
        document = client.fetch_document(target["row_index"], document_type)
    except (RegisterError, ValueError) as exc:
        return {"error": str(exc), "company": target}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Document download failed: {exc}", "company": target}

    return {"company": target, "document": document, "rate_limit": _limiter.status()}


@mcp.tool()
def rate_limit_status() -> dict:
    """Report the remaining handelsregister.de request budget for this hour."""
    return _limiter.status()


def main() -> None:
    """Console entry point — runs the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
