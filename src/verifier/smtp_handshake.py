"""Non-Intrusive Asynchronous SMTP Handshake & Catch-All Detection Engine (Task 5.3).

Executes polite RFC-compliant SMTP socket handshakes (HELO -> MAIL FROM -> RCPT TO)
without ever transmitting email message data (DATA is never invoked).
Probes for Catch-All mail servers using randomized test addresses.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional
import aiosmtplib
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field


class SMTPHandshakeResult(BaseModel):
    """Result of non-intrusive SMTP recipient verification."""
    model_config = ConfigDict(extra="ignore")

    email: str = Field(..., description="Target candidate email address")
    mx_host: Optional[str] = Field(default=None, description="MX host queried")
    is_deliverable: bool = Field(
        default=False, description="True if recipient accepted by mail server (code 250)"
    )
    is_catch_all: bool = Field(
        default=False, description="True if server accepts randomized fake address"
    )
    smtp_code: Optional[int] = Field(
        default=None, description="Primary SMTP response code for candidate"
    )
    smtp_message: Optional[str] = Field(
        default=None, description="SMTP server reply message string"
    )
    connection_succeeded: bool = Field(
        default=False, description="True if socket connection on port 25 was established"
    )
    port_blocked: bool = Field(
        default=False, description="True if outbound port 25 was blocked or unreachable"
    )
    error_message: Optional[str] = Field(
        default=None, description="Diagnostic error reason if handshake failed"
    )
    logs: list[str] = Field(
        default_factory=list, description="Audit trace of SMTP commands and replies"
    )


class SMTPHandshakeVerifier:
    """Performs polite, non-intrusive SMTP verification and catch-all probing."""

    DEFAULT_HELO_HOST = "verify.leads-agent.com"
    DEFAULT_SENDER = "verify@verified-leads.org"

    def __init__(
        self,
        helo_host: str = DEFAULT_HELO_HOST,
        sender_email: str = DEFAULT_SENDER,
        timeout: float = 8.0,
    ) -> None:
        self.helo_host = helo_host
        self.sender_email = sender_email
        self.timeout = timeout

    async def verify_smtp(
        self,
        email: str,
        mx_host: str,
        domain: Optional[str] = None,
        check_catch_all: bool = True,
    ) -> SMTPHandshakeResult:
        """Connects to MX server, performs non-intrusive RCPT TO, and tests catch-all.

        NEVER invokes DATA. Transmits no email messages.

        Args:
            email: Candidate email to verify.
            mx_host: Primary DNS MX host.
            domain: Domain name (extracted from email if None).
            check_catch_all: Whether to test random fake address for catch-all behavior.

        Returns:
            SMTPHandshakeResult with deliverability status and catch-all flags.
        """
        logs: list[str] = []
        clean_email = email.strip()
        target_domain = domain or (clean_email.split("@")[-1] if "@" in clean_email else "")

        smtp_client = aiosmtplib.SMTP(
            hostname=mx_host,
            port=25,
            timeout=self.timeout,
        )

        try:
            logs.append(f"Connecting to MX host {mx_host}:25...")
            await smtp_client.connect()
            logs.append(f"Connected to {mx_host}:25.")

            # Polite EHLO / HELO
            code, message = await smtp_client.ehlo_or_helo_if_needed(hostname=self.helo_host)
            logs.append(f"HELO/EHLO -> {code}: {message}")

            # MAIL FROM
            code, message = await smtp_client.mail(self.sender_email)
            logs.append(f"MAIL FROM:<{self.sender_email}> -> {code}: {message}")
            if code not in (250, 251):
                logs.append(f"Sender rejected: {code} {message}")
                await smtp_client.quit()
                return SMTPHandshakeResult(
                    email=clean_email,
                    mx_host=mx_host,
                    connection_succeeded=True,
                    is_deliverable=False,
                    smtp_code=code,
                    smtp_message=message,
                    error_message=f"Mail server rejected sender address: {code} {message}",
                    logs=logs,
                )

            # RCPT TO candidate
            code, message = await smtp_client.rcpt(clean_email)
            logs.append(f"RCPT TO:<{clean_email}> -> {code}: {message}")
            is_deliverable = code in (250, 251)
            candidate_code = code
            candidate_msg = message

            is_catch_all = False
            if is_deliverable and check_catch_all and target_domain:
                # Catch-All probe: test a randomized nonexistent recipient
                fake_user = f"chk_probe_{uuid.uuid4().hex[:12]}"
                fake_address = f"{fake_user}@{target_domain}"
                try:
                    await smtp_client.rset()
                    await smtp_client.mail(self.sender_email)
                    probe_code, probe_msg = await smtp_client.rcpt(fake_address)
                    logs.append(f"Catch-all probe RCPT TO:<{fake_address}> -> {probe_code}: {probe_msg}")
                    if probe_code in (250, 251):
                        is_catch_all = True
                        logs.append(f"Domain '{target_domain}' confirmed as Catch-All mail server.")
                except Exception as probe_err:
                    logs.append(f"Catch-all probe non-fatal error: {probe_err}")

            # Reset and gracefully terminate connection without transmitting data
            try:
                await smtp_client.rset()
                await smtp_client.quit()
            except Exception:
                smtp_client.close()

            return SMTPHandshakeResult(
                email=clean_email,
                mx_host=mx_host,
                is_deliverable=is_deliverable,
                is_catch_all=is_catch_all,
                smtp_code=candidate_code,
                smtp_message=candidate_msg,
                connection_succeeded=True,
                logs=logs,
            )

        except (
            aiosmtplib.SMTPConnectError,
            aiosmtplib.SMTPTimeoutError,
            TimeoutError,
            asyncio.TimeoutError,
            OSError,
        ) as net_err:
            error_str = str(net_err)
            is_blocked = any(
                term in error_str.lower()
                for term in ("10060", "10061", "refused", "timed out", "unreachable", "timedout")
            )
            logger.warning(
                f"SMTP connection to {mx_host}:25 failed ({error_str}). "
                f"Port 25 restricted/blocked by local environment."
            )
            logs.append(f"Connection failure: {error_str}")
            return SMTPHandshakeResult(
                email=clean_email,
                mx_host=mx_host,
                connection_succeeded=False,
                port_blocked=is_blocked,
                is_deliverable=False,
                error_message=f"SMTP socket error: {error_str}",
                logs=logs,
            )

        except Exception as exc:
            logger.error(f"Unexpected SMTP handshake exception on {mx_host}: {exc}")
            logs.append(f"Unexpected error: {exc}")
            return SMTPHandshakeResult(
                email=clean_email,
                mx_host=mx_host,
                connection_succeeded=False,
                is_deliverable=False,
                error_message=f"SMTP handshake error: {exc}",
                logs=logs,
            )
        finally:
            if getattr(smtp_client, "is_connected", False):
                try:
                    close_val = smtp_client.close()
                    if asyncio.iscoroutine(close_val):
                        await close_val
                except Exception:
                    pass
