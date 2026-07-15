"""Bundled artifact skills and deterministic request matching.

These skills belong to Odysseus itself.  They are copied into the runtime
skill library for discovery, while the source-controlled copies are used for
trusted, automatic prompt loading when a user explicitly requests a file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, List, Tuple


BUNDLED_SKILLS_ROOT = Path(__file__).with_name("bundled_skills")

ARTIFACT_SKILL_FILES = {
    "create-docx-document": BUNDLED_SKILLS_ROOT / "create-docx-document" / "SKILL.md",
    "create-excel-workbook": BUNDLED_SKILLS_ROOT / "create-excel-workbook" / "SKILL.md",
    "create-pdf-document": BUNDLED_SKILLS_ROOT / "create-pdf-document" / "SKILL.md",
}

_REQUEST_VERB = re.compile(
    r"\b(?:create|make|generate|build|prepare|write|draft|export|convert|"
    r"mach(?:e|en)?|erstell(?:e|en)?|erzeug(?:e|en)?|generier(?:e|en)?|"
    r"exportier(?:e|en)?|konvertier(?:e|en)?|schreib(?:e|en)?)\b",
    re.IGNORECASE,
)
_REQUEST_SIGNAL = re.compile(
    r"\b(?:need|want|would\s+like|please|brauche|möchte|will|bitte|soll)\b",
    re.IGNORECASE,
)
_FORMAT_PATTERNS = {
    "create-docx-document": re.compile(
        r"(?:\bdocx\b|\.docx\b|\bword(?:[\s-]+(?:datei|dokument|file|document))?\b|"
        r"\boffice[\s-]+document\b)",
        re.IGNORECASE,
    ),
    "create-excel-workbook": re.compile(
        r"(?:\bxlsx\b|\.xlsx\b|\bexcel\b|\bspreadsheet\b|\bworkbook\b|"
        r"\barbeitsmappe\b|\btabellenkalkulation\b|\bcsv\b|\.csv\b)",
        re.IGNORECASE,
    ),
    "create-pdf-document": re.compile(r"(?:\bpdf\b|\.pdf\b)", re.IGNORECASE),
}


def iter_bundled_artifact_skills() -> Iterator[Tuple[str, Path]]:
    """Yield each bundled artifact skill name and its source SKILL.md path."""
    yield from ARTIFACT_SKILL_FILES.items()


def artifact_skill_names_for_request(text: str) -> List[str]:
    """Return the file-generation skills explicitly requested by *text*.

    Requiring an action/request signal avoids loading a creation procedure for
    informational questions such as "What is a PDF?".  Multiple formats are
    intentionally supported for conversion requests.
    """
    text = str(text or "").strip()
    if not text or not (_REQUEST_VERB.search(text) or _REQUEST_SIGNAL.search(text)):
        return []
    return [name for name, pattern in _FORMAT_PATTERNS.items() if pattern.search(text)]


def load_bundled_artifact_skills_for_request(text: str) -> List[Tuple[str, str]]:
    """Load the complete source-controlled SKILL.md files for a request."""
    loaded: List[Tuple[str, str]] = []
    for name in artifact_skill_names_for_request(text):
        path = ARTIFACT_SKILL_FILES[name]
        try:
            loaded.append((name, path.read_text(encoding="utf-8")))
        except OSError:
            # Packaging or installation mistakes must not break chat.  The
            # caller logs/proceeds with normal tool routing, and tests ensure
            # production builds include this directory.
            continue
    return loaded
