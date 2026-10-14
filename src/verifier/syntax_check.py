"""RFC 5321/5322 Email Syntax & Domain Typo Validator (Task 5.1).

Validates email syntax via email-validator, detects common domain typos,
and enforces negative filters against generic corporate/support mailboxes.
"""

from __future__ import annotations

import re
from typing import Optional
from email_validator import EmailNotValidError, validate_email
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from src.models.schema import GENERIC_EMAIL_PATTERN


# Dictionary of frequent domain typos to canonical replacements
COMMON_DOMAIN_TYPOS: dict[str, str] = {
    "gmial.com": "gmail.com",
    "gamil.com": "gmail.com",
    "gmaill.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gamil.co": "gmail.com",
    "outlok.com": "outlook.com",
    "outllok.com": "outlook.com",
    "outloo.com": "outlook.com",
    "hotmial.com": "hotmail.com",
    "hotmai.com": "hotmail.com",
    "hotmali.com": "hotmail.com",
    "yaho.com": "yahoo.com",
    "yahooo.com": "yahoo.com",
    "yaboo.com": "yahoo.com",
    "icoud.com": "icloud.com",
    "iclud.com": "icloud.com",
    "rediffmial.com": "rediffmail.com",
}


class SyntaxCheckResult(BaseModel):
    """Result of an email syntax and typo evaluation."""
    model_config = ConfigDict(extra="ignore")

    email: str = Field(..., description="Original raw candidate email")
    normalized_email: Optional[str] = Field(
        default=None, description="Cleaned, canonicalized email"
    )
    domain: Optional[str] = Field(default=None, description="Extracted domain")
    is_valid_syntax: bool = Field(
        default=False, description="True if passes RFC 5321/5322 rules"
    )
    is_generic: bool = Field(
        default=False, description="True if matches generic central mailbox prefixes"
    )
    has_typo: bool = Field(
        default=False, description="True if a common domain typo was identified"
    )
    suggested_correction: Optional[str] = Field(
        default=None, description="Suggested correction with fixed domain"
    )
    error_message: Optional[str] = Field(
        default=None, description="Failure reason if syntax invalid"
    )


class EmailSyntaxValidator:
    """Validates email formatting, catches domain typos, and checks generic inboxes."""

    @classmethod
    def check_typo(cls, domain: str) -> tuple[bool, Optional[str]]:
        """Checks if a domain contains a known typo and returns suggested fix."""
        clean_domain = domain.strip().lower()
        if clean_domain in COMMON_DOMAIN_TYPOS:
            return True, COMMON_DOMAIN_TYPOS[clean_domain]
        return False, None

    @classmethod
    def is_generic_email(cls, email: str) -> bool:
        """Checks whether the address matches central/role-based mailbox prefixes."""
        clean = email.strip()
        return bool(GENERIC_EMAIL_PATTERN.match(clean))

    @classmethod
    def validate(cls, email: str) -> SyntaxCheckResult:
        """Validates candidate email against RFC syntax, typos, and generic filters.

        Args:
            email: Raw candidate email address.

        Returns:
            SyntaxCheckResult with validation flags and normalized values.
        """
        if not email or not isinstance(email, str):
            return SyntaxCheckResult(
                email=str(email or ""),
                is_valid_syntax=False,
                error_message="Email is empty or not a string",
            )

        clean_email = email.strip()

        # Step 1: Reject generic inboxes immediately
        if cls.is_generic_email(clean_email):
            logger.warning(
                f"Generic central inbox rejected by syntax validator: {clean_email}"
            )
            return SyntaxCheckResult(
                email=clean_email,
                is_valid_syntax=False,
                is_generic=True,
                error_message=(
                    f"Generic central mailbox prefix is prohibited: '{clean_email}'. "
                    f"Must be a direct personal email."
                ),
            )

        # Step 2: Validate via email-validator (RFC 5321/5322 compliance)
        try:
            # check_deliverability=False because DNS MX and SMTP are validated in later stages
            parsed = validate_email(
                clean_email,
                check_deliverability=False,
                test_environment=False,
            )
            normalized = parsed.normalized
            domain = parsed.domain.lower()
            local_part = parsed.local_part

            # Step 3: Check for domain typo
            has_typo, suggested_domain = cls.check_typo(domain)
            suggested_email = None
            if has_typo and suggested_domain:
                suggested_email = f"{local_part}@{suggested_domain}"
                logger.info(
                    f"Domain typo detected: {domain} -> {suggested_domain} ({clean_email} -> {suggested_email})"
                )

            return SyntaxCheckResult(
                email=clean_email,
                normalized_email=normalized,
                domain=domain,
                is_valid_syntax=True,
                is_generic=False,
                has_typo=has_typo,
                suggested_correction=suggested_email,
            )

        except EmailNotValidError as err:
            logger.debug(f"Email syntax validation failed for '{clean_email}': {err}")
            return SyntaxCheckResult(
                email=clean_email,
                is_valid_syntax=False,
                is_generic=False,
                error_message=str(err),
            )

