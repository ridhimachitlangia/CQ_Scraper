"""Email Format Pattern Derivation Engine.

Analyzes observed corporate and collegiate email samples to identify domain-level
naming patterns (e.g. {first}.{last}@domain.com) and synthesizes candidate emails
for identified decision-makers. Strictly enforces that at least 2 non-generic
sample emails must corroborate a pattern before derivation is allowed.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse
from loguru import logger

from src.models.schema import GENERIC_EMAIL_PATTERN, EmailPatternRule


# Common naming formats
PATTERN_FIRST_DOT_LAST = "{first}.{last}@{domain}"
PATTERN_FIRST_LAST = "{first}{last}@{domain}"
PATTERN_FIRST_UNDERSCORE_LAST = "{first}_{last}@{domain}"
PATTERN_F_LAST = "{f}{last}@{domain}"
PATTERN_FIRST = "{first}@{domain}"
PATTERN_LAST_DOT_FIRST = "{last}.{first}@{domain}"


class EmailPatternEngine:
    """Discovers domain email naming conventions and synthesizes candidate emails."""

    @classmethod
    def clean_name_tokens(cls, full_name: str) -> tuple[str, str, str]:
        """Splits full name into (first, last, first_initial) cleaned lowercase strings."""
        # Strip titles/honorifics
        clean = re.sub(r"^(dr\.|mr\.|ms\.|mrs\.|prof\.)\s+", "", full_name.strip(), flags=re.I)
        # Strip trailing degrees/roles
        clean = re.sub(r"[,|\-].*$", "", clean).strip()
        tokens = [re.sub(r"[^a-zA-Z]", "", t.lower()) for t in clean.split() if t.strip()]
        tokens = [t for t in tokens if t]

        if not tokens:
            return "", "", ""
        if len(tokens) == 1:
            first = tokens[0]
            return first, "", first[0]
        
        first = tokens[0]
        last = tokens[-1]
        return first, last, first[0]

    @classmethod
    def extract_domain(cls, email_or_url: str) -> str:
        """Extracts clean lowercase domain from email or URL."""
        target = email_or_url.strip().lower()
        if "@" in target:
            return target.split("@")[-1].strip()
        if "://" in target:
            parsed = urlparse(target)
            host = parsed.netloc or parsed.path
        else:
            host = target.split("/")[0]
        return re.sub(r"^www\.", "", host).strip()

    @classmethod
    def filter_non_generic_emails(cls, emails: list[str]) -> list[str]:
        """Excludes generic inboxes (info@, contact@, support@, etc.) from samples."""
        valid: list[str] = []
        for email in emails:
            clean = email.strip().lower()
            if not clean or "@" not in clean:
                continue
            if GENERIC_EMAIL_PATTERN.match(clean):
                continue
            # Filter non-personal file extensions mistakenly parsed
            if any(clean.endswith(ext) for ext in [".png", ".jpg", ".webp", ".js", ".css"]):
                continue
            if clean not in valid:
                valid.append(clean)
        return valid

    @classmethod
    def detect_pattern_from_samples(
        cls,
        sample_emails: list[str],
        domain: Optional[str] = None,
        name_sample_pairs: Optional[list[tuple[str, str]]] = None,
    ) -> Optional[EmailPatternRule]:
        """Infers domain email syntax pattern.
        
        Requires AT LEAST 2 non-generic employee email samples to satisfy the
        Zero-Hallucination mandate.
        """
        valid_samples = cls.filter_non_generic_emails(sample_emails)
        if len(valid_samples) < 2:
            logger.debug(
                f"Insufficient non-generic email samples ({len(valid_samples)} found, 2 required) "
                f"to infer pattern for domain: {domain}"
            )
            return None

        detected_domain = domain or cls.extract_domain(valid_samples[0])

        # 1. If we have explicit (name, email) pairs, match with high statistical confidence
        if name_sample_pairs:
            valid_pairs = [
                (n, e) for n, e in name_sample_pairs
                if e.strip().lower() in valid_samples
            ]
            if len(valid_pairs) >= 2:
                matched_patterns: list[str] = []
                for name, email in valid_pairs:
                    local_part = email.split("@")[0].lower()
                    first, last, f = cls.clean_name_tokens(name)
                    if not first or not last:
                        continue

                    if local_part == f"{first}.{last}":
                        matched_patterns.append(PATTERN_FIRST_DOT_LAST)
                    elif local_part == f"{first}_{last}":
                        matched_patterns.append(PATTERN_FIRST_UNDERSCORE_LAST)
                    elif local_part == f"{f}{last}":
                        matched_patterns.append(PATTERN_F_LAST)
                    elif local_part == f"{first}{last}":
                        matched_patterns.append(PATTERN_FIRST_LAST)
                    elif local_part == f"{last}.{first}":
                        matched_patterns.append(PATTERN_LAST_DOT_FIRST)
                    elif local_part == first:
                        matched_patterns.append(PATTERN_FIRST)

                if matched_patterns:
                    # Pick most frequent pattern
                    best_pattern = max(set(matched_patterns), key=matched_patterns.count)
                    return EmailPatternRule(
                        domain=detected_domain,
                        pattern_format=best_pattern,
                        confidence=0.95,
                        sample_emails=valid_samples[:5],
                    )

        # 2. Heuristic inference from email local parts across domain samples
        pattern_votes: list[str] = []
        for email in valid_samples:
            local_part = email.split("@")[0].lower()
            if "." in local_part and len(local_part.split(".")) == 2:
                p1, p2 = local_part.split(".")
                if len(p1) > 1 and len(p2) > 1:
                    pattern_votes.append(PATTERN_FIRST_DOT_LAST)
                elif len(p1) == 1 and len(p2) > 1:
                    pattern_votes.append(PATTERN_F_LAST)
            elif "_" in local_part and len(local_part.split("_")) == 2:
                pattern_votes.append(PATTERN_FIRST_UNDERSCORE_LAST)
            elif len(local_part) >= 4 and not any(c in local_part for c in ".-_"):
                pattern_votes.append(PATTERN_FIRST_LAST)

        if not pattern_votes:
            return None

        # Count pattern occurrences
        best_pattern = max(set(pattern_votes), key=pattern_votes.count)
        vote_count = pattern_votes.count(best_pattern)

        # Enforce at least 2 samples matching the same pattern
        if vote_count >= 2:
            return EmailPatternRule(
                domain=detected_domain,
                pattern_format=best_pattern,
                confidence=min(0.9, 0.7 + (vote_count * 0.05)),
                sample_emails=valid_samples[:5],
            )

        return None

    @classmethod
    def synthesize_email(
        cls,
        full_name: str,
        domain: str,
        pattern_rule: EmailPatternRule,
    ) -> Optional[str]:
        """Synthesizes candidate email using discovered pattern and person's name."""
        first, last, f = cls.clean_name_tokens(full_name)
        if not first:
            return None

        # Clean target domain
        clean_domain = cls.extract_domain(domain)
        if not clean_domain:
            return None

        fmt = pattern_rule.pattern_format
        if "{last}" in fmt and not last:
            # Cannot derive without last name if template requires it
            return None

        derived_local = fmt.replace("{domain}", clean_domain)
        derived_local = derived_local.replace("{first}", first)
        derived_local = derived_local.replace("{last}", last)
        derived_local = derived_local.replace("{f}", f)

        # Ensure result ends with @domain
        if not derived_local.endswith(f"@{clean_domain}"):
            derived_email = f"{derived_local}@{clean_domain}"
        else:
            derived_email = derived_local

        # Sanity check: ensure valid email structure
        if re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", derived_email):
            logger.info(
                f"Synthesized pattern-derived email for '{full_name}': {derived_email} "
                f"(Pattern: {pattern_rule.pattern_format}, Domain: {clean_domain})"
            )
            return derived_email

        return None

