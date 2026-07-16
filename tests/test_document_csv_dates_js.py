"""Execute the spreadsheet date parser to prevent silent calendar rollovers."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_JS = ROOT / "static" / "js" / "document.js"
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node binary not on PATH")


def _csv_date_results(values: list[str]) -> list[dict[str, str | None]]:
    script = """
        import fs from 'node:fs';
        const source = fs.readFileSync(process.argv[1], 'utf8');
        const start = source.indexOf('  function csvDateValue(value) {');
        const end = source.indexOf('\\n  function csvTypedValue', start);
        if (start < 0 || end < 0) throw new Error('csvDateValue not found');
        eval(source.slice(start, end) + '\\nglobalThis.csvDateValue = csvDateValue;');
        const values = JSON.parse(process.argv[2]);
        console.log(JSON.stringify(values.map(value => {
          const date = csvDateValue(value);
          return { value, parsed: date ? [date.getFullYear(), date.getMonth() + 1, date.getDate()].join('-') : null };
        })));
    """
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(DOCUMENT_JS), json.dumps(values)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_csv_dates_reject_impossible_calendar_values_without_normalizing_them():
    results = _csv_date_results(["2026-02-28", "2026-02-31", "31.04.2026", "29.02.2024"])
    assert results == [
        {"value": "2026-02-28", "parsed": "2026-2-28"},
        {"value": "2026-02-31", "parsed": None},
        {"value": "31.04.2026", "parsed": None},
        {"value": "29.02.2024", "parsed": "2024-2-29"},
    ]
