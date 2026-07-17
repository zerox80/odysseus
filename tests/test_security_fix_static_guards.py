from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generated_image_route_requires_metadata_and_fails_closed():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    start = source.index("async def serve_generated_image")
    end = source.index("\n\n@app.", start)
    body = source[start:end]

    assert "require_user(request)" in body
    assert "if _row is None" in body
    assert "status_code=503" in body
    assert "Generated-but-not-yet-imported images have no row" not in body


def test_gallery_persistence_failure_removes_orphan_and_propagates():
    source = (ROOT / "src" / "ai_interaction.py").read_text(encoding="utf-8")
    start = source.index("def _save_to_gallery")
    end = source.index("# GPT image models", start)
    body = source[start:end]

    assert ".unlink(missing_ok=True)" in body
    assert "raise RuntimeError" in body
    assert 'return ""' not in body


def test_python_dependency_audit_is_merge_blocking():
    workflow = (
        ROOT / ".github" / "workflows" / "dependency-review.yml"
    ).read_text(encoding="utf-8")

    assert "pip-audit (blocking)" in workflow
    assert "continue-on-error: true" not in workflow
