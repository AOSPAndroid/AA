CREATE TABLE IF NOT EXISTS watcher_state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notification_state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL, entry_id TEXT NOT NULL,
    received_at TEXT NOT NULL, imported_at TEXT NOT NULL,
    conversation_id TEXT NOT NULL, sender_name TEXT NOT NULL,
    sender_address TEXT NOT NULL, subject TEXT NOT NULL,
    body TEXT NOT NULL, body_truncated INTEGER NOT NULL,
    channel TEXT NOT NULL DEFAULT 'outlook',
    content_kind TEXT NOT NULL DEFAULT 'mail',
    app_name TEXT NOT NULL DEFAULT '',
    UNIQUE(source, entry_id)
);
