"""camelot-api: PDF table extraction RPC service for Rust interop."""

from __future__ import annotations

__version__ = "0.1.0"


def main() -> None:
    """Entry point for console_scripts. Starts the HTTP server."""
    from camelot_api.__main__ import main as _main

    _main()
