"""
Relational Directory Store.

Holds structured contact records (Faculty Advisors, HODs, room numbers,
official email templates, Department Student Representatives) and is
queried with deterministic SQL, not similarity search -- this is the
"SQL Exact Match" branch of the Async Multi-Route Retriever.
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from src.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS faculty (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    role TEXT NOT NULL,              -- 'HOD' | 'Faculty Advisor' | 'Dean'
    department TEXT NOT NULL,
    email TEXT NOT NULL,
    office TEXT,
    office_hours TEXT
);

CREATE TABLE IF NOT EXISTS student_reps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    email TEXT NOT NULL,
    contact TEXT
);
"""


def _connect() -> sqlite3.Connection:
    Path(settings.sqlite_directory_db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.sqlite_directory_db)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def load_csv(faculty_csv: str | Path, reps_csv: str | Path | None = None) -> None:
    """Ingest data/faculty_directory.csv (and optionally a reps CSV) into SQLite."""
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM faculty")
        with open(faculty_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                conn.execute(
                    "INSERT INTO faculty (name, role, department, email, office, "
                    "office_hours) VALUES (:name, :role, :department, :email, "
                    ":office, :office_hours)",
                    row,
                )
        if reps_csv:
            conn.execute("DELETE FROM student_reps")
            with open(reps_csv, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    conn.execute(
                        "INSERT INTO student_reps (name, department, email, contact) "
                        "VALUES (:name, :department, :email, :contact)",
                        row,
                    )
        conn.commit()


def query_directory(department: str | None, role: str | None = None) -> list[dict]:
    """
    Deterministic SQL exact-match lookup, e.g. the pipeline's own example:
        SELECT email, office FROM faculty WHERE dept='CSE' AND role='HOD'
    """
    if department is None:
        return []

    sql = "SELECT name, role, department, email, office, office_hours FROM faculty WHERE department = ?"
    params: list = [department]
    if role:
        sql += " AND role = ?"
        params.append(role)

    with _connect() as conn:
        faculty_rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        rep_rows = [
            dict(r)
            for r in conn.execute(
                "SELECT name, department, email, contact FROM student_reps WHERE department = ?",
                [department],
            ).fetchall()
        ]

    for r in rep_rows:
        r["role"] = "Department Student Representative"
    return faculty_rows + rep_rows
