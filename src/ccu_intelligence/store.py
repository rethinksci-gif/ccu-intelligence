"""SQLite working store with immutable event history and normalized relationships."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import Article, Bundle, Project, ProjectEvent

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS companies(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, company_id TEXT NOT NULL REFERENCES companies(id), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS technologies(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY, canonical_url TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, doi TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS article_fingerprint ON articles(fingerprint);
CREATE UNIQUE INDEX IF NOT EXISTS article_doi ON articles(doi) WHERE doi IS NOT NULL;
CREATE TABLE IF NOT EXISTS article_sources(article_id TEXT REFERENCES articles(id), source_id TEXT NOT NULL, url TEXT NOT NULL, retrieved_at TEXT NOT NULL, PRIMARY KEY(article_id, source_id, url));
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), payload TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'Events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'Events are immutable'); END;
CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY, article_id TEXT NOT NULL REFERENCES articles(id), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claim_evidence(claim_id TEXT REFERENCES claims(id), evidence_id TEXT REFERENCES evidence(id), PRIMARY KEY(claim_id,evidence_id));
CREATE TABLE IF NOT EXISTS retrievals(id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, at TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT NOT NULL, action TEXT NOT NULL, record_id TEXT NOT NULL, detail TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def log(self, source: str, status: str, detail: str):
        with self.db:
            self.db.execute(
                "INSERT INTO retrievals(source_id,at,status,detail) VALUES(?,?,?,?)",
                (source, datetime.now(UTC).isoformat(), status, detail),
            )

    def add_article(self, article: Article) -> tuple[str, bool]:
        row = self.db.execute(
            "SELECT id FROM articles WHERE canonical_url=? OR fingerprint=? OR (doi IS NOT NULL AND doi=?)",
            (str(article.canonical_url), article.content_fingerprint, article.doi),
        ).fetchone()
        article_id = row[0] if row else article.article_id
        with self.db:
            if not row:
                self.db.execute(
                    "INSERT INTO articles VALUES(?,?,?,?,?)",
                    (
                        article_id,
                        str(article.canonical_url),
                        article.content_fingerprint,
                        article.doi,
                        article.model_dump_json(),
                    ),
                )
            self.db.execute(
                "INSERT OR IGNORE INTO article_sources VALUES(?,?,?,?)",
                (article_id, article.source_id, str(article.canonical_url), article.retrieved_at.isoformat()),
            )
        return article_id, not bool(row)

    def articles(self) -> list[Article]:
        return [
            Article.model_validate_json(r[0])
            for r in self.db.execute("SELECT payload FROM articles ORDER BY id")
        ]

    def import_bundle(self, bundle: Bundle):
        # All-or-nothing import. Existing events/evidence may be replayed, never rewritten.
        with self.db:
            for table, records, id_attr in [
                ("companies", bundle.companies, "company_id"),
                ("evidence", bundle.evidence, "evidence_id"),
                ("technologies", bundle.technologies, "technology_id"),
            ]:
                for record in records:
                    record_id = getattr(record, id_attr)
                    old = self.db.execute(f"SELECT payload FROM {table} WHERE id=?", (record_id,)).fetchone()
                    if table == "evidence" and old and json.loads(old[0]) != record.model_dump(mode="json"):
                        raise ValueError("Evidence is immutable; create a new evidence ID")
                    self.db.execute(
                        f"INSERT INTO {table} VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                        (record_id, record.model_dump_json()),
                    )
            for p in bundle.projects:
                old = self.db.execute("SELECT payload FROM projects WHERE id=?", (p.project_id,)).fetchone()
                if old and json.loads(old[0]) != p.model_dump(mode="json"):
                    current = json.loads(old[0])
                    pending = [
                        e
                        for e in bundle.events
                        if e.project_id == p.project_id
                        and not self.db.execute("SELECT 1 FROM events WHERE id=?", (e.event_id,)).fetchone()
                    ]
                    for event in sorted(pending, key=lambda e: (e.reporting_date, e.event_id)):
                        if set(event.previous_value) != set(event.new_value):
                            raise ValueError("Every imported change requires previous and new values")
                        if set(event.new_value) & {"project_id", "company", "sample"}:
                            raise ValueError("Events cannot change project identity")
                        if any(k not in current or current[k] != v for k, v in event.previous_value.items()):
                            raise ValueError("Stale imported event chain")
                        current.update(event.new_value)
                    if not pending or current != p.model_dump(mode="json"):
                        raise ValueError("Project snapshot changes require a complete new event chain")
                    self.db.execute(
                        "UPDATE projects SET payload=? WHERE id=?", (p.model_dump_json(), p.project_id)
                    )
                self.db.execute(
                    "INSERT OR IGNORE INTO projects VALUES(?,?,?)",
                    (p.project_id, p.company, p.model_dump_json()),
                )
            for e in bundle.events:
                self._insert_event(e)
            for a in bundle.articles:
                old = self.db.execute("SELECT payload FROM articles WHERE id=?", (a.article_id,)).fetchone()
                if old and json.loads(old[0]) != a.model_dump(mode="json"):
                    # An explicitly reviewed manual bundle may replace candidate analysis only.
                    previous = Article.model_validate_json(old[0])
                    if (
                        str(previous.canonical_url) != str(a.canonical_url)
                        or previous.content_fingerprint != a.content_fingerprint
                    ):
                        raise ValueError("Cannot change article identity during review")
                    self.db.execute(
                        "UPDATE articles SET payload=? WHERE id=?", (a.model_dump_json(), a.article_id)
                    )
                elif not old:
                    self.db.execute(
                        "INSERT INTO articles VALUES(?,?,?,?,?)",
                        (
                            a.article_id,
                            str(a.canonical_url),
                            a.content_fingerprint,
                            a.doi,
                            a.model_dump_json(),
                        ),
                    )
                self.db.execute(
                    "DELETE FROM claim_evidence WHERE claim_id IN (SELECT id FROM claims WHERE article_id=?)",
                    (a.article_id,),
                )
                self.db.execute("DELETE FROM claims WHERE article_id=?", (a.article_id,))
                for c in a.claims:
                    self.db.execute(
                        "INSERT INTO claims VALUES(?,?,?)", (c.claim_id, a.article_id, c.model_dump_json())
                    )
                    for eid in c.evidence_ids:
                        self.db.execute("INSERT INTO claim_evidence VALUES(?,?)", (c.claim_id, eid))
            self.db.execute(
                "INSERT INTO audit(at,action,record_id,detail) VALUES(?,?,?,?)",
                (datetime.now(UTC).isoformat(), "manual_import", "bundle", "Validated records imported"),
            )

    def _insert_event(self, event: ProjectEvent) -> bool:
        old = self.db.execute("SELECT payload FROM events WHERE id=?", (event.event_id,)).fetchone()
        if old:
            if json.loads(old[0]) != event.model_dump(mode="json"):
                raise ValueError("An existing event cannot be changed")
            return False
        for eid in event.evidence_links:
            if not self.db.execute("SELECT 1 FROM evidence WHERE id=?", (eid,)).fetchone():
                raise ValueError(f"Missing evidence: {eid}")
        self.db.execute(
            "INSERT INTO events VALUES(?,?,?)", (event.event_id, event.project_id, event.model_dump_json())
        )
        return True

    def apply_event(self, event: ProjectEvent):
        with self.db:
            if self.db.execute("SELECT 1 FROM events WHERE id=?", (event.event_id,)).fetchone():
                self._insert_event(event)
                return
            row = self.db.execute("SELECT payload FROM projects WHERE id=?", (event.project_id,)).fetchone()
            if not row:
                raise ValueError("Unknown project")
            current = json.loads(row[0])
            if current["sample"] != event.sample:
                raise ValueError("Sample/production mismatch")
            if set(event.new_value) != set(event.previous_value):
                raise ValueError("Every changed field needs its previous value")
            if set(event.new_value) & {"project_id", "company", "sample"}:
                raise ValueError("Events cannot change project identity")
            for key, previous in event.previous_value.items():
                if key not in current or current[key] != previous:
                    raise ValueError(f"Stale event: previous value mismatch for {key}")
            updated = Project.model_validate(current | event.new_value)
            for eid in event.evidence_links:
                evidence_row = self.db.execute("SELECT payload FROM evidence WHERE id=?", (eid,)).fetchone()
                if not evidence_row or (not event.sample and json.loads(evidence_row[0])["sample"]):
                    raise ValueError("Missing or sample evidence")
            self._insert_event(event)
            self.db.execute(
                "UPDATE projects SET payload=? WHERE id=?", (updated.model_dump_json(), event.project_id)
            )
            self.bundle()  # validate every new evidence reference before committing

    def bundle(self) -> Bundle:
        result = {}
        for table in ["companies", "evidence", "projects", "events", "technologies", "articles"]:
            result[table] = [
                json.loads(r[0]) for r in self.db.execute(f"SELECT payload FROM {table} ORDER BY id")
            ]
        return Bundle.model_validate(result)
