"""
Converts a raw senior-experience export (Google Forms -> Sheets/Excel, or a
plain CSV) into data/senior_experiences.json.

Google Form exports almost never use our schema's field names directly --
columns are usually the literal question text ("Which department are you
in?", "Describe what worked for you", ...). Rather than guess and silently
get it wrong, this script:

  1. Loads the sheet with pandas (xlsx, xls, or csv).
  2. Shows you every column and asks which one maps to which of our five
     fields (category, subcategory, department, degree_program, summary).
  3. If you don't have a subcategory column (most forms won't), it can
     auto-tag each row from the summary text using the same keyword rules
     the intent classifier uses (src/llm.py's INTENT_RULES) -- and leaves
     anything it can't confidently tag as "unclassified" for you to fix by
     hand, rather than guessing.

Usage:
    python scripts/convert_senior_experiences.py --input path/to/export.xlsx
    python scripts/convert_senior_experiences.py --input export.csv --output data/senior_experiences.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm import INTENT_RULES  # noqa: E402  (reuse the same keyword rules Node 1 uses)

FIELDS = ["category", "subcategory", "department", "degree_program", "summary"]
REQUIRED_FIELDS = {"department", "summary"}  # category/subcategory/degree_program may be blank


def _load_sheet(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def _pick_column(field: str, columns: list[str]) -> str | None:
    print(f"\nWhich column is '{field}'?")
    print("  0. <none / skip this field>")
    for i, col in enumerate(columns, 1):
        print(f"  {i}. {col}")
    while True:
        raw = input("> ").strip()
        if raw == "0":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(columns):
            return columns[int(raw) - 1]
        print(f"Enter a number from 0-{len(columns)}.")


def _auto_tag_subcategory(text: str) -> str:
    for pattern, tags in INTENT_RULES:
        if pattern.search(str(text)):
            return tags["subcategory"]
    return "unclassified"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to the raw .xlsx/.xls/.csv export")
    parser.add_argument(
        "--output",
        default="data/senior_experiences.json",
        help="Where to write the converted JSON (default: data/senior_experiences.json)",
    )
    parser.add_argument(
        "--mapping",
        help=(
            "Optional path to a JSON file mapping our field names to your column "
            'names, e.g. {"department": "Which department are you in?", '
            '"summary": "Describe what worked"}. Skips the interactive prompts '
            "for any field present in the mapping."
        ),
    )
    args = parser.parse_args()

    df = _load_sheet(Path(args.input))
    columns = list(df.columns)
    print(f"Loaded {len(df)} rows with columns: {columns}")

    mapping: dict[str, str | None] = {}
    if args.mapping:
        mapping.update(json.loads(Path(args.mapping).read_text(encoding="utf-8")))

    for field in FIELDS:
        if field in mapping:
            continue
        mapping[field] = _pick_column(field, columns)

    missing_required = [f for f in REQUIRED_FIELDS if not mapping.get(f)]
    if missing_required:
        print(f"\nERROR: these fields are required and weren't mapped: {missing_required}")
        sys.exit(1)

    entries = []
    auto_tagged, unclassified = 0, 0
    for _, row in df.iterrows():
        summary = str(row[mapping["summary"]]).strip()
        if not summary or summary.lower() == "nan":
            continue  # skip blank responses

        if mapping.get("subcategory"):
            subcategory = str(row[mapping["subcategory"]]).strip()
        else:
            subcategory = _auto_tag_subcategory(summary)
            auto_tagged += 1
            if subcategory == "unclassified":
                unclassified += 1

        entries.append(
            {
                "category": str(row[mapping["category"]]).strip() if mapping.get("category") else "",
                "subcategory": subcategory,
                "department": str(row[mapping["department"]]).strip(),
                "degree_program": (
                    str(row[mapping["degree_program"]]).strip() if mapping.get("degree_program") else ""
                ),
                "summary": summary,
            }
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nWrote {len(entries)} entries to {out_path}")
    if auto_tagged:
        print(
            f"Auto-tagged subcategory for {auto_tagged} rows "
            f"({unclassified} landed in 'unclassified' -- open the JSON and fix those by hand, "
            "or add matching patterns to INTENT_RULES in src/llm.py)."
        )
    print("Re-run `python scripts/ingest_data.py` to rebuild the Senior Experience store.")


if __name__ == "__main__":
    main()
