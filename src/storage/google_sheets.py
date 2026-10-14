"""Google Sheets Synchronization Client (Task 7.1 & Task 7.2).

Automates hands-free Google Sheets synchronization:
- Authenticates using Google Service Account credentials via gspread.
- Idempotently creates or opens target spreadsheets and worksheets.
- Formats canonical 6-column header with navy styling (#1E293B) and frozen top row.
- Deduplicates incoming rows against existing sheet data to guarantee idempotency.
- Ingests verified records in rate-limited batch chunks.
- Color-codes the 'Verification Status' column (Green = Verified, Amber = Pattern-Derived).
- Supports offline / mock fallback when credentials are not configured.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from src.models.schema import FinalLeadRecord, VerificationStatusEnum

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False


SHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DEFAULT_SHEET_TITLE = "Autonomous Event Leads - CQ Scraper"
HEADER_BG_COLOR = {"red": 0.118, "green": 0.161, "blue": 0.231}  # #1E293B
HEADER_TEXT_COLOR = {"red": 1.0, "green": 1.0, "blue": 1.0}
VERIFIED_BG_COLOR = {"red": 0.863, "green": 0.988, "blue": 0.906}  # Light green #DCFCE7
PATTERN_BG_COLOR = {"red": 0.996, "green": 0.953, "blue": 0.780}   # Light amber #FEF3C7


class SheetSyncResult(BaseModel):
    """Result of Google Sheets batch synchronization."""
    model_config = ConfigDict(extra="ignore")

    spreadsheet_id: str
    spreadsheet_url: str
    worksheet_title: str
    rows_appended: int
    duplicates_skipped: int
    total_rows: int
    is_mock: bool = False
    logs: list[str] = Field(default_factory=list)


class GoogleSheetsSyncClient:
    """Manages Google Sheets authentication, header styling, deduplication, and batch insertion."""

    def __init__(
        self,
        credentials_path: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
        sheet_title: str = DEFAULT_SHEET_TITLE,
    ) -> None:
        self.credentials_path = credentials_path or settings.google_application_credentials
        self.spreadsheet_id = spreadsheet_id or settings.google_spreadsheet_id
        self.sheet_title = sheet_title
        self._client: Optional[Any] = None

    def _get_client(self) -> Optional[Any]:
        """Initializes and returns authenticated gspread client if credentials exist."""
        if not GSPREAD_AVAILABLE:
            logger.warning("gspread or google-auth not installed; running in mock storage mode.")
            return None

        if self._client is not None:
            return self._client

        # Check credentials file path
        if self.credentials_path and Path(self.credentials_path).exists():
            try:
                creds = Credentials.from_service_account_file(
                    self.credentials_path, scopes=SHEET_SCOPES
                )
                self._client = gspread.authorize(creds)
                logger.info(f"Authenticated Google Sheets service account from {self.credentials_path}")
                return self._client
            except Exception as e:
                logger.warning(f"Failed to authenticate Google Service Account from file: {e}")

        # Check environment JSON string
        import os
        raw_json = os.getenv("GOOGLE_SHEET_CREDENTIALS_JSON")
        if raw_json:
            try:
                data = json.loads(raw_json)
                creds = Credentials.from_service_account_info(data, scopes=SHEET_SCOPES)
                self._client = gspread.authorize(creds)
                logger.info("Authenticated Google Sheets service account from JSON env string.")
                return self._client
            except Exception as e:
                logger.warning(f"Failed to authenticate Google Service Account from JSON env: {e}")

        logger.info("Google credentials not found or unconfigured; falling back to mock sheets mode.")
        return None

    def initialize_spreadsheet(self, client: Any) -> tuple[Any, Any]:
        """Opens or creates the designated spreadsheet and worksheet."""
        spreadsheet = None
        if self.spreadsheet_id:
            try:
                spreadsheet = client.open_by_key(self.spreadsheet_id)
            except Exception as e:
                logger.warning(f"Could not open spreadsheet by ID {self.spreadsheet_id}: {e}")

        if spreadsheet is None:
            # Create new spreadsheet
            spreadsheet = client.create(self.sheet_title)
            try:
                # Share with anyone as viewer
                spreadsheet.share(None, perm_type="anyone", role="reader")
            except Exception as e:
                logger.debug(f"Could not make spreadsheet publicly readable: {e}")

        worksheet = spreadsheet.sheet1
        return spreadsheet, worksheet

    def ensure_headers_and_styling(self, worksheet: Any) -> bool:
        """Verifies canonical 6-column header row exists and applies navy styling."""
        canonical_headers = FinalLeadRecord.sheet_headers()
        existing = []
        try:
            existing = worksheet.row_values(1)
        except Exception:
            pass

        if existing != canonical_headers:
            logger.info("Applying canonical 6-column headers and navy styling to worksheet.")
            worksheet.insert_row(canonical_headers, index=1)

            # Style header row (Row 1, Cols 1-6)
            try:
                worksheet.format("A1:F1", {
                    "backgroundColor": HEADER_BG_COLOR,
                    "horizontalAlignment": "CENTER",
                    "textFormat": {
                        "foregroundColor": HEADER_TEXT_COLOR,
                        "fontSize": 10,
                        "bold": True,
                    },
                })
                worksheet.freeze(rows=1)
            except Exception as style_err:
                logger.warning(f"Failed applying header cell formatting: {style_err}")
            return True
        return False

    def sync_leads(
        self,
        records: list[FinalLeadRecord],
        batch_size: int = 15,
    ) -> SheetSyncResult:
        """Deduplicates incoming leads and batch appends to Google Sheets.

        Args:
            records: Verified FinalLeadRecord objects.
            batch_size: Chunk size for rate-limited batch appending.

        Returns:
            SheetSyncResult with appended counts, URLs, and logs.
        """
        logs: list[str] = []
        client = self._get_client()

        # Offline / Mock Fallback Mode
        if client is None:
            mock_id = self.spreadsheet_id or "mock_sheet_101"
            mock_url = f"https://docs.google.com/spreadsheets/d/{mock_id}/edit"
            logs.append("Executed mock sheet sync: Credentials not configured.")
            return SheetSyncResult(
                spreadsheet_id=mock_id,
                spreadsheet_url=mock_url,
                worksheet_title="Sheet1",
                rows_appended=len(records),
                duplicates_skipped=0,
                total_rows=len(records) + 1,
                is_mock=True,
                logs=logs,
            )

        try:
            spreadsheet, worksheet = self.initialize_spreadsheet(client)
            self.ensure_headers_and_styling(worksheet)

            # Idempotency: Deduplicate against existing sheet entries
            existing_orgs = set()
            existing_channels = set()
            try:
                org_col = worksheet.col_values(1)[1:]  # skip header
                channel_col = worksheet.col_values(5)[1:]  # skip header
                existing_orgs = {o.strip().lower() for o in org_col if o.strip()}
                existing_channels = {c.strip().lower() for c in channel_col if c.strip()}
            except Exception as read_err:
                logs.append(f"Could not read existing sheet rows for deduplication: {read_err}")

            new_rows: list[list[str]] = []
            duplicates_count = 0

            for rec in records:
                org_clean = rec.organization_name.strip().lower()
                chan_clean = rec.contact_channel.strip().lower()

                if org_clean in existing_orgs or chan_clean in existing_channels:
                    duplicates_count += 1
                    logs.append(f"Skipped duplicate lead: '{rec.organization_name}' ({rec.contact_channel})")
                    continue

                new_rows.append(rec.to_sheet_row())
                existing_orgs.add(org_clean)
                existing_channels.add(chan_clean)

            # Batch append in rate-limited chunks
            rows_appended = len(new_rows)
            for i in range(0, rows_appended, batch_size):
                chunk = new_rows[i: i + batch_size]
                worksheet.append_rows(chunk, value_input_option="USER_ENTERED")
                logs.append(f"Batch appended {len(chunk)} rows to Google Sheet.")

            # Conditional formatting / color-coding on status column
            try:
                # Color code verification status cells
                all_status = worksheet.col_values(6)[1:]
                start_row = len(all_status) - rows_appended + 2
                for idx, row in enumerate(new_rows):
                    current_row = start_row + idx
                    status_val = row[5]
                    color = VERIFIED_BG_COLOR if status_val == VerificationStatusEnum.VERIFIED.value else PATTERN_BG_COLOR
                    worksheet.format(f"F{current_row}", {"backgroundColor": color})
            except Exception as format_err:
                logger.debug(f"Optional status color formatting skipped: {format_err}")

            total_rows = len(worksheet.get_all_values())
            sheet_id = str(getattr(spreadsheet, "id", "sheet_id"))
            sheet_url = str(
                getattr(spreadsheet, "url", f"https://docs.google.com/spreadsheets/d/{sheet_id}")
            )
            ws_title = str(getattr(worksheet, "title", "Sheet1"))

            return SheetSyncResult(
                spreadsheet_id=sheet_id,
                spreadsheet_url=sheet_url,
                worksheet_title=ws_title,
                rows_appended=rows_appended,
                duplicates_skipped=duplicates_count,
                total_rows=total_rows,
                is_mock=False,
                logs=logs,
            )

        except Exception as exc:
            logger.error(f"Google Sheets sync exception: {exc}")
            logs.append(f"Google Sheets sync failed: {exc}")
            mock_id = self.spreadsheet_id or "fallback_sheet"
            return SheetSyncResult(
                spreadsheet_id=mock_id,
                spreadsheet_url=f"https://docs.google.com/spreadsheets/d/{mock_id}",
                worksheet_title="Sheet1",
                rows_appended=0,
                duplicates_skipped=0,
                total_rows=0,
                is_mock=True,
                logs=logs,
            )
