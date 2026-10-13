"""Unit tests for Core Schemas, 6-Field Output Table, and LangGraph State."""

import pytest
from pydantic import ValidationError

from src.models.schema import (
    CategoryEnum,
    DecisionMakerCandidate,
    DecisionMakerRole,
    FinalLeadRecord,
    TargetOrganization,
    VerificationStatusEnum,
)
from src.models.state import create_initial_state


class TestFinalLeadRecord:
    def test_valid_sponsor_record_creation(self):
        """Test valid sponsor creation and exact 6-element sheet row export."""
        record = FinalLeadRecord(
            **{
                "Organization Name": "Red Bull India",
                "Category": "Sponsor",
                "Location": "Mumbai",
                "Contact Person": "Arun Verma - Head of Brand Marketing",
                "Contact Channel": "arun.verma@redbull.com",
                "Verification Status": "Verified",
            }
        )
        assert record.organization_name == "Red Bull India"
        assert record.category == CategoryEnum.SPONSOR
        assert record.location == "Mumbai"
        assert record.contact_person == "Arun Verma - Head of Brand Marketing"
        assert record.contact_channel == "arun.verma@redbull.com"
        assert record.verification_status == VerificationStatusEnum.VERIFIED

        # Verify exact 6 headers
        headers = FinalLeadRecord.sheet_headers()
        assert headers == [
            "Organization Name",
            "Category",
            "Location",
            "Contact Person",
            "Contact Channel",
            "Verification Status",
        ]

        # Verify exact 6 row values
        row = record.to_sheet_row()
        assert row == [
            "Red Bull India",
            "Sponsor",
            "Mumbai",
            "Arun Verma - Head of Brand Marketing",
            "arun.verma@redbull.com",
            "Verified",
        ]
        assert len(row) == 6

    def test_valid_college_delegation_record_with_social_profile(self):
        """Test valid college delegation lead with LinkedIn/Instagram profile link."""
        record = FinalLeadRecord(
            **{
                "Organization Name": "Robotics Club IIT Bombay",
                "Category": "College Delegation",
                "Location": "Mumbai",
                "Contact Person": "Devika Sen - Society President",
                "Contact Channel": "https://linkedin.com/in/devika-sen",
                "Verification Status": "Pattern-Derived",
            }
        )
        assert record.category == CategoryEnum.COLLEGE_DELEGATION
        assert record.verification_status == VerificationStatusEnum.PATTERN_DERIVED
        assert record.contact_channel == "https://linkedin.com/in/devika-sen"

    @pytest.mark.parametrize(
        "generic_email",
        [
            "info@company.com",
            "contact@company.com",
            "support@acme.org",
            "hello@startup.io",
            "admin@college.edu",
            "sales@brand.in",
            "office@society.org",
            "marketing@corp.com",
            "team@club.ac.in",
        ],
    )
    def test_generic_inbox_rejection(self, generic_email):
        """Generic inboxes must be rejected with ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            FinalLeadRecord(
                **{
                    "Organization Name": "Acme Corp",
                    "Category": "Sponsor",
                    "Location": "Delhi",
                    "Contact Person": "Sarah Connor - VP Marketing",
                    "Contact Channel": generic_email,
                    "Verification Status": "Verified",
                }
            )
        assert "Generic central inbox prohibited" in str(exc_info.value)

    @pytest.mark.parametrize(
        "invalid_contact_person",
        [
            "Sarah Connor",  # Missing role
            "VP Marketing",  # Missing name
            "N/A",  # Placeholder
            "Unknown - Marketing",  # Placeholder name
            "Sarah Connor - Unknown",  # Placeholder role
            " - ",
        ],
    )
    def test_invalid_contact_person_formatting(self, invalid_contact_person):
        """Contact person must strictly follow '[Name] - [Role]' with no placeholders."""
        with pytest.raises(ValidationError):
            FinalLeadRecord(
                **{
                    "Organization Name": "Acme Corp",
                    "Category": "Sponsor",
                    "Location": "Delhi",
                    "Contact Person": invalid_contact_person,
                    "Contact Channel": "sarah.connor@acme.com",
                    "Verification Status": "Verified",
                }
            )

    @pytest.mark.parametrize(
        "placeholder",
        ["N/A", "Unknown", "None", "null", "TBD", "pending"],
    )
    def test_placeholder_rejection(self, placeholder):
        """No placeholder strings allowed in critical fields."""
        with pytest.raises(ValidationError):
            FinalLeadRecord(
                **{
                    "Organization Name": placeholder,
                    "Category": "Sponsor",
                    "Location": "Delhi",
                    "Contact Person": "Sarah Connor - VP Marketing",
                    "Contact Channel": "sarah@acme.com",
                    "Verification Status": "Verified",
                }
            )


class TestIntermediateModels:
    def test_target_organization(self):
        org = TargetOrganization(
            name="Zomato",
            category=CategoryEnum.SPONSOR,
            city="Gurugram",
            website="https://zomato.com",
            domain="zomato.com",
        )
        assert org.name == "Zomato"
        assert org.domain == "zomato.com"

    def test_decision_maker_candidate(self):
        candidate = DecisionMakerCandidate(
            organization_name="Fintech Corp",
            category=CategoryEnum.SPONSOR,
            location="Bengaluru",
            name="Karan Mehta",
            role="CSR Head",
            email_candidate="karan.m@fintechcorp.com",
            source_url="https://fintechcorp.com/team",
        )
        assert candidate.name == "Karan Mehta"
        assert candidate.role == "CSR Head"


class TestAgentState:
    def test_create_initial_state(self):
        state = create_initial_state(
            search_prompt="Find AI sponsors in Bangalore",
            brochure_path="/tmp/brochure.pdf",
            category_focus="Sponsor",
            max_target_count=10,
        )
        assert state["search_prompt"] == "Find AI sponsors in Bangalore"
        assert state["brochure_path"] == "/tmp/brochure.pdf"
        assert state["category_focus"] == "Sponsor"
        assert state["max_target_count"] == 10
        assert state["active_org_index"] == 0
        assert state["is_complete"] is False
        assert state["verified_leads"] == []
        assert state["dead_urls"] == []
        assert state["errors"] == []

