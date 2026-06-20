"""handelsregister-mcp: an MCP server for the German commercial register."""

from .client import DOCUMENT_TYPES, HandelsregisterClient, RegisterError

__version__ = "0.1.0"
__all__ = ["HandelsregisterClient", "RegisterError", "DOCUMENT_TYPES", "__version__"]
