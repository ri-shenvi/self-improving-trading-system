"""The committed specification text must be the document's, not a paraphrase.

Several tests read `docs/specification/spec.txt` as the authority on what the
specification requires — most importantly the section 7 minimum-field coverage
test. If that text could drift from the .docx, those tests would be asserting
against a transcription, and a requirement could quietly disappear from the
codebase's notion of the spec without the document changing at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.extract_spec import DOCX, TEXT, extract, main

pytestmark = pytest.mark.unit


def test_document_is_committed() -> None:
    assert DOCX.is_file(), "the specification .docx must be in the repository"


def test_committed_text_matches_the_document() -> None:
    assert TEXT.read_text(encoding="utf-8") == extract()


def test_check_mode_passes() -> None:
    assert main(["--check"]) == 0


def test_extraction_is_deterministic() -> None:
    assert extract() == extract()


def test_text_preserves_structure_the_tests_depend_on() -> None:
    """Headings and tables must survive, or section citations become unlocatable."""
    body = TEXT.read_text(encoding="utf-8")
    assert "[Heading2] 7  Data sources and minimum fields" in body
    assert "--- TABLE ---" in body
    assert "knowledge_time" in body


def test_extractor_reports_a_missing_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.extract_spec as module

    monkeypatch.setattr(module, "DOCX", tmp_path / "absent.docx")
    assert module.main(["--check"]) == 1
