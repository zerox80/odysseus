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

_IMPERATIVE_REQUEST = re.compile(
    r"(?:^\s*(?:(?:please|bitte)\s+)*"
    r"(?:create|make|generate|build|prepare|write|draft|export|convert|"
    r"mach(?:e|en)?|erstell(?:e|en)?|erzeug(?:e|en)?|generier(?:e|en)?|"
    r"exportier(?:e|en)?|konvertier(?:e|en)?|schreib(?:e|en)?)\b|"
    r"\b(?:can|could|would|will)\s+you\s+"
    r"(?:create|make|generate|build|prepare|write|draft|export|convert)\b|"
    r"\b(?:kannst|könntest)\s+du\b.{0,80}\b"
    r"(?:mach(?:e|en)?|erstell(?:e|en)?|erzeug(?:e|en)?|generier(?:e|en)?|"
    r"exportier(?:e|en)?|konvertier(?:e|en)?|schreib(?:e|en)?)\b)",
    re.IGNORECASE,
)
_DESIRED_FORMAT_REQUEST = re.compile(
    r"\b(?:i\s+(?:need|want|would\s+like)|"
    r"ich\s+(?:brauche|möchte)|ich\s+will)\b.{0,40}"
    r"(?:\bdocx\b|\.docx\b|\bword\b|\bxlsx\b|\.xlsx\b|\bexcel\b|"
    r"\bspreadsheet\b|\bworkbook\b|\bcsv\b|\.csv\b|\bpdf\b|\.pdf\b)",
    re.IGNORECASE,
)
_INFORMATIONAL_REQUEST = re.compile(
    r"^\s*(?:what(?:'s|\s+is)|what\s+does|explain|tell\s+me\s+about|"
    r"how\s+(?:do|can)\s+i|wie\s+(?:kann|könnte|soll)\s+ich|"
    r"was\s+(?:ist|macht)|erklär(?:e|en)?)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_DECLARATION = re.compile(
    r"^\s*(?:i\s+(?:will|am\s+going\s+to)|ich\s+werde)\b",
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

    Mentions of a format in informational questions and first-person status
    updates must remain normal chat. Multiple requested formats select the
    export procedures for one canonical editor document.
    """
    text = str(text or "").strip()
    if not text or _INFORMATIONAL_REQUEST.search(text) or _FIRST_PERSON_DECLARATION.search(text):
        return []
    if not (_IMPERATIVE_REQUEST.search(text) or _DESIRED_FORMAT_REQUEST.search(text)):
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
