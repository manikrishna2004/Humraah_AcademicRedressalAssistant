"""
Run once (and again whenever data/*.csv or data/*.json change) to build:
    - the SQLite Directory Store
    - the ChromaDB Senior Experience collection (+ embeddings)
    - the ChromaDB Official Rulebook collection (+ embeddings + BM25 index)

Usage:
    python scripts/ingest_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.stores import directory_store, rulebook_store, senior_experience_store  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    print("Ingesting Directory Store (SQLite)...")
    directory_store.load_csv(
        DATA_DIR / "faculty_directory.csv", DATA_DIR / "student_reps.csv"
    )

    print("Ingesting Senior Experience Store (ChromaDB Collection A)...")
    senior_experience_store.load_json(DATA_DIR / "senior_experiences.json")

    print("Ingesting Official Rulebook Store (ChromaDB Collection B + BM25)...")
    rulebook_store.load_json(DATA_DIR / "rulebook_chunks.json")

    print("Done. Stores are ready under ./data/")


if __name__ == "__main__":
    main()
