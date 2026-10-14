"""Unit tests for Decision-Maker Extraction & Pattern Derivation Engine (Phase 4)."""

import pytest

from src.extractors.decision_maker import DecisionMakerExtractor, DecisionMakerResult
from src.extractors.pattern_engine import EmailPatternEngine
from src.models.schema import CategoryEnum, DecisionMakerCandidate, ScrapedPageSnapshot


class TestEmailPatternEngine:
    def test_extract_domain(self):
        """Test domain extraction from URLs, subdomains, and emails."""
        assert EmailPatternEngine.extract_domain("https://www.acme.com/team") == "acme.com"
        assert EmailPatternEngine.extract_domain("sarah@sub.acme.org") == "sub.acme.org"
        assert EmailPatternEngine.extract_domain("iitb.ac.in/society") == "iitb.ac.in"

    def test_filter_non_generic_emails(self):
        """Filters out generic inboxes (info@, contact@, admin@, etc.)."""
        raw_emails = [
            "info@company.com",
            "contact@company.com",
            "sarah.c@company.com",
            "admin@company.com",
            "arun.kumar@company.com",
            "banner.png",  # non-email asset
        ]
        filtered = EmailPatternEngine.filter_non_generic_emails(raw_emails)
        assert "sarah.c@company.com" in filtered
        assert "arun.kumar@company.com" in filtered
        assert "info@company.com" not in filtered
        assert "contact@company.com" not in filtered
        assert "admin@company.com" not in filtered

    def test_pattern_detection_requires_at_least_two_samples(self):
        """Pattern detection must strictly return None if fewer than 2 non-generic samples exist."""
        samples = ["sarah.connor@acme.com"]  # only 1 sample
        rule = EmailPatternEngine.detect_pattern_from_samples(samples, domain="acme.com")
        assert rule is None

        # Two samples with same pattern -> should succeed
        samples.append("john.doe@acme.com")
        rule = EmailPatternEngine.detect_pattern_from_samples(samples, domain="acme.com")
        assert rule is not None
        assert rule.pattern_format == "{first}.{last}@{domain}"
        assert rule.domain == "acme.com"

    def test_detect_patterns_various_formats(self):
        """Tests detection of underscore, first initial last, etc."""
        # Underscore pattern
        samples_underscore = ["priya_nair@acme.com", "vikram_singh@acme.com"]
        rule_underscore = EmailPatternEngine.detect_pattern_from_samples(samples_underscore, "acme.com")
        assert rule_underscore is not None
        assert rule_underscore.pattern_format == "{first}_{last}@{domain}"

        # First initial last pattern
        samples_f_last = ["pnair@acme.com", "vsingh@acme.com"]
        pairs = [("Priya Nair", "pnair@acme.com"), ("Vikram Singh", "vsingh@acme.com")]
        rule_f_last = EmailPatternEngine.detect_pattern_from_samples(
            samples_f_last, "acme.com", name_sample_pairs=pairs
        )
        assert rule_f_last is not None
        assert rule_f_last.pattern_format == "{f}{last}@{domain}"

    def test_synthesize_email(self):
        """Tests synthesizing candidate email from discovered pattern rule."""
        samples = ["alice.smith@acme.com", "bob.jones@acme.com"]
        rule = EmailPatternEngine.detect_pattern_from_samples(samples, "acme.com")
        assert rule is not None

        synthesized = EmailPatternEngine.synthesize_email("Arun Kumar", "acme.com", rule)
        assert synthesized == "arun.kumar@acme.com"

        # Honorific stripping
        synthesized_dr = EmailPatternEngine.synthesize_email("Dr. Rajesh Sharma", "acme.com", rule)
        assert synthesized_dr == "rajesh.sharma@acme.com"


class TestDecisionMakerExtractor:
    def test_extract_sponsor_decision_maker_name_role(self):
        """Extracts VP Marketing persona from text using Name, Role pattern."""
        markdown = """
        # About Acme Technologies
        We are building next-generation developer platforms.
        
        Our Leadership:
        Sarah Connor, VP Marketing
        Contact our brand team for event partnerships and sponsorships.
        """
        page = ScrapedPageSnapshot(
            url="https://acme.com/team",
            markdown_content=markdown,
            discovered_emails=["sarah.connor@acme.com"],
            discovered_social_links=["https://www.linkedin.com/in/sarah-connor"],
        )

        candidate = DecisionMakerExtractor.extract_decision_maker(
            org_name="Acme Technologies",
            category=CategoryEnum.SPONSOR,
            crawled_pages=[page],
            base_url="https://acme.com",
        )

        assert candidate is not None
        assert isinstance(candidate, DecisionMakerCandidate)
        assert candidate.name == "Sarah Connor"
        assert candidate.role == "VP Marketing"
        assert candidate.email_candidate == "sarah.connor@acme.com"
        assert candidate.profile_url_candidate == "https://www.linkedin.com/in/sarah-connor"

    def test_extract_delegation_decision_maker(self):
        """Extracts Society President persona from Role: Name pattern."""
        markdown = """
        # Robotics Society IIT Bombay
        Welcome to the official portal of the student robotics club.
        
        Executive Council 2025:
        President: Devika Sen
        Vice President: Rohan Gupta
        """
        page = ScrapedPageSnapshot(
            url="https://robotics-iitb.org/council",
            markdown_content=markdown,
            discovered_social_links=["https://www.instagram.com/robotics_iitb"],
        )

        candidate = DecisionMakerExtractor.extract_decision_maker(
            org_name="Robotics Society IIT Bombay",
            category=CategoryEnum.COLLEGE_DELEGATION,
            crawled_pages=[page],
            location="Mumbai",
            base_url="https://robotics-iitb.org",
        )

        assert candidate is not None
        assert candidate.name == "Devika Sen"
        assert candidate.role == "President"
        assert candidate.location == "Mumbai"
        assert candidate.profile_url_candidate == "https://www.instagram.com/robotics_iitb"

    def test_generic_email_nullified(self):
        """If only generic inboxes (info@, contact@) exist, email_candidate must be None."""
        markdown = """
        Acme Corp
        Sarah Connor, Head of Marketing
        For inquiries: contact@acme.com or info@acme.com
        """
        page = ScrapedPageSnapshot(
            url="https://acme.com",
            markdown_content=markdown,
            discovered_emails=["info@acme.com", "contact@acme.com"],
            discovered_social_links=["https://www.linkedin.com/in/sarah-connor-mkt"],
        )

        candidate = DecisionMakerExtractor.extract_decision_maker(
            org_name="Acme Corp",
            category=CategoryEnum.SPONSOR,
            crawled_pages=[page],
            base_url="https://acme.com",
        )

        assert candidate is not None
        assert candidate.name == "Sarah Connor"
        # Generic emails must not be assigned to candidate email
        assert candidate.email_candidate is None
        assert candidate.profile_url_candidate == "https://www.linkedin.com/in/sarah-connor-mkt"

    def test_personal_social_profile_filtering(self):
        """Personal profile links are preserved while company profiles are excluded."""
        urls = [
            "https://www.linkedin.com/company/acme-corp",
            "https://www.linkedin.com/in/sarah-connor-1234",
            "https://www.instagram.com/sarahc_marketing",
            "https://www.instagram.com/explore",
            "https://twitter.com/sarahconnor_mkt",
        ]
        profiles = DecisionMakerExtractor.extract_personal_social_profiles(urls)
        assert profiles.get("linkedin") == "https://www.linkedin.com/in/sarah-connor-1234"
        assert profiles.get("instagram") == "https://www.instagram.com/sarahc_marketing"
        assert profiles.get("twitter") == "https://x.com/sarahconnor_mkt"

    def test_pattern_derivation_integration(self):
        """When individual has no direct email but domain has >= 2 sample emails, derives email."""
        markdown = """
        Acme Global Solutions
        Executive Leadership:
        Sarah Connor, Chief Marketing Officer
        """
        # Two other employee emails on acme.com matching first.last
        page = ScrapedPageSnapshot(
            url="https://acme.com/team",
            markdown_content=markdown,
            discovered_emails=["priya.nair@acme.com", "vikram.singh@acme.com"],
            discovered_social_links=["https://www.linkedin.com/in/sarah-connor"],
        )

        candidate = DecisionMakerExtractor.extract_decision_maker(
            org_name="Acme Global Solutions",
            category=CategoryEnum.SPONSOR,
            crawled_pages=[page],
            base_url="https://acme.com",
        )

        assert candidate is not None
        assert candidate.name == "Sarah Connor"
        assert candidate.email_candidate == "sarah.connor@acme.com"
        assert "Pattern-Derived" in (candidate.raw_snippet or "")

