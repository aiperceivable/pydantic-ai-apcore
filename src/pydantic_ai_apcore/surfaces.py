"""Project registered modules onto the other apcore surfaces.

Once tools have been registered with :func:`register_toolset`, they are ordinary
apcore modules -- anything that can serve an apcore registry can serve them.
These helpers are thin, optional conveniences over the surface adapters, kept
behind extras so the base install stays minimal:

    pip install "pydantic-ai-apcore[mcp]"
    pip install "pydantic-ai-apcore[cli]"
"""

from __future__ import annotations

from pathlib import Path
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
    """Run the given registry or executor as a command-line interface.

    Builds a Click application with :func:`apcore_cli.create_cli` and invokes
    it, so the modules reach the terminal the same way a standalone
    ``apcore-cli`` installation would. A path may be given instead, in which
    case apcore-cli's normal filesystem discovery applies.

    Extra keyword arguments are forwarded to ``create_cli`` (``prog_name``,
    ``description``, ``expose``, ``acl``, and so on). To build the Click group
    without running it, call ``apcore_cli.create_cli`` directly.

    Raises:
        ImportError: If the ``cli`` extra is not installed.
        TypeError: If ``registry_or_executor`` is not a Registry, Executor, or
            filesystem path.
    """
    try:
        from apcore import Executor, Registry
        from apcore_cli import create_cli
    except ImportError as exc:  # pragma: no cover - exercised via the extra
        raise ImportError(_MISSING.format(surface="CLI", extra="cli")) from exc

    if isinstance(registry_or_executor, Executor):
        kwargs.setdefault("executor", registry_or_executor)
        kwargs.setdefault("registry", registry_or_executor.registry)
    elif isinstance(registry_or_executor, Registry):
        kwargs.setdefault("registry", registry_or_executor)
    elif isinstance(registry_or_executor, (str, Path)):
        kwargs.setdefault("extensions_dir", str(registry_or_executor))
    else:
        raise TypeError(
            "serve_cli() takes an apcore Registry, an apcore Executor, or an "
            f"extensions directory path; got {type(registry_or_executor).__name__}."
        )

    cli = create_cli(**kwargs)
    return cli(standalone_mode=True)
