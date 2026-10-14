"""Local SQLite Storage & Audit Trail Engine (Task 7.3).

Persists agent discovery runs, verified 6-field lead records, and detailed
chronological audit logs using asynchronous SQLite (aiosqlite) for offline replay,
debugging, and automated verification benchmarks.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Optional
import aiosmtplib
import aiosqlite
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from src.models.schema import FinalLeadRecord


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "leads_agent.db"


class LocalDatabase:
    """Asynchronous SQLite storage manager for runs, leads, and execution audit trails."""

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def init_db(self) -> None:
        """Initializes tables for runs, leads, and audit logs."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")

            # 1. Runs Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    session_id TEXT PRIMARY KEY,
                    search_prompt TEXT,
                    brochure_path TEXT,
                    category_focus TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    is_complete INTEGER DEFAULT 0,
                    total_leads_found INTEGER DEFAULT 0,
                    google_sheet_url TEXT
                );
            """)

            # 2. Leads Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    organization_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    location TEXT NOT NULL,
                    contact_person TEXT NOT NULL,
                    contact_channel TEXT NOT NULL,
                    verification_status TEXT NOT NULL,
                    source_url TEXT,
                    confidence_score REAL DEFAULT 1.0,
                    created_at TEXT,
                    FOREIGN KEY(session_id) REFERENCES runs(session_id) ON DELETE CASCADE
                );
            """)

            # 3. Audit Logs Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    node TEXT NOT NULL,
                    message TEXT NOT NULL,
                    level TEXT DEFAULT 'INFO',
                    timestamp TEXT,
                    FOREIGN KEY(session_id) REFERENCES runs(session_id) ON DELETE CASCADE
                );
            """)

            await db.commit()
            logger.debug(f"Initialized SQLite database at {self.db_path}")

    async def create_or_update_run(
        self,
        session_id: str,
        search_prompt: Optional[str] = None,
        brochure_path: Optional[str] = None,
        category_focus: Optional[str] = "Both",
        is_complete: bool = False,
        total_leads_found: int = 0,
        google_sheet_url: Optional[str] = None,
    ) -> None:
        """Upserts a discovery run entry."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO runs (
                    session_id, search_prompt, brochure_path, category_focus,
                    started_at, completed_at, is_complete, total_leads_found, google_sheet_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    is_complete = excluded.is_complete,
                    completed_at = CASE WHEN excluded.is_complete = 1 THEN excluded.completed_at ELSE runs.completed_at END,
                    total_leads_found = excluded.total_leads_found,
                    google_sheet_url = COALESCE(excluded.google_sheet_url, runs.google_sheet_url);
            """, (
                session_id, search_prompt, brochure_path, category_focus,
                now_iso, now_iso if is_complete else None,
                1 if is_complete else 0, total_leads_found, google_sheet_url,
            ))
            await db.commit()

    async def save_lead(self, session_id: str, lead: FinalLeadRecord) -> int:
        """Persists a single verified FinalLeadRecord."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO leads (
                    session_id, organization_name, category, location,
                    contact_person, contact_channel, verification_status,
                    source_url, confidence_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                lead.organization_name,
                lead.category.value,
                lead.location,
                lead.contact_person,
                lead.contact_channel,
                lead.verification_status.value,
                lead.source_url,
                lead.confidence_score,
                now_iso,
            ))
            await db.commit()
            return cursor.lastrowid or 0

    async def save_leads(self, session_id: str, leads: list[FinalLeadRecord]) -> int:
        """Batch persists multiple verified FinalLeadRecords."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        records_to_insert = [
            (
                session_id,
                l.organization_name,
                l.category.value,
                l.location,
                l.contact_person,
                l.contact_channel,
                l.verification_status.value,
                l.source_url,
                l.confidence_score,
                now_iso,
            )
            for l in leads
        ]

        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany("""
                INSERT INTO leads (
                    session_id, organization_name, category, location,
                    contact_person, contact_channel, verification_status,
                    source_url, confidence_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records_to_insert)
            await db.commit()
            return len(records_to_insert)

    async def save_audit_logs(self, session_id: str, logs: list[dict[str, Any]]) -> int:
        """Batch saves audit log entries for a given session."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entries = [
            (
                session_id,
                log.get("node", "system"),
                log.get("message", ""),
                log.get("level", "INFO"),
                log.get("timestamp", now_iso),
            )
            for log in logs
        ]

        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany("""
                INSERT INTO audit_logs (session_id, node, message, level, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, entries)
            await db.commit()
            return len(entries)

    async def get_leads_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieves all verified leads collected in a specific session."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT organization_name, category, location, contact_person,
                       contact_channel, verification_status, source_url, confidence_score, created_at
                FROM leads
                WHERE session_id = ?
                ORDER BY id ASC;
            """, (session_id,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_audit_logs_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """Retrieves chronological execution logs for a session."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT node, message, level, timestamp
                FROM audit_logs
                WHERE session_id = ?
                ORDER BY id ASC;
            """, (session_id,))
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def get_run_summary(self, session_id: str) -> Optional[dict[str, Any]]:
        """Retrieves overview metrics for a discovery session."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT session_id, search_prompt, brochure_path, category_focus,
                       started_at, completed_at, is_complete, total_leads_found, google_sheet_url
                FROM runs
                WHERE session_id = ?;
            """, (session_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None

