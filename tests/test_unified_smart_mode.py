"""Regression checks for the single-mode, automatic-tool UX."""

from pathlib import Path

from src.action_intents import classify_tool_intent
from services.memory.artifact_skills import (
    artifact_skill_names_for_request,
    load_bundled_artifact_skills_for_request,
)
from services.memory.skills import SkillsManager


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_primary_ui_does_not_offer_chat_or_agent_modes():
    html = _read("static/index.html")
    app_js = _read("static/app.js")
    sessions_js = _read("static/js/sessions.js")
    assert 'id="mode-agent-btn"' not in html
    assert 'id="mode-chat-btn"' not in html
    assert 'data-ui-key="mode-toggle"' not in html
    assert "Agent / Chat" not in html
    assert "'mode-toggle':" not in app_js
    assert "chooses the right tools automatically" in html
    assert "s.mode === 'agent'" not in sessions_js


def test_every_frontend_turn_uses_unified_smart_routing():
    chat_js = _read("static/js/chat.js")
    assert "fd.append('mode', 'agent')" in chat_js
    assert "fd.set('mode', 'chat')" not in chat_js
    assert "isAgentMode ? 'agent' : 'chat'" not in chat_js
    # The visible Agent/Chat switch was removed, so its old per-submit state
    # must not survive as a free variable that crashes every prompt.
    assert "_isAgent" not in chat_js


def test_stream_cleanup_can_access_streaming_tts_state():
    chat_js = _read("static/js/chat.js")
    assert "let streamingTTS = false;" in chat_js
    assert "const streamingTTS =" not in chat_js


def test_backend_ignores_legacy_mode_choice():
    route = _read("routes/chat_routes.py")
    assert 'chat_mode = "agent"' in route
    assert 'form_data.get("mode"' not in route


def test_compare_ui_exposes_smart_instead_of_chat_agent_choice():
    selector = _read("static/js/compare/selector.js")
    assert "label: 'Smart'" in selector
    assert "label: 'Agent'" not in selector
    assert "{ id: 'chat'" not in selector


def test_document_editor_can_export_csv_as_real_xlsx():
    document_js = _read("static/js/document.js")
    assert "Export as Excel (.xlsx)" in document_js
    assert "XLSX.writeFile" in document_js
    assert (ROOT / "static/lib/xlsx.full.min.js").is_file()


def test_spreadsheets_receive_professional_preview_and_export_defaults():
    document_js = _read("static/js/document.js")
    style = _read("static/style.css")
    excel_skill = _read(
        "services/memory/bundled_skills/create-excel-workbook/SKILL.md"
    )

    assert "buildProfessionalWorkbook" in document_js
    assert "worksheet['!cols']" in document_js
    assert "worksheet['!autofilter']" in document_js
    assert "worksheet['!freeze']" in document_js
    assert "cellStyles: true" in document_js
    assert "csvDisplayValue" in document_js
    assert ".csv-workbook-header" in style
    assert ".csv-table thead th" in style
    assert ".csv-table td.csv-cell-currency" in style
    assert "position: sticky" in style
    assert "plausible and internally consistent sample values" in excel_skill
    assert "verify every calculation" in excel_skill


def test_file_requests_are_classified_for_automatic_document_tools():
    for prompt in (
        "Create an Excel spreadsheet with a monthly budget",
        "Generate a PDF report about this project",
        "Make a Word document from these notes",
        "Mach mir eine Excel-Datei für mein Monatsbudget",
        "Erstelle daraus bitte eine PDF-Datei",
        "Generiere ein Word-Dokument aus diesen Notizen",
    ):
        intent = classify_tool_intent(prompt)
        assert intent.needs_tools, prompt
        assert intent.category == "documents", prompt


def test_system_prompt_requires_detailed_answers_and_smart_routing():
    policy = _read("src/prompt_policy.py")
    assert "at least 800 words" in policy
    assert "1,500 words or more" in policy
    assert "one unified smart assistant" in policy


def test_custom_presets_support_long_outputs_beyond_8k():
    html = _read("static/index.html")
    presets_js = _read("static/js/presets.js")
    request_models = _read("src/request_models.py")
    assert 'id="custom-max-tokens" min="256" max="65792"' in html
    assert "rawTokens > 65536 ? 0 : rawTokens" in presets_js
    assert "_rawTk > 65536 ? 0 : _rawTk" in presets_js
    assert "le=65536" in request_models


def test_artifact_skill_matcher_avoids_informational_mentions():
    assert artifact_skill_names_for_request("Mach eine DOCX und eine PDF daraus") == [
        "create-docx-document",
        "create-pdf-document",
    ]
    assert artifact_skill_names_for_request("Bitte erstelle eine Excel-Arbeitsmappe") == [
        "create-excel-workbook",
    ]
    assert artifact_skill_names_for_request("Was ist eigentlich eine PDF?") == []


def test_exact_random_excel_request_selects_excel_skill():
    assert artifact_skill_names_for_request(
        "erstell excel liste wo du irgendwelche zufälligen sachen eingibst"
    ) == ["create-excel-workbook"]


def test_complete_bundled_skill_is_loaded_for_file_request():
    loaded = load_bundled_artifact_skills_for_request(
        "Erstelle einen hochwertigen PDF-Bericht"
    )
    assert [name for name, _ in loaded] == ["create-pdf-document"]
    markdown = loaded[0][1]
    assert "## Procedure" in markdown
    assert "## Pitfalls" in markdown
    assert "## Verification" in markdown
    assert "Print as PDF" in markdown


def test_bundled_artifact_skills_are_provisioned_and_global(tmp_path):
    manager = SkillsManager(str(tmp_path))
    names = manager.ensure_bundled_artifact_skills()
    assert names == [
        "create-docx-document",
        "create-excel-workbook",
        "create-pdf-document",
    ]

    manager.add_skill(
        name="alice-private-skill",
        description="Private test skill",
        owner="alice",
        source="user",
        status="published",
    )
    alice = {skill["name"] for skill in manager.load(owner="alice")}
    bob = {skill["name"] for skill in manager.load(owner="bob")}
    assert set(names).issubset(alice)
    assert set(names).issubset(bob)
    assert "alice-private-skill" in alice
    assert "alice-private-skill" not in bob
    assert manager.read_skill_md("create-docx-document", owner="bob")


def test_bundled_artifact_skills_are_read_only(tmp_path):
    manager = SkillsManager(str(tmp_path))
    manager.ensure_bundled_artifact_skills()
    assert not manager.update_skill(
        "create-pdf-document",
        {"description": "mutated"},
        owner=None,
    )
    assert not manager.delete_skill("create-pdf-document", owner=None)
    assert manager.read_skill_md("create-pdf-document", owner="alice")


def test_bundled_artifact_skills_are_read_only_in_the_ui():
    skills_js = _read("static/js/skills.js")
    assert "const isBundledArtifact = sk.source === 'builtin'" in skills_js
    assert "Odysseus built-in · automatically selected · read-only" in skills_js
    assert "Artifact skills · automatic" in skills_js
    assert ".filter(s => s.source !== 'builtin')" in skills_js


def test_agent_loop_uses_compact_task_anchored_artifact_path():
    loop = _read("src/agent_loop.py")
    initializer = _read("src/app_initializer.py")
    build_spec = _read("Odysseus.spec")
    assert "Automatically loaded Odysseus artifact skills" in loop
    assert "def _minimal_artifact_messages(" in loop
    assert "CURRENT USER REQUEST -- this is the task to execute now" in loop
    assert '_relevant_tools = {"create_document"}' in loop
    assert "artifact turn discarded non-create tool call(s)" in loop
    assert "artifact-without-tool retry=" in loop
    assert "allow_fenced_for_api=(_ody_doc_finetune_mode or _artifact_turn)" in loop
    assert "load_bundled_artifact_skills_for_request" in loop
    assert "ensure_bundled_artifact_skills" in initializer
    assert "services/memory/bundled_skills" in build_spec


def test_secondary_workspace_apps_are_removed_from_visible_navigation():
    html = _read("static/index.html")
    slash_commands = _read("static/js/slashCommands.js")

    for app in ("cookbook", "gallery", "notes", "tasks"):
        assert f'id="tool-{app}-btn"' not in html
        assert f'id="rail-{app}"' not in html
        assert f'data-ui-key="tool-{app}"' not in html

    assert "Open what? Try /open Settings" in slash_commands
    assert "Try /open Cookbook" not in slash_commands
