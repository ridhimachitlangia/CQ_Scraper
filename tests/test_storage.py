"""Unit tests for Google Sheets & Local SQLite Sync (Phase 7).

Tests:
- Task 7.1: Google Sheets authentication, header enforcement, styling, and mock fallback.
- Task 7.2: Deduplication, batch row insertion, and status color formatting.
- Task 7.3: Local SQLite database initialization, runs tracking, leads persistence, and audit logging.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.models.schema import (
    CategoryEnum,
    FinalLeadRecord,
    VerificationStatusEnum,
)
from src.storage.database import LocalDatabase
from src.storage.google_sheets import (
    GoogleSheetsSyncClient,
    HEADER_BG_COLOR,
    PATTERN_BG_COLOR,
    VERIFIED_BG_COLOR,
)


# ==============================================================================
# Task 7.1 & 7.2: Google Sheets Sync Client Tests
# ==============================================================================

class TestGoogleSheetsSyncClient:
    def test_mock_fallback_when_credentials_missing(self):
        """When credentials are not present, runs gracefully in mock mode without crashing."""
        client = GoogleSheetsSyncClient(
            credentials_path="nonexistent_credentials.json",
            spreadsheet_id="mock_test_sheet",
        )
        record = FinalLeadRecord(
            organization_name="Acme Technologies",
            category=CategoryEnum.SPONSOR,
            location="Bengaluru",
            contact_person="Sarah Connor - VP Marketing",
            contact_channel="sarah.connor@acme.com",
            verification_status=VerificationStatusEnum.VERIFIED,
        )

        res = client.sync_leads([record])
        assert res.is_mock is True
        assert res.spreadsheet_id == "mock_test_sheet"
        assert res.rows_appended == 1
        assert "mock_test_sheet" in res.spreadsheet_url

    def test_ensure_headers_and_styling(self):
        """Applies canonical 6-column header and navy styling if sheet is empty."""
        client = GoogleSheetsSyncClient()
        mock_worksheet = MagicMock()
        mock_worksheet.row_values.return_value = []  # Empty sheet

        applied = client.ensure_headers_and_styling(mock_worksheet)
        assert applied is True
        mock_worksheet.insert_row.assert_called_once_with(
            FinalLeadRecord.sheet_headers(), index=1
        )
        mock_worksheet.format.assert_called_once()
        mock_worksheet.freeze.assert_called_once_with(rows=1)

    def test_sync_leads_deduplication_and_batch_insertion(self):
        """Deduplicates leads against existing sheet data and batch appends."""
        client = GoogleSheetsSyncClient()

        # Mock gspread client, spreadsheet, and worksheet
        mock_gspread_client = MagicMock()
        mock_spreadsheet = MagicMock()
        mock_spreadsheet.id = "real_sheet_123"
        mock_spreadsheet.url = "https://docs.google.com/spreadsheets/d/real_sheet_123/edit"
        mock_worksheet = MagicMock()
        mock_worksheet.title = "Sheet1"
        mock_worksheet.row_values.return_value = FinalLeadRecord.sheet_headers()

        # Existing sheet has "Existing Corp" and "existing@corp.com"
        mock_worksheet.col_values.side_effect = [
            ["Organization Name", "Existing Corp"],       # col 1 (orgs)
            ["Contact Channel", "existing@corp.com"],     # col 5 (channels)
            ["Verification Status", "Verified"],          # col 6 (status)
        ]
        mock_worksheet.get_all_values.return_value = [["Header"], ["Row 1"], ["Row 2"]]

        mock_spreadsheet.sheet1 = mock_worksheet
        mock_gspread_client.open_by_key.return_value = mock_spreadsheet
        mock_gspread_client.create.return_value = mock_spreadsheet

        # 2 incoming leads: 1 duplicate, 1 unique
        rec_duplicate = FinalLeadRecord(
            organization_name="Existing Corp",
            category=CategoryEnum.SPONSOR,
            location="Mumbai",
            contact_person="John Doe - Director",
            contact_channel="existing@corp.com",
            verification_status=VerificationStatusEnum.VERIFIED,
        )
        rec_unique = FinalLeadRecord(
            organization_name="New Corp",
            category=CategoryEnum.SPONSOR,
            location="Bengaluru",
            contact_person="Sarah Connor - VP Marketing",
            contact_channel="sarah@newcorp.com",
            verification_status=VerificationStatusEnum.PATTERN_DERIVED,
        )

        with patch.object(client, "_get_client", return_value=mock_gspread_client):
            res = client.sync_leads([rec_duplicate, rec_unique])
            assert res.is_mock is False
            assert res.rows_appended == 1
            assert res.duplicates_skipped == 1
            mock_worksheet.append_rows.assert_called_once()
            # Verify row appended matches canonical schema
            appended_data = mock_worksheet.append_rows.call_args[0][0]
            assert len(appended_data) == 1
            assert appended_data[0] == rec_unique.to_sheet_row()


# ==============================================================================
# Task 7.3: Local SQLite Storage & Audit Trail Tests
# ==============================================================================

class TestLocalDatabase:
    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self):
        """Initializes SQLite schema for runs, leads, and audit_logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_leads.db"
            db = LocalDatabase(db_path=db_path)
            await db.init_db()
            assert db_path.exists()

    @pytest.mark.asyncio
    async def test_create_and_update_run(self):
        """Creates run record and updates completion metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_leads.db"
            db = LocalDatabase(db_path=db_path)
            await db.init_db()

            await db.create_or_update_run(
                session_id="session_001",
                search_prompt="Find AI sponsors",
                category_focus="Sponsor",
                is_complete=False,
                total_leads_found=0,
            )

            summary = await db.get_run_summary("session_001")
            assert summary is not None
            assert summary["session_id"] == "session_001"
            assert summary["search_prompt"] == "Find AI sponsors"
            assert summary["is_complete"] == 0

            # Update completion
            await db.create_or_update_run(
                session_id="session_001",
                is_complete=True,
                total_leads_found=5,
                google_sheet_url="https://docs.google.com/test",
            )

            updated = await db.get_run_summary("session_001")
            assert updated["is_complete"] == 1
            assert updated["total_leads_found"] == 5
            assert updated["google_sheet_url"] == "https://docs.google.com/test"

    @pytest.mark.asyncio
    async def test_save_and_retrieve_leads(self):
        """Persists verified leads and retrieves them by session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_leads.db"
            db = LocalDatabase(db_path=db_path)
            await db.init_db()

            await db.create_or_update_run("session_002", search_prompt="Test")

            records = [
                FinalLeadRecord(
                    organization_name="Acme Corp",
                    category=CategoryEnum.SPONSOR,
                    location="Bengaluru",
                    contact_person="Sarah Connor - VP Marketing",
                    contact_channel="sarah@acme.com",
                    verification_status=VerificationStatusEnum.VERIFIED,
                ),
                FinalLeadRecord(
                    organization_name="Robotics Society IITB",
                    category=CategoryEnum.COLLEGE_DELEGATION,
                    location="Mumbai",
                    contact_person="Devika Sen - President",
                    contact_channel="https://instagram.com/robotics_iitb",
                    verification_status=VerificationStatusEnum.VERIFIED,
                ),
            ]

            saved_count = await db.save_leads("session_002", records)
            assert saved_count == 2

            retrieved = await db.get_leads_by_session("session_002")
            assert len(retrieved) == 2
            assert retrieved[0]["organization_name"] == "Acme Corp"
            assert retrieved[0]["contact_person"] == "Sarah Connor - VP Marketing"
            assert retrieved[1]["organization_name"] == "Robotics Society IITB"
            assert retrieved[1]["contact_channel"] == "https://instagram.com/robotics_iitb"

    @pytest.mark.asyncio
    async def test_save_and_retrieve_audit_logs(self):
        """Persists and retrieves chronological audit log events."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_leads.db"
            db = LocalDatabase(db_path=db_path)
            await db.init_db()

            await db.create_or_update_run("session_003")

            logs = [
                {"node": "parse_input", "message": "Parsed brochure", "level": "INFO"},
                {"node": "crawl_page", "message": "Dead link 404 encountered", "level": "WARNING"},
                {"node": "verify_contact", "message": "Lead verified", "level": "INFO"},
            ]

            saved = await db.save_audit_logs("session_003", logs)
            assert saved == 3

            retrieved_logs = await db.get_audit_logs_by_session("session_003")
            assert len(retrieved_logs) == 3
            assert retrieved_logs[0]["node"] == "parse_input"
            assert retrieved_logs[1]["level"] == "WARNING"
            assert retrieved_logs[2]["node"] == "verify_contact"
