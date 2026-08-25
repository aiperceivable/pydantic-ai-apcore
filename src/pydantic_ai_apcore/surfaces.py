"""Project registered modules onto the other apcore surfaces.

Once tools have been registered with :func:`register_toolset`, they are ordinary
apcore modules -- anything that can serve an apcore registry can serve them.
These helpers are thin, optional conveniences over the surface adapters, kept
behind extras so the base install stays minimal:

    pip install "pydantic-ai-apcore[mcp]"
    pip install "pydantic-ai-apcore[cli]"
"""

from __future__ import annotations

from typing import Any

__all__ = ["serve_cli", "serve_mcp"]

_MISSING = "{surface} support requires the '{extra}' extra:\n    pip install \"pydantic-ai-apcore[{extra}]\""


def serve_mcp(registry_or_executor: Any, **kwargs: Any) -> Any:
    """Serve the given registry or executor as an MCP server.

    Forwards to :func:`apcore_mcp.serve`; see that function for transport, auth,
    and approval options.

    Raises:
        ImportError: If the ``mcp`` extra is not installed.
    """
    try:
        from apcore_mcp import serve
    except ImportError as exc:  # pragma: no cover - exercised via the extra
        raise ImportError(_MISSING.format(surface="MCP", extra="mcp")) from exc

    return serve(registry_or_executor, **kwargs)


def serve_cli(registry_or_executor: Any, **kwargs: Any) -> Any:
    """Expose the given registry or executor as a command-line interface.

    Forwards to the apcore-cli entry point.

    Raises:
        ImportError: If the ``cli`` extra is not installed.
    """
    try:
        import apcore_cli
    except ImportError as exc:  # pragma: no cover - exercised via the extra
        raise ImportError(_MISSING.format(surface="CLI", extra="cli")) from exc

    for entry_point in ("main", "run", "serve", "cli"):
        candidate = getattr(apcore_cli, entry_point, None)
        if callable(candidate):
            return candidate(registry_or_executor, **kwargs)

    raise RuntimeError("apcore-cli is installed but exposes no recognised entry point; call it directly instead.")
