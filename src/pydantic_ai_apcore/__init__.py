"""pydantic-ai-apcore -- apcore integration for pydantic-ai.

Two directions:

* :class:`ApcoreToolset` exposes registered apcore modules to a pydantic-ai
  agent, with governance enforced on every call.
* :func:`register_toolset` takes the tools an agent already has and registers
  them as apcore modules, so they can be governed and served on other surfaces.
"""

from pydantic_ai_apcore.scanner import (
    PydanticAIScanner,
    ScanResult,
    SkippedTool,
    register_toolset,
)
from pydantic_ai_apcore.surfaces import serve_cli, serve_mcp
from pydantic_ai_apcore.toolset import ApcoreToolset

__all__ = [
    "ApcoreToolset",
    "PydanticAIScanner",
    "ScanResult",
    "SkippedTool",
    "register_toolset",
    "serve_cli",
    "serve_mcp",
]
