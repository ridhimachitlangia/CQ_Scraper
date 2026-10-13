"""Domain schemas and data contracts for CQ Scraper.

Enforces strict Pydantic v2 validation and the exact 6-field output table schema:
1. Organization Name
2. Category (Sponsor | College Delegation)
3. Location
4. Contact Person ([Full Name] - [Role])
5. Contact Channel (Deliverable email | Authentic profile link)
6. Verification Status (Verified | Pattern-Derived)
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class CategoryEnum(str, Enum):
    """Outreach target category."""
    SPONSOR = "Sponsor"
    COLLEGE_DELEGATION = "College Delegation"


class VerificationStatusEnum(str, Enum):
    """Deliverability verification classification."""
    VERIFIED = "Verified"
    PATTERN_DERIVED = "Pattern-Derived"


# Prohibited generic inboxes regex
GENERIC_EMAIL_PATTERN = re.compile(
    r"^(info|contact|support|help|sales|hello|enquiry|office|admin|careers|press|media|billing|marketing|team|general|inquiries)@",
    re.IGNORECASE,
)

# Prohibited placeholder values
PLACEHOLDER_VALUES = {"n/a", "na", "unknown", "none", "null", "undefined", "tbd", "pending"}


class TargetOrganization(BaseModel):
    """Seed target company or collegiate society identified for research."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Name of the company or student society")
    category: CategoryEnum = Field(..., description="Sponsor or College Delegation")
    city: Optional[str] = Field(default=None, description="Headquarters or campus city")
    website: Optional[str] = Field(default=None, description="Official website URL")
    domain: Optional[str] = Field(default=None, description="Clean web domain (e.g., acme.com)")
    notes: Optional[str] = Field(default=None, description="Extraction context or origin")


class DecisionMakerRole(BaseModel):
    """Personal identity and corporate/society position of an individual."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Full personal name of the individual")
    title: str = Field(..., description="Official job title or society leadership role")
    linkedin_url: Optional[str] = Field(default=None, description="Personal LinkedIn profile URL")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        clean = value.strip()
        if clean.lower() in PLACEHOLDER_VALUES or len(clean.split()) < 1:
            raise ValueError(f"Invalid decision maker name: '{value}'")
        return clean

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        clean = value.strip()
        if clean.lower() in PLACEHOLDER_VALUES:
            raise ValueError(f"Invalid decision maker title: '{value}'")
        return clean


class DecisionMakerCandidate(BaseModel):
    """Candidate lead before final verification."""
    model_config = ConfigDict(extra="ignore")

    organization_name: str = Field(..., description="Target company or society name")
    category: CategoryEnum = Field(..., description="Sponsor or College Delegation")
    location: str = Field(..., description="City or base location")
    name: str = Field(..., description="Decision maker's full name")
    role: str = Field(..., description="Decision maker's title/position")
    email_candidate: Optional[str] = Field(default=None, description="Candidate email address")
    profile_url_candidate: Optional[str] = Field(default=None, description="Candidate profile URL")
    source_url: str = Field(..., description="Grounding URL where contact was discovered")
    raw_snippet: Optional[str] = Field(default=None, description="Contextual snippet for audit")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)


class EmailPatternRule(BaseModel):
    """Discovered email syntax pattern for a specific domain."""
    model_config = ConfigDict(extra="ignore")

    domain: str = Field(..., description="Email domain e.g., acme.com")
    pattern_format: str = Field(
        ..., description="Format template e.g., '{first}.{last}@{domain}', '{first}@{domain}'"
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    sample_emails: list[str] = Field(default_factory=list, description="Grounding observed emails")


class ScrapedPageSnapshot(BaseModel):
    """Snapshot of a crawled web page."""
    model_config = ConfigDict(extra="ignore")

    url: str = Field(..., description="Target URL")
    status_code: int = Field(default=200, description="HTTP response code")
    title: Optional[str] = Field(default=None, description="Page title")
    markdown_content: str = Field(default="", description="Clean extracted markdown content")
    discovered_internal_links: list[str] = Field(default_factory=list)
    discovered_emails: list[str] = Field(default_factory=list)
    discovered_social_links: list[str] = Field(default_factory=list)
    is_dead: bool = Field(default=False, description="Flag indicating dead, 404, or blocked page")


class FinalLeadRecord(BaseModel):
    """Final verified lead record strictly adhering to the 6-field sheet schema."""
    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        frozen=False,
    )

    organization_name: str = Field(..., alias="Organization Name")
    category: CategoryEnum = Field(..., alias="Category")
    location: str = Field(..., alias="Location")
    contact_person: str = Field(
        ...,
        alias="Contact Person",
        description="Formatted strictly as '[Full Name] - [Role]'",
    )
    contact_channel: str = Field(
        ...,
        alias="Contact Channel",
        description="Verified deliverable email address or authentic live profile link",
    )
    verification_status: VerificationStatusEnum = Field(
        ...,
        alias="Verification Status",
        description="Strictly 'Verified' or 'Pattern-Derived'",
    )

    # Optional audit metadata (excluded from 6-column sheet export)
    source_url: Optional[str] = Field(default=None, description="Grounding URL")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("organization_name", "location")
    @classmethod
    def validate_non_empty_strings(cls, value: str, info: Any) -> str:
        clean = value.strip()
        if not clean or clean.lower() in PLACEHOLDER_VALUES:
            raise ValueError(f"Field '{info.field_name}' cannot be empty or a placeholder: '{value}'")
        return clean

    @field_validator("contact_person")
    @classmethod
    def validate_contact_person(cls, value: str) -> str:
        clean = value.strip()
        if clean.lower() in PLACEHOLDER_VALUES:
            raise ValueError(f"Contact Person cannot be a placeholder: '{value}'")
        if " - " not in clean:
            raise ValueError(
                f"Contact Person must be formatted as '[Full Name] - [Role]', got: '{value}'"
            )
        parts = clean.split(" - ", 1)
        name, role = parts[0].strip(), parts[1].strip()
        if not name or name.lower() in PLACEHOLDER_VALUES:
            raise ValueError(f"Contact Person name is invalid: '{name}'")
        if not role or role.lower() in PLACEHOLDER_VALUES:
            raise ValueError(f"Contact Person role is invalid: '{role}'")
        return f"{name} - {role}"

    @field_validator("contact_channel")
    @classmethod
    def validate_contact_channel(cls, value: str) -> str:
        clean = value.strip()
        if clean.lower() in PLACEHOLDER_VALUES:
            raise ValueError(f"Contact Channel cannot be a placeholder: '{value}'")

        # If it is an email address, forbid generic inboxes
        if "@" in clean:
            if GENERIC_EMAIL_PATTERN.match(clean):
                raise ValueError(
                    f"Generic central inbox prohibited in Contact Channel: '{clean}'. "
                    f"Must be a direct personal email or authentic profile link."
                )
        elif not (clean.startswith("http://") or clean.startswith("https://")):
            raise ValueError(
                f"Contact Channel must be a valid email or web profile URL, got: '{clean}'"
            )

        return clean

    @classmethod
    def sheet_headers(cls) -> list[str]:
        """Returns the canonical 6 column headers in required sequence."""
        return [
            "Organization Name",
            "Category",
            "Location",
            "Contact Person",
            "Contact Channel",
            "Verification Status",
        ]

    def to_sheet_row(self) -> list[str]:
        """Formats the record into a 6-element list matching the required sheet columns."""
        return [
            self.organization_name,
            self.category.value,
            self.location,
            self.contact_person,
            self.contact_channel,
            self.verification_status.value,
        ]

