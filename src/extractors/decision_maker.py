"""Decision Maker and Role Extraction Subsystem.

Extracts specific human decision-makers (Full Name, Role, Direct Email, and Profile Link)
from crawled page content, search dorks, and snippets. Strictly eliminates generic central inboxes
and enforces the leadership role hierarchy for Sponsors and College Delegations.
"""

from __future__ import annotations

import re
from typing import Optional
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.settings import settings
from src.extractors.pattern_engine import EmailPatternEngine
from src.models.schema import (
    GENERIC_EMAIL_PATTERN,
    PLACEHOLDER_VALUES,
    CategoryEnum,
    DecisionMakerCandidate,
    ScrapedPageSnapshot,
)


# Personal social profile regexes
LINKEDIN_PERSONAL_PATTERN = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([a-zA-Z0-9_\-\.]+)/?",
    re.IGNORECASE,
)
INSTAGRAM_PROFILE_PATTERN = re.compile(
    r"https?://(?:www\.)?instagram\.com/([a-zA-Z0-9_\-\.]+)/?",
    re.IGNORECASE,
)
TWITTER_PROFILE_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:twitter|x)\.com/([a-zA-Z0-9_\-\.]+)/?",
    re.IGNORECASE,
)

# Generic titles or non-individual names that must be rejected as personal names
DISALLOWED_PERSON_NAMES = {
    "team", "marketing team", "admin", "administrator", "contact us", "about us",
    "student council", "executive board", "board of directors", "office bearers",
    "faculty coordinator", "department", "society", "society president", "president",
    "secretariat", "organizing committee", "core team", "support team", "alumni",
}


class DecisionMakerResult(BaseModel):
    """Structured extraction result of an individual decision-maker."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., description="Full personal name of the individual")
    role: str = Field(..., description="Specific official title or leadership position")
    direct_email: Optional[str] = Field(default=None, description="Direct personal email if found")
    profile_link: Optional[str] = Field(default=None, description="Personal LinkedIn, Instagram, or faculty profile")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    source_url: str = Field(..., description="URL where decision-maker was grounded")
    rationale: str = Field(default="", description="Extraction context and source justification")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        clean = value.strip()
        if clean.lower() in PLACEHOLDER_VALUES or clean.lower() in DISALLOWED_PERSON_NAMES:
            raise ValueError(f"Extracted name is generic or placeholder: '{value}'")
        # Must contain at least two characters
        if len(clean) < 2:
            raise ValueError(f"Name too short: '{value}'")
        return clean

    @field_validator("direct_email")
    @classmethod
    def validate_direct_email(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        clean = value.strip().lower()
        if GENERIC_EMAIL_PATTERN.match(clean) or clean in PLACEHOLDER_VALUES:
            # Nullify generic email
            return None
        return clean

    def to_candidate(
        self,
        org_name: str,
        category: CategoryEnum,
        location: str,
        raw_snippet: Optional[str] = None,
    ) -> DecisionMakerCandidate:
        """Converts result into a domain DecisionMakerCandidate."""
        return DecisionMakerCandidate(
            organization_name=org_name,
            category=category,
            location=location,
            name=self.name,
            role=self.role,
            email_candidate=self.direct_email,
            profile_url_candidate=self.profile_link,
            source_url=self.source_url,
            raw_snippet=raw_snippet or self.rationale,
            confidence_score=self.confidence_score,
        )


class DecisionMakerExtractor:
    """Extracts human decision-makers and personal contacts from web pages and snippets."""

    SPONSOR_ROLE_KEYWORDS = [
        "Chief Marketing Officer", "CMO", "VP Marketing", "Vice President Marketing",
        "Head of Marketing", "Director of Marketing", "Brand Partnerships",
        "Head of Brand", "CSR Head", "Head of CSR", "Sponsorship Director",
        "Managing Director", "Founder", "Co-Founder", "Chief Executive Officer",
        "CEO", "Marketing Lead", "Partnerships Lead",
    ]

    DELEGATION_ROLE_KEYWORDS = [
        "President", "Society President", "Club President", "Convenor",
        "Overall Convenor", "General Secretary", "Secretary General",
        "Vice President", "Co-Convenor", "Team Captain", "Lead Organizer",
        "Faculty Advisor", "Faculty In-Charge", "Treasurer",
    ]

    @classmethod
    def extract_personal_social_profiles(cls, urls: list[str]) -> dict[str, str]:
        """Extracts and categorizes verified personal profile URLs (LinkedIn, Instagram, Twitter/X)."""
        profiles: dict[str, str] = {}
        for raw in urls:
            clean = raw.strip()
            # LinkedIn personal profile (exclude /company/, /school/, /jobs/)
            li_match = LINKEDIN_PERSONAL_PATTERN.search(clean)
            if li_match:
                slug = li_match.group(1).lower()
                if slug not in ["company", "school", "feed", "posts", "pulse"]:
                    profiles["linkedin"] = f"https://www.linkedin.com/in/{slug}"
                    continue

            # Instagram personal/society handle
            ig_match = INSTAGRAM_PROFILE_PATTERN.search(clean)
            if ig_match:
                slug = ig_match.group(1).lower()
                if slug not in ["p", "reel", "stories", "explore", "about", "legal"]:
                    profiles["instagram"] = f"https://www.instagram.com/{slug}"
                    continue

            # Twitter / X
            tw_match = TWITTER_PROFILE_PATTERN.search(clean)
            if tw_match:
                slug = tw_match.group(1).lower()
                if slug not in ["home", "explore", "search", "intent", "privacy"]:
                    profiles["twitter"] = f"https://x.com/{slug}"
                    continue

        return profiles

    @classmethod
    def extract_decision_maker(
        cls,
        org_name: str,
        category: CategoryEnum,
        crawled_pages: list[ScrapedPageSnapshot],
        search_snippets: Optional[list[str]] = None,
        location: str = "National",
        base_url: str = "",
    ) -> Optional[DecisionMakerCandidate]:
        """Main extraction pipeline: analyzes pages & snippets, filters generics, applies LLM/heuristics."""
        search_snippets = search_snippets or []
        combined_text_chunks: list[str] = []
        all_discovered_emails: list[str] = []
        all_discovered_socials: list[str] = []
        primary_source_url = base_url or (crawled_pages[0].url if crawled_pages else "")

        for p in crawled_pages:
            if p.is_dead:
                continue
            if p.markdown_content.strip():
                combined_text_chunks.append(f"Source: {p.url}\n{p.markdown_content[:4000]}")
            all_discovered_emails.extend(p.discovered_emails)
            all_discovered_socials.extend(p.discovered_social_links)

        for snip in search_snippets:
            if snip.strip():
                combined_text_chunks.append(f"Snippet: {snip}")

        aggregated_text = "\n\n".join(combined_text_chunks)
        personal_profiles = cls.extract_personal_social_profiles(all_discovered_socials)

        # 1. Attempt LLM-based structured extraction if OpenAI API key is available
        if settings.openai_api_key and not settings.openai_api_key.startswith("your_"):
            try:
                res = cls._extract_with_llm(
                    org_name=org_name,
                    category=category,
                    text=aggregated_text,
                    discovered_emails=all_discovered_emails,
                    social_profiles=personal_profiles,
                    source_url=primary_source_url,
                )
                if res and res.name:
                    candidate = res.to_candidate(
                        org_name=org_name,
                        category=category,
                        location=location,
                    )
                    return cls._post_process_candidate(
                        candidate=candidate,
                        all_discovered_emails=all_discovered_emails,
                        base_url=base_url or primary_source_url,
                    )
            except Exception as e:
                logger.warning(f"LLM decision-maker extraction failed: {e}. Falling back to heuristic parsing.")

        # 2. Heuristic extraction fallback
        res = cls._extract_with_heuristics(
            org_name=org_name,
            category=category,
            text=aggregated_text,
            discovered_emails=all_discovered_emails,
            social_profiles=personal_profiles,
            source_url=primary_source_url,
        )

        if res:
            candidate = res.to_candidate(
                org_name=org_name,
                category=category,
                location=location,
            )
            return cls._post_process_candidate(
                candidate=candidate,
                all_discovered_emails=all_discovered_emails,
                base_url=base_url or primary_source_url,
            )

        return None

    @classmethod
    def _extract_with_llm(
        cls,
        org_name: str,
        category: CategoryEnum,
        text: str,
        discovered_emails: list[str],
        social_profiles: dict[str, str],
        source_url: str,
    ) -> Optional[DecisionMakerResult]:
        """Executes LLM extraction with strict Zero-Hallucination prompt constraints."""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.0,
            openai_api_key=settings.openai_api_key,
        )
        structured_llm = llm.with_structured_output(DecisionMakerResult)

        role_target = (
            "VP Marketing, CMO, Head of Brand Partnerships, or CSR Head"
            if category == CategoryEnum.SPONSOR
            else "Society President, Convenor, or General Secretary"
        )

        system_prompt = (
            f"You are a strict data auditor extracting real executive decision-makers for '{org_name}'. "
            f"Category: {category.value}. Target Role: {role_target}.\n"
            "STRICT RULES:\n"
            "1. NEVER hallucinate or invent a name. The name and role MUST be cited verbatim in the text.\n"
            "2. Disallow generic departments like 'Marketing Team', 'Office Bearers', or 'Student Council' as a person's name.\n"
            "3. Disallow central inboxes (info@, contact@, sales@, etc.) in direct_email. If only a generic email exists, leave direct_email null.\n"
            "4. Prefer the person's direct personal profile (LinkedIn, Instagram) if direct email is not stated."
        )

        user_content = (
            f"Organization: {org_name}\n"
            f"Discovered Non-Generic Emails: {EmailPatternEngine.filter_non_generic_emails(discovered_emails)}\n"
            f"Discovered Social Profiles: {social_profiles}\n\n"
            f"Source Text:\n{text[:7000]}"
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        result = structured_llm.invoke(messages)
        if isinstance(result, DecisionMakerResult):
            if not result.source_url:
                result.source_url = source_url
            return result
        return None

    @classmethod
    def _extract_with_heuristics(
        cls,
        org_name: str,
        category: CategoryEnum,
        text: str,
        discovered_emails: list[str],
        social_profiles: dict[str, str],
        source_url: str,
    ) -> Optional[DecisionMakerResult]:
        """Deterministic heuristic extraction using regex role matching and contextual window analysis."""
        role_keywords = (
            cls.SPONSOR_ROLE_KEYWORDS
            if category == CategoryEnum.SPONSOR
            else cls.DELEGATION_ROLE_KEYWORDS
        )

        lines = [line.strip() for line in text.split("\n") if line.strip()]
        best_name: Optional[str] = None
        best_role: Optional[str] = None
        best_email: Optional[str] = None
        best_profile: Optional[str] = None
        rationale: str = ""

        # Pattern 1: Look for "Role: Name" or "Role - Name"
        # e.g. "President: Devika Sen", "VP Marketing - Sarah Connor"
        for role_kw in role_keywords:
            role_regex = re.compile(
                rf"\b{re.escape(role_kw)}\b\s*[:|\-|–]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})",
                re.IGNORECASE,
            )
            for line in lines:
                match = role_regex.search(line)
                if match:
                    cand_name = match.group(1).strip()
                    if cls._is_valid_person_name(cand_name):
                        best_name = cand_name
                        best_role = role_kw
                        rationale = f"Matched '{role_kw}: {cand_name}'"
                        break
            if best_name:
                break

        # Pattern 2: Look for "Name, Role" or "Name (Role)"
        # e.g. "Sarah Connor, VP Marketing", "Devika Sen (President)"
        if not best_name:
            for role_kw in role_keywords:
                inv_regex = re.compile(
                    rf"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){{1,3}})\s*[,|–|\-|\(]\s*\b{re.escape(role_kw)}\b",
                    re.IGNORECASE,
                )
                for line in lines:
                    match = inv_regex.search(line)
                    if match:
                        cand_name = match.group(1).strip()
                        if cls._is_valid_person_name(cand_name):
                            best_name = cand_name
                            best_role = role_kw
                            rationale = f"Matched '{cand_name}, {role_kw}'"
                            break
                if best_name:
                    break

        # Pattern 3: Look for adjacent lines (Line 1: Name, Line 2: Role)
        if not best_name:
            for i in range(len(lines) - 1):
                l1 = lines[i].strip()
                l2 = lines[i + 1].strip()
                for role_kw in role_keywords:
                    if re.search(rf"^\b{re.escape(role_kw)}\b", l2, re.IGNORECASE):
                        if cls._is_valid_person_name(l1):
                            best_name = l1
                            best_role = role_kw
                            rationale = f"Matched adjacent lines '{l1}' followed by '{role_kw}'"
                            break
                if best_name:
                    break

        if not best_name or not best_role:
            return None

        # Check for direct personal email matching decision maker's name
        first_token = best_name.split()[0].lower()
        non_generic_emails = EmailPatternEngine.filter_non_generic_emails(discovered_emails)
        for email in non_generic_emails:
            if first_token in email.lower():
                best_email = email
                break

        # Check for personal profile link
        if "linkedin" in social_profiles:
            best_profile = social_profiles["linkedin"]
        elif "instagram" in social_profiles:
            best_profile = social_profiles["instagram"]
        elif "twitter" in social_profiles:
            best_profile = social_profiles["twitter"]

        return DecisionMakerResult(
            name=best_name,
            role=best_role,
            direct_email=best_email,
            profile_link=best_profile,
            confidence_score=0.90,
            source_url=source_url,
            rationale=rationale,
        )

    @classmethod
    def _post_process_candidate(
        cls,
        candidate: DecisionMakerCandidate,
        all_discovered_emails: list[str],
        base_url: str,
    ) -> DecisionMakerCandidate:
        """Applies email pattern derivation if email is missing but name and samples exist."""
        # If candidate already has a direct non-generic email, return
        if candidate.email_candidate and not GENERIC_EMAIL_PATTERN.match(candidate.email_candidate):
            return candidate

        # Clean any accidental generic email
        if candidate.email_candidate and GENERIC_EMAIL_PATTERN.match(candidate.email_candidate):
            candidate.email_candidate = None

        # Attempt pattern derivation if we have candidate name and domain samples
        domain = EmailPatternEngine.extract_domain(base_url)
        if domain and candidate.name:
            pattern_rule = EmailPatternEngine.detect_pattern_from_samples(
                sample_emails=all_discovered_emails,
                domain=domain,
            )
            if pattern_rule:
                derived = EmailPatternEngine.synthesize_email(
                    full_name=candidate.name,
                    domain=domain,
                    pattern_rule=pattern_rule,
                )
                if derived:
                    candidate.email_candidate = derived
                    candidate.raw_snippet = (
                        f"{candidate.raw_snippet or ''} [Pattern-Derived via {pattern_rule.pattern_format}]"
                    ).strip()

        return candidate

    @classmethod
    def _is_valid_person_name(cls, name: str) -> bool:
        """Validates that extracted string is a natural person name."""
        clean = name.strip()
        lower = clean.lower()

        if lower in DISALLOWED_PERSON_NAMES or lower in PLACEHOLDER_VALUES:
            return False

        # Reject names containing digits or web characters
        if re.search(r"[\d@/\\_\+\*#]", clean):
            return False

        # Reject common button/nav text
        if any(nav in lower for nav in ["read more", "learn more", "click here", "sign up", "contact", "home", "menu"]):
            return False

        words = clean.split()
        # Person names should typically be 2 to 4 words (First, [Middle], Last)
        if len(words) < 2 or len(words) > 4:
            return False

        # Words should start with uppercase
        if not all(w[0].isupper() for w in words if len(w) > 0):
            return False

        return True

