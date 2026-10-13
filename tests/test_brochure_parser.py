"""Unit tests for Brochure and Prompt Parsing Subsystem (Phase 2)."""

from pathlib import Path
import pytest
import pymupdf

from src.models.schema import CategoryEnum
from src.parsers.brochure_parser import BrochureContext, BrochureParser
from src.parsers.prompt_expander import ParsedPromptContext, PromptExpander


@pytest.fixture
def sample_pdf_path(tmp_path: Path) -> Path:
    """Creates a realistic synthetic multi-page conference brochure PDF."""
    pdf_file = tmp_path / "synthetic_brochure.pdf"
    doc = pymupdf.open()

    # Page 1: Cover & Theme
    page1 = doc.new_page()
    page1.insert_text(
        (50, 80),
        "TECHNOVATE 2025: National AI & Robotics Hackathon\n"
        "Location: Bengaluru, India\n"
        "Join 1500+ student developers and 50+ collegiate delegations.\n",
        fontsize=16,
    )

    # Page 2: Sponsorship Tiers & Past Sponsors
    page2 = doc.new_page()
    page2.insert_text(
        (50, 80),
        "SPONSORSHIP OPPORTUNITIES & TIERS\n"
        "Title Sponsor: INR 5,00,000\n"
        "Powered By Sponsor: INR 3,00,000\n"
        "Associate Sponsor: INR 1,50,000\n\n"
        "Past Sponsors & Partners:\n"
        "Google Cloud\n"
        "GitHub\n"
        "Red Bull India\n"
        "Swiggy\n\n"
        "Collegiate Chapters:\n"
        "Robotics Club IIT Madras\n"
        "Coding Club BITS Pilani\n",
        fontsize=12,
    )

    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


class TestBrochureParser:
    def test_parse_synthetic_brochure(self, sample_pdf_path: Path):
        """Test parsing of multi-page PDF brochure."""
        parser = BrochureParser(max_pages=5)
        context = parser.parse(sample_pdf_path)

        assert isinstance(context, BrochureContext)
        assert "TECHNOVATE" in context.event_name or "National AI" in context.event_theme_summary
        assert context.event_location in ["Bengaluru", "National"]
        assert len(context.target_categories) >= 1
        assert len(context.seed_search_queries) > 0
        assert any("Google Cloud" in s or "Red Bull" in s or "GitHub" in s for s in context.past_sponsors_found)

    def test_parse_real_problem_statement_pdf(self):
        """Test parsing against the repository's real problem-statement.pdf."""
        pdf_path = Path("problem-statement.pdf")
        if not pdf_path.exists():
            pytest.skip("problem-statement.pdf not found in root")

        parser = BrochureParser(max_pages=5)
        context = parser.parse(pdf_path)

        assert isinstance(context, BrochureContext)
        assert len(context.seed_search_queries) > 0
        assert context.event_name is not None

    def test_non_existent_file_raises_error(self):
        """Non-existent file must raise FileNotFoundError."""
        parser = BrochureParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/tmp/non_existent_brochure_12345.pdf")

    def test_corrupt_bytes_raises_error(self):
        """Corrupt or invalid PDF bytes must raise ValueError."""
        parser = BrochureParser()
        with pytest.raises(ValueError):
            parser.parse(b"this is not a valid pdf document")


class TestPromptExpander:
    def test_expand_sponsor_specific_prompt(self):
        """Test deconstructing a sponsor-heavy prompt."""
        expander = PromptExpander()
        prompt = "Find AI startup sponsors and cloud brands in Bangalore for our hackathon"
        res = expander.expand(prompt)

        assert isinstance(res, ParsedPromptContext)
        assert CategoryEnum.SPONSOR in res.target_categories
        assert "Bengaluru" in res.locations or "Bangalore" in res.locations
        assert any("Artificial Intelligence" in ind or "Cloud" in ind for ind in res.target_industries)
        assert len(res.generated_search_queries) > 0

    def test_expand_college_delegation_prompt(self):
        """Test deconstructing a delegation-focused prompt."""
        expander = PromptExpander()
        prompt = "Find top robotics college societies and coding clubs in Delhi"
        res = expander.expand(prompt)

        assert isinstance(res, ParsedPromptContext)
        assert CategoryEnum.COLLEGE_DELEGATION in res.target_categories
        assert "Delhi" in res.locations
        assert any("Robotics" in soc for soc in res.target_societies)
        assert any("Coding" in soc for soc in res.target_societies)

    def test_expand_combined_prompt(self):
        """Test deconstructing a prompt requesting both sponsors and delegations."""
        expander = PromptExpander()
        prompt = "Find FinTech sponsors and college delegations in Mumbai for business conclave"
        res = expander.expand(prompt)

        assert isinstance(res, ParsedPromptContext)
        assert CategoryEnum.SPONSOR in res.target_categories
        assert CategoryEnum.COLLEGE_DELEGATION in res.target_categories
        assert "Mumbai" in res.locations

    def test_empty_prompt_raises_error(self):
        """Empty prompt must raise ValueError."""
        expander = PromptExpander()
        with pytest.raises(ValueError):
            expander.expand("   ")

