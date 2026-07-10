"""Service layer public API with lazy exports.

Importing a subpackage such as :mod:`services.hwfit` must not pull optional
search, document, research, memory, and shell dependencies into the process.
The historical ``from services import SearchService`` API remains supported.
"""

from importlib import import_module


__all__ = (
    "SearchService",
    "SearchResult",
    "SearchResponse",
    "DocsService",
    "DocChunk",
    "IndexResult",
    "ResearchService",
    "ResearchResult",
    "ResearchSource",
    "MemoryService",
    "Memory",
    "MemorySearchResult",
    "ShellService",
    "ShellResult",
)

_EXPORTS = {
    "SearchService": (".search", "SearchService"),
    "SearchResult": (".search", "SearchResult"),
    "SearchResponse": (".search", "SearchResponse"),
    "DocsService": (".docs", "DocsService"),
    "DocChunk": (".docs", "DocChunk"),
    "IndexResult": (".docs", "IndexResult"),
    "ResearchService": (".research", "ResearchService"),
    "ResearchResult": (".research", "ResearchResult"),
    "ResearchSource": (".research", "ResearchSource"),
    "MemoryService": (".memory", "MemoryService"),
    "Memory": (".memory", "Memory"),
    "MemorySearchResult": (".memory", "MemorySearchResult"),
    "ShellService": (".shell", "ShellService"),
    "ShellResult": (".shell", "ShellResult"),
}


def __getattr__(name: str):
    """Load an exported service only when a caller asks for it."""
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
