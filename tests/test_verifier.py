"""Unit tests for Contact Deliverability & Verification Engine (Phase 5).

Tests:
- Task 5.1: RFC 5321/5322 syntax validation, typo detection, and generic inbox filtering.
- Task 5.2: Asynchronous DNS MX record resolver and Null MX handling.
- Task 5.3: Non-intrusive SMTP socket handshake and catch-all detection.
- Task 5.4: Social profile liveness and personal account verification.
- Task 5.5: Master ContactVerifier pipeline and FinalLeadRecord synthesis.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from src.models.schema import (
    CategoryEnum,
    DecisionMakerCandidate,
    FinalLeadRecord,
    VerificationStatusEnum,
)
from src.verifier.contact_verifier import ContactVerifier, VerificationResult
from src.verifier.mx_resolver import DNSMXResolver, MXRecord, MXResolutionResult
from src.verifier.smtp_handshake import SMTPHandshakeResult, SMTPHandshakeVerifier
from src.verifier.social_validator import SocialProfileValidator, SocialValidationResult
from src.verifier.syntax_check import EmailSyntaxValidator, SyntaxCheckResult


# ==============================================================================
# Task 5.1: Syntax Validation & Typo Detection Tests
# ==============================================================================

class TestEmailSyntaxValidator:
    def test_valid_syntax(self):
        """Standard human email formats pass RFC validation."""
        res = EmailSyntaxValidator.validate("sarah.connor@acme.com")
        assert res.is_valid_syntax is True
        assert res.normalized_email == "sarah.connor@acme.com"
        assert res.domain == "acme.com"
        assert res.is_generic is False
        assert res.has_typo is False

    def test_detect_domain_typo(self):
        """Detects frequent domain typos and offers suggested correction."""
        res = EmailSyntaxValidator.validate("arun.kumar@gmial.com")
        assert res.is_valid_syntax is True
        assert res.has_typo is True
        assert res.suggested_correction == "arun.kumar@gmail.com"

        res_outlook = EmailSyntaxValidator.validate("test@outlok.com")
        assert res_outlook.has_typo is True
        assert res_outlook.suggested_correction == "test@outlook.com"

    def test_reject_generic_central_inboxes(self):
        """Rejects generic corporate/support mailboxes (info@, contact@, admin@)."""
        generic_emails = [
            "info@acme.com",
            "contact@startup.io",
            "support@help.org",
            "admin@college.edu",
            "sales@store.com",
            "hello@agency.in",
        ]
        for email in generic_emails:
            res = EmailSyntaxValidator.validate(email)
            assert res.is_valid_syntax is False
            assert res.is_generic is True
            assert "prohibited" in (res.error_message or "").lower()

    def test_invalid_syntax_formats(self):
        """Catches malformed strings, missing @, spaces, and empty inputs."""
        assert EmailSyntaxValidator.validate("").is_valid_syntax is False
        assert EmailSyntaxValidator.validate("not-an-email").is_valid_syntax is False
        assert EmailSyntaxValidator.validate("user@").is_valid_syntax is False
        assert EmailSyntaxValidator.validate("@domain.com").is_valid_syntax is False
        assert EmailSyntaxValidator.validate("user @domain.com").is_valid_syntax is False


# ==============================================================================
# Task 5.2: DNS MX Resolver Tests
# ==============================================================================

class TestDNSMXResolver:
    @pytest.mark.asyncio
    async def test_resolve_mx_success(self):
        """Resolves and sorts MX records by preference priority."""
        resolver = DNSMXResolver()

        # Mock dnspython answers
        mock_rdata_1 = MagicMock()
        mock_rdata_1.exchange = "mail2.acme.com."
        mock_rdata_1.preference = 20

        mock_rdata_2 = MagicMock()
        mock_rdata_2.exchange = "mail1.acme.com."
        mock_rdata_2.preference = 10

        with patch.object(
            resolver.resolver,
            "resolve",
            new_callable=AsyncMock,
            return_value=[mock_rdata_1, mock_rdata_2],
        ):
            res = await resolver.resolve_mx("acme.com")
            assert res.has_mx is True
            assert res.primary_host == "mail1.acme.com"
            assert len(res.records) == 2
            assert res.records[0].host == "mail1.acme.com"
            assert res.records[0].preference == 10
            assert res.records[1].host == "mail2.acme.com"
            assert res.records[1].preference == 20

    @pytest.mark.asyncio
    async def test_resolve_rfc7505_null_mx(self):
        """Identifies RFC 7505 Null MX indicating domain explicitly rejects email."""
        resolver = DNSMXResolver()

        mock_null_mx = MagicMock()
        mock_null_mx.exchange = "."
        mock_null_mx.preference = 0

        with patch.object(
            resolver.resolver,
            "resolve",
            new_callable=AsyncMock,
            return_value=[mock_null_mx],
        ):
            res = await resolver.resolve_mx("nomail.example.com")
            assert res.has_mx is False
            assert res.is_null_mx is True
            assert "Null MX" in (res.error_message or "")

    @pytest.mark.asyncio
    async def test_resolve_nxdomain(self):
        """Handles nonexistent domains gracefully."""
        import dns.resolver

        resolver = DNSMXResolver()
        with patch.object(
            resolver.resolver,
            "resolve",
            new_callable=AsyncMock,
            side_effect=dns.resolver.NXDOMAIN,
        ):
            res = await resolver.resolve_mx("nonexistent-domain-12345.xyz")
            assert res.has_mx is False
            assert "NXDOMAIN" in (res.error_message or "")


# ==============================================================================
# Task 5.3: SMTP Handshake & Catch-All Tests
# ==============================================================================

class TestSMTPHandshakeVerifier:
    @pytest.mark.asyncio
    async def test_smtp_deliverable_non_catch_all(self):
        """Server returns 250 for candidate and 550 for probe -> Deliverable & Non-Catch-All."""
        verifier = SMTPHandshakeVerifier()

        mock_smtp = AsyncMock()
        mock_smtp.is_connected = True
        mock_smtp.connect = AsyncMock()
        mock_smtp.ehlo_or_helo_if_needed = AsyncMock(return_value=(250, "OK"))
        mock_smtp.mail = AsyncMock(return_value=(250, "OK"))
        # Candidate accepted (250), fake catch-all rejected (550)
        mock_smtp.rcpt = AsyncMock(side_effect=[(250, "Recipient OK"), (550, "User unknown")])
        mock_smtp.rset = AsyncMock()
        mock_smtp.quit = AsyncMock()

        with patch("aiosmtplib.SMTP", return_value=mock_smtp):
            res = await verifier.verify_smtp("sarah.connor@acme.com", "mail.acme.com")
            assert res.connection_succeeded is True
            assert res.is_deliverable is True
            assert res.is_catch_all is False
            assert res.smtp_code == 250
            # Ensure DATA was NEVER called
            assert not hasattr(mock_smtp, "data") or not mock_smtp.data.called

    @pytest.mark.asyncio
    async def test_smtp_catch_all_detection(self):
        """Server returns 250 for candidate and 250 for fake address -> Catch-All."""
        verifier = SMTPHandshakeVerifier()

        mock_smtp = AsyncMock()
        mock_smtp.is_connected = True
        mock_smtp.connect = AsyncMock()
        mock_smtp.ehlo_or_helo_if_needed = AsyncMock(return_value=(250, "OK"))
        mock_smtp.mail = AsyncMock(return_value=(250, "OK"))
        # Both candidate and fake address return 250
        mock_smtp.rcpt = AsyncMock(return_value=(250, "OK"))
        mock_smtp.rset = AsyncMock()
        mock_smtp.quit = AsyncMock()

        with patch("aiosmtplib.SMTP", return_value=mock_smtp):
            res = await verifier.verify_smtp("sarah.connor@acme.com", "mail.acme.com")
            assert res.connection_succeeded is True
            assert res.is_deliverable is True
            assert res.is_catch_all is True

    @pytest.mark.asyncio
    async def test_smtp_mailbox_not_found(self):
        """Server returns 550 for candidate -> is_deliverable=False."""
        verifier = SMTPHandshakeVerifier()

        mock_smtp = AsyncMock()
        mock_smtp.is_connected = True
        mock_smtp.connect = AsyncMock()
        mock_smtp.ehlo_or_helo_if_needed = AsyncMock(return_value=(250, "OK"))
        mock_smtp.mail = AsyncMock(return_value=(250, "OK"))
        mock_smtp.rcpt = AsyncMock(return_value=(550, "5.1.1 User unknown"))
        mock_smtp.rset = AsyncMock()
        mock_smtp.quit = AsyncMock()

        with patch("aiosmtplib.SMTP", return_value=mock_smtp):
            res = await verifier.verify_smtp("unknown.person@acme.com", "mail.acme.com")
            assert res.connection_succeeded is True
            assert res.is_deliverable is False
            assert res.smtp_code == 550

    @pytest.mark.asyncio
    async def test_smtp_port_25_blocked_handled_gracefully(self):
        """When port 25 is blocked by network, returns connection_succeeded=False without crashing."""
        import aiosmtplib

        verifier = SMTPHandshakeVerifier()
        with patch("aiosmtplib.SMTP.connect", side_effect=aiosmtplib.SMTPConnectError("Connection refused")):
            res = await verifier.verify_smtp("test@acme.com", "mail.acme.com")
            assert res.connection_succeeded is False
            assert res.is_deliverable is False
            assert res.port_blocked is True


# ==============================================================================
# Task 5.4: Social Profile Validator Tests
# ==============================================================================

class TestSocialProfileValidator:
    def test_classify_personal_vs_company_urls(self):
        """Differentiates personal profiles from company/search URLs."""
        # LinkedIn
        p1, is_p1 = SocialProfileValidator.classify_url("https://www.linkedin.com/in/sarah-connor")
        assert p1 == "linkedin" and is_p1 is True

        p2, is_p2 = SocialProfileValidator.classify_url("https://www.linkedin.com/company/acme-corp")
        assert p2 == "linkedin" and is_p2 is False

        # Instagram
        p3, is_p3 = SocialProfileValidator.classify_url("https://instagram.com/robotics_society")
        assert p3 == "instagram" and is_p3 is True

        p4, is_p4 = SocialProfileValidator.classify_url("https://instagram.com/p/Cxyz1234")
        assert p4 == "instagram" and is_p4 is False

        # Twitter / X
        p5, is_p5 = SocialProfileValidator.classify_url("https://x.com/sarahconnor")
        assert p5 == "twitter" and is_p5 is True

        p6, is_p6 = SocialProfileValidator.classify_url("https://x.com/explore")
        assert p6 == "twitter" and is_p6 is False

    @pytest.mark.asyncio
    async def test_validate_profile_url_success(self):
        """Live personal profile returning HTTP 200 is marked live and verified."""
        validator = SocialProfileValidator()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>Sarah Connor - VP Marketing Profile</body></html>"

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_resp)

        res = await validator.validate_profile_url(
            "https://www.linkedin.com/in/sarah-connor", client=mock_client
        )
        assert res.is_personal_profile is True
        assert res.is_live is True
        assert res.status_code == 200

    @pytest.mark.asyncio
    async def test_validate_profile_url_404(self):
        """Deleted profile returning 404 is marked not live."""
        validator = SocialProfileValidator()

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_resp)

        res = await validator.validate_profile_url(
            "https://www.linkedin.com/in/nonexistent-user-999", client=mock_client
        )
        assert res.is_personal_profile is True
        assert res.is_live is False
        assert res.status_code == 404


# ==============================================================================
# Task 5.5: Master ContactVerifier Integration Tests
# ==============================================================================

class TestContactVerifier:
    @pytest.mark.asyncio
    async def test_verify_contact_direct_email_success(self):
        """Direct candidate email passing syntax, MX, and SMTP 250 -> 'Verified'."""
        verifier = ContactVerifier()

        # Mock syntax check
        mock_syntax = MagicMock()
        mock_syntax.validate.return_value = SyntaxCheckResult(
            email="sarah.connor@acme.com",
            normalized_email="sarah.connor@acme.com",
            domain="acme.com",
            is_valid_syntax=True,
            is_generic=False,
            has_typo=False,
        )

        # Mock MX
        mock_mx = AsyncMock()
        mock_mx.resolve_mx.return_value = MXResolutionResult(
            domain="acme.com",
            has_mx=True,
            primary_host="mail.acme.com",
            records=[MXRecord(host="mail.acme.com", preference=10)],
        )

        # Mock SMTP
        mock_smtp = AsyncMock()
        mock_smtp.verify_smtp.return_value = SMTPHandshakeResult(
            email="sarah.connor@acme.com",
            mx_host="mail.acme.com",
            connection_succeeded=True,
            is_deliverable=True,
            is_catch_all=False,
            smtp_code=250,
        )

        verifier.syntax_validator = mock_syntax
        verifier.mx_resolver = mock_mx
        verifier.smtp_verifier = mock_smtp

        result = await verifier.verify_contact(
            email_candidate="sarah.connor@acme.com",
            decision_maker_name="Sarah Connor",
        )

        assert result.is_deliverable is True
        assert result.contact_channel == "sarah.connor@acme.com"
        assert result.status == VerificationStatusEnum.VERIFIED
        assert "SMTP_HANDSHAKE_250" in result.verification_method

    @pytest.mark.asyncio
    async def test_verify_contact_catch_all_pattern_derived(self):
        """Catch-All domain with pattern derivation -> 'Pattern-Derived' status."""
        verifier = ContactVerifier()

        mock_syntax = MagicMock()
        mock_syntax.validate.return_value = SyntaxCheckResult(
            email="sarah.connor@acme.com",
            normalized_email="sarah.connor@acme.com",
            domain="acme.com",
            is_valid_syntax=True,
            is_generic=False,
            has_typo=False,
        )

        mock_mx = AsyncMock()
        mock_mx.resolve_mx.return_value = MXResolutionResult(
            domain="acme.com",
            has_mx=True,
            primary_host="mail.acme.com",
            records=[MXRecord(host="mail.acme.com", preference=10)],
        )

        mock_smtp = AsyncMock()
        mock_smtp.verify_smtp.return_value = SMTPHandshakeResult(
            email="sarah.connor@acme.com",
            mx_host="mail.acme.com",
            connection_succeeded=True,
            is_deliverable=True,
            is_catch_all=True,  # Catch-All!
            smtp_code=250,
        )

        verifier.syntax_validator = mock_syntax
        verifier.mx_resolver = mock_mx
        verifier.smtp_verifier = mock_smtp

        # Provided domain samples matching pattern {first}.{last}
        samples = ["alice.smith@acme.com", "bob.jones@acme.com"]

        result = await verifier.verify_contact(
            email_candidate="sarah.connor@acme.com",
            decision_maker_name="Sarah Connor",
            domain_email_samples=samples,
            is_pattern_derived=True,
        )

        assert result.is_deliverable is True
        assert result.status == VerificationStatusEnum.PATTERN_DERIVED
        assert "SMTP_CATCHALL_PATTERN" in result.verification_method

    @pytest.mark.asyncio
    async def test_verify_contact_email_fails_fallback_to_profile(self):
        """When candidate email returns 550, falls back to live personal profile -> 'Verified'."""
        verifier = ContactVerifier()

        # Syntax check OK
        mock_syntax = MagicMock()
        mock_syntax.validate.return_value = SyntaxCheckResult(
            email="bad.email@acme.com",
            domain="acme.com",
            is_valid_syntax=True,
        )

        # MX OK
        mock_mx = AsyncMock()
        mock_mx.resolve_mx.return_value = MXResolutionResult(
            domain="acme.com",
            has_mx=True,
            primary_host="mail.acme.com",
        )

        # SMTP returns 550 Mailbox Not Found
        mock_smtp = AsyncMock()
        mock_smtp.verify_smtp.return_value = SMTPHandshakeResult(
            email="bad.email@acme.com",
            connection_succeeded=True,
            is_deliverable=False,
            smtp_code=550,
            error_message="User not found",
        )

        # Social profile validator returns live profile
        mock_social = AsyncMock()
        mock_social.validate_profile_url.return_value = SocialValidationResult(
            url="https://linkedin.com/in/sarah-connor",
            normalized_url="https://linkedin.com/in/sarah-connor",
            platform="linkedin",
            is_personal_profile=True,
            is_live=True,
            status_code=200,
        )

        verifier.syntax_validator = mock_syntax
        verifier.mx_resolver = mock_mx
        verifier.smtp_verifier = mock_smtp
        verifier.social_validator = mock_social

        result = await verifier.verify_contact(
            email_candidate="bad.email@acme.com",
            profile_url_candidate="https://linkedin.com/in/sarah-connor",
            decision_maker_name="Sarah Connor",
        )

        assert result.is_deliverable is True
        assert result.contact_channel == "https://linkedin.com/in/sarah-connor"
        assert result.status == VerificationStatusEnum.VERIFIED
        assert result.candidate_type == "profile_url"

    @pytest.mark.asyncio
    async def test_verify_contact_completely_unverified_discarded(self):
        """When neither email nor profile can be verified, returns is_deliverable=False."""
        verifier = ContactVerifier()

        # Generic email rejected by syntax validator
        mock_syntax = MagicMock()
        mock_syntax.validate.return_value = SyntaxCheckResult(
            email="info@acme.com",
            is_valid_syntax=False,
            is_generic=True,
        )

        # Profile is 404 dead
        mock_social = AsyncMock()
        mock_social.validate_profile_url.return_value = SocialValidationResult(
            url="https://linkedin.com/in/deleted-user",
            normalized_url="https://linkedin.com/in/deleted-user",
            is_personal_profile=True,
            is_live=False,
            status_code=404,
        )

        verifier.syntax_validator = mock_syntax
        verifier.social_validator = mock_social

        result = await verifier.verify_contact(
            email_candidate="info@acme.com",
            profile_url_candidate="https://linkedin.com/in/deleted-user",
            decision_maker_name="Sarah Connor",
        )

        assert result.is_deliverable is False
        assert result.contact_channel == ""

    @pytest.mark.asyncio
    async def test_verify_decision_maker_produces_final_lead_record(self):
        """verify_decision_maker synthesizes a strict 6-field FinalLeadRecord."""
        verifier = ContactVerifier()

        candidate = DecisionMakerCandidate(
            organization_name="Acme Technologies",
            category=CategoryEnum.SPONSOR,
            location="Bengaluru",
            name="Sarah Connor",
            role="VP Marketing",
            email_candidate="sarah.connor@acme.com",
            source_url="https://acme.com/team",
        )

        # Mock direct verification success
        verifier.verify_contact = AsyncMock(
            return_value=VerificationResult(
                contact_channel="sarah.connor@acme.com",
                status=VerificationStatusEnum.VERIFIED,
                is_deliverable=True,
                verification_method="SMTP_HANDSHAKE_250",
            )
        )

        record = await verifier.verify_decision_maker(candidate)
        assert record is not None
        assert isinstance(record, FinalLeadRecord)
        assert record.organization_name == "Acme Technologies"
        assert record.category == CategoryEnum.SPONSOR
        assert record.location == "Bengaluru"
        assert record.contact_person == "Sarah Connor - VP Marketing"
        assert record.contact_channel == "sarah.connor@acme.com"
        assert record.verification_status == VerificationStatusEnum.VERIFIED

        # Check sheet row matches 6 fields
        sheet_row = record.to_sheet_row()
        assert len(sheet_row) == 6
        assert sheet_row == [
            "Acme Technologies",
            "Sponsor",
            "Bengaluru",
            "Sarah Connor - VP Marketing",
            "sarah.connor@acme.com",
            "Verified",
        ]

    @pytest.mark.asyncio
    async def test_verify_decision_maker_returns_none_if_unverified(self):
        """Unverified candidates return None (Zero-Hallucination mandate)."""
        verifier = ContactVerifier()

        candidate = DecisionMakerCandidate(
            organization_name="Acme Corp",
            category=CategoryEnum.SPONSOR,
            location="Mumbai",
            name="Unknown Lead",
            role="Sales",
            email_candidate="bad@nowhere.com",
            source_url="https://acme.com",
        )

        verifier.verify_contact = AsyncMock(
            return_value=VerificationResult(
                contact_channel="",
                status=VerificationStatusEnum.VERIFIED,
                is_deliverable=False,
                verification_method="REJECTED_UNVERIFIED",
            )
        )

        record = await verifier.verify_decision_maker(candidate)
        assert record is None

