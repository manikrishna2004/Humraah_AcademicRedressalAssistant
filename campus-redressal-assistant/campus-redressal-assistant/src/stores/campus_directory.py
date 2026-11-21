"""Build and query the versioned directory of publicly listed campus offices."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from src.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS campus_contacts (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    department TEXT NOT NULL,
    role TEXT NOT NULL,
    office TEXT,
    office_hours TEXT,
    visit_note TEXT,
    email TEXT,
    phone TEXT,
    detail TEXT NOT NULL,
    source_label TEXT NOT NULL,
    url TEXT NOT NULL,
    location_url TEXT,
    sort_order INTEGER NOT NULL,
    search_text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS campus_contacts_route ON campus_contacts(kind, department);
"""

PUBLIC_FIELDS = """
    id, kind, department, role, office, office_hours, visit_note, email, phone,
    detail, source_label, url, location_url
"""
ROUTE_SQL = f"""
    SELECT {PUBLIC_FIELDS} FROM campus_contacts
    WHERE kind = $kind AND department = $department ORDER BY sort_order LIMIT 1
"""
SEARCH_SQL = f"""
    SELECT {PUBLIC_FIELDS} FROM campus_contacts
    WHERE $term = '' OR instr(' ' || search_text || ' ', ' ' || $term || ' ') > 0
       OR (length($term) >= 3 AND instr(search_text, $term) > 0)
    ORDER BY sort_order, role
"""
ROUTES = {
    "supplementary_exam": ["academic_ug", "erp_exams"],
    "grade_review": ["instructor", "department"],
    "mid_sem_review": ["instructor", "department"],
    "end_sem_appeal": ["instructor", "department", "academic_ug"],
    "attendance_waiver": ["advisor", "department", "medical"],
    "escalation": ["advisor", "department"],
}
ESCALATION = {
    "yes": ["department", "academic_ug"],
    "no": ROUTES["escalation"],
    "unknown": ["advisor", "department", "academic_ug"],
}


def _connect(database: str | Path | None = None) -> sqlite3.Connection:
    path = Path(database or settings.sqlite_directory_db)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def load_campus(path: str | Path, database: str | Path | None = None) -> None:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    with closing(_connect(database)) as connection, connection:
        connection.executescript(SCHEMA)
        connection.execute("DELETE FROM campus_contacts")
        connection.executemany(
            """
            INSERT INTO campus_contacts VALUES (
                :id, :kind, :department, :role, :office, :office_hours, :visit_note,
                :email, :phone, :detail, :source_label, :url, :location_url, :sort_order, :search_text
            )
            """,
            (
                {
                    **dict.fromkeys(("office", "office_hours", "visit_note", "email", "phone", "location_url")),
                    **row,
                    "sort_order": index,
                    "search_text": normalize_search(" ".join(
                        str(row.get(key) or "") for key in ("role", "department", "office", "aliases", "detail")
                    )),
                }
                for index, row in enumerate(rows)
            ),
        )


def normalize_search(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def search_contacts(term: str) -> list[dict]:
    with closing(_connect()) as connection:
        return [dict(row) for row in connection.execute(SEARCH_SQL, {"term": normalize_search(term)})]


def academic_contacts(tag: str | None, department: str | None, sent: bool | None) -> list[dict]:
    if not tag:
        return []
    if tag == "escalation":
        kinds = ESCALATION["unknown" if sent is None else "yes" if sent else "no"]
    else:
        kinds = ROUTES.get(tag, [])
    result = []
    with closing(_connect()) as connection:
        for kind in kinds:
            unit = department if kind == "department" and department else "General"
            row = connection.execute(ROUTE_SQL, {"kind": kind, "department": unit}).fetchone()
            if row is None and kind == "department" and unit != "General":
                row = connection.execute(ROUTE_SQL, {"kind": kind, "department": "General"}).fetchone()
            if row is not None:
                result.append(dict(row))
    return result


def browser_directory() -> dict:
    return {"routeSql": ROUTE_SQL, "searchSql": SEARCH_SQL, "routes": ROUTES, "escalation": ESCALATION}
