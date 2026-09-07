"""
Chunks PDF/DOCX rulebooks/ordinances/curricula into data/rulebook_chunks.json.

Expected input layout -- organize raw files by department subfolder so the
department can be inferred automatically; anything directly in the root
folder is tagged department="General" (matches every department at query
time -- see src/stores/rulebook_store.py):

    data/raw_rulebooks/
        general_ordinances.pdf              -> department: General
        Civil Engineering/
            civil_curriculum.docx           -> department: Civil Engineering
        Computer Science and Engineering/
            cse_ug_rulebook.pdf

Chunking strategy:
  1. If the text contains numbered clause/section markers ("Clause 7.3",
     "Section 4", ...), split on those boundaries -- each clause becomes
     one chunk, which is exactly the granularity the Confidence Gate and
     synthesizer expect (one self-contained rule per chunk).
  2. Otherwise, falls back to merging paragraphs into ~120-word chunks with
     a small overlap, so no chunk is either a single sentence or an entire
     multi-page section.

Each chunk is auto-tagged with a subcategory using the same keyword rules
Node 1 uses (src/llm.py's INTENT_RULES) -- chunks that don't match anything
are tagged "unclassified" and should be reviewed by hand, since an
untagged/mistagged chunk won't be found by the ambiguity-detection logic.

Usage:
    python scripts/chunk_rulebooks.py --input data/raw_rulebooks
    python scripts/chunk_rulebooks.py --input data/raw_rulebooks --output data/rulebook_chunks.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm import INTENT_RULES  # noqa: E402

_CLAUSE_MARKER = re.compile(r"(?=\b(?:Clause|Section|Ordinance)\s+\d+(?:\.\d+)*\b)", re.I)
_WORD = re.compile(r"\S+")
_TARGET_CHUNK_WORDS = 120
_OVERLAP_WORDS = 20


def _extract_pdf_text(path: Path) -> str:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _extract_docx_text(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    return "\n".join(p.text for p in document.paragraphs)


def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _extract_pdf_text(path)
    if path.suffix.lower() in {".docx", ".doc"}:
        return _extract_docx_text(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def _split_on_clauses(text: str) -> list[str]:
    pieces = [p.strip() for p in _CLAUSE_MARKER.split(text) if p.strip()]
    return pieces


def _chunk_by_words(text: str) -> list[str]:
    words = _WORD.findall(text)
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = start + _TARGET_CHUNK_WORDS
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = end - _OVERLAP_WORDS
    return chunks


def _chunk_text(text: str) -> list[str]:
    clause_pieces = _split_on_clauses(text)
    # Require at least 2 real clause markers before trusting this split --
    # a single match usually just means the word "Section" appeared once.
    if len(clause_pieces) >= 2:
        # still cap runaway clause lengths (e.g. a clause followed by pages
        # of unrelated appendix text with no further markers)
        final: list[str] = []
        for piece in clause_pieces:
            if len(_WORD.findall(piece)) > _TARGET_CHUNK_WORDS * 3:
                final.extend(_chunk_by_words(piece))
            else:
                final.append(piece)
        return final
    return _chunk_by_words(text)


def _auto_tag(text: str) -> str:
    for pattern, tags in INTENT_RULES:
        if pattern.search(text):
            return tags["subcategory"]
    return "unclassified"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Root folder of raw PDF/DOCX files")
    parser.add_argument("--output", default="data/rulebook_chunks.json")
    args = parser.parse_args()

    root = Path(args.input)
    files = [p for p in root.rglob("*") if p.suffix.lower() in {".pdf", ".docx", ".doc"}]
    if not files:
        print(f"No .pdf/.docx files found under {root}")
        sys.exit(1)

    entries = []
    tag_counts: dict[str, int] = {}
    for path in files:
        department = path.relative_to(root).parts[0] if path.parent != root else "General"
        print(f"Processing {path} (department: {department})...")
        try:
            text = _extract_text(path)
        except Exception as exc:  # noqa: BLE001 -- keep converting the rest on failure
            print(f"  SKIPPED ({exc})")
            continue

        for chunk in _chunk_text(text):
            if len(_WORD.findall(chunk)) < 8:
                continue  # too short to be a meaningful standalone rule
            subcategory = _auto_tag(chunk)
            tag_counts[subcategory] = tag_counts.get(subcategory, 0) + 1
            entries.append({"subcategory": subcategory, "department": department, "text": chunk})

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nWrote {len(entries)} chunks to {out_path}")
    print("Subcategory breakdown:", tag_counts)
    if tag_counts.get("unclassified"):
        print(
            f"\n{tag_counts['unclassified']} chunks are 'unclassified' -- open the JSON and "
            "either tag them manually or add a matching pattern to INTENT_RULES in src/llm.py."
        )
    print("Re-run `python scripts/ingest_data.py` to rebuild the Rulebook store.")


if __name__ == "__main__":
    main()
