CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL,
    touched INTEGER NOT NULL,
    history TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_sessions_touched ON chat_sessions(touched);

CREATE TABLE IF NOT EXISTS campus_contacts (
    id TEXT NOT NULL,
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
    search_text TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    PRIMARY KEY (id, snapshot)
);
CREATE INDEX IF NOT EXISTS campus_contacts_route ON campus_contacts(snapshot, kind, department);
