"""Extract the specification .docx to plain text, reproducibly.

The committed `spec.txt` is what tests read — `tests/unit/test_spec_minimum_fields.py`
parses the section 7 table from it and asserts every minimum field appears in the
corresponding contract. That only means something if the text is verifiably the
document's rather than a paraphrase someone typed, so the extractor is committed
alongside its output and a test asserts re-running it reproduces the file
byte-for-byte.

Paragraph styles are preserved as a `[StyleName]` prefix so heading structure
survives, and tables are emitted as pipe-delimited rows between markers. Both
matter: the section numbers cited throughout the codebase are only locatable if
headings are, and nearly every normative requirement in the document lives in a
table.

Usage::

    python tools/extract_spec.py [--check]
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from typing import Final
from xml.etree import ElementTree

ROOT: Final = Path(__file__).resolve().parent.parent
DOCX: Final = ROOT / "docs/specification/Intraday_Agentic_Trading_System_Specification.docx"
TEXT: Final = ROOT / "docs/specification/spec.txt"

W: Final = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{W}t"))


def _paragraph_style(paragraph: ElementTree.Element) -> str:
    properties = paragraph.find(f"{W}pPr")
    if properties is None:
        return ""
    style = properties.find(f"{W}pStyle")
    return style.get(f"{W}val", "") if style is not None else ""


def extract(docx: Path = DOCX) -> str:
    """Render the document body as plain text."""
    with zipfile.ZipFile(docx) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))

    body = document.find(f"{W}body")
    if body is None:
        raise ValueError(f"{docx} has no document body")

    lines: list[str] = []
    for element in body:
        tag = element.tag.removeprefix(W)
        if tag == "p":
            text = _paragraph_text(element)
            if not text.strip():
                continue
            style = _paragraph_style(element)
            lines.append(f"[{style}] {text}" if style else text)
        elif tag == "tbl":
            lines.append("--- TABLE ---")
            for row in element.findall(f"{W}tr"):
                cells = [
                    " ".join(_paragraph_text(p) for p in cell.findall(f"{W}p"))
                    for cell in row.findall(f"{W}tc")
                ]
                lines.append(" | ".join(cells))
            lines.append("--- END TABLE ---")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed text matches the document instead of rewriting it",
    )
    args = parser.parse_args(argv)

    if not DOCX.is_file():
        print(f"specification not found at {DOCX}", file=sys.stderr)
        return 1

    rendered = extract()

    if args.check:
        if not TEXT.is_file():
            print(f"{TEXT} is missing; run tools/extract_spec.py", file=sys.stderr)
            return 1
        if TEXT.read_text(encoding="utf-8") != rendered:
            print(
                f"{TEXT} does not match {DOCX.name}. Either the document changed "
                "(re-run tools/extract_spec.py and review the diff) or the text was "
                "edited by hand, which it must not be.",
                file=sys.stderr,
            )
            return 1
        print(f"specification text matches {DOCX.name} ({len(rendered):,} chars).")
        return 0

    TEXT.write_text(rendered, encoding="utf-8")
    print(f"wrote {TEXT.relative_to(ROOT)} ({len(rendered):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
