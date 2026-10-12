"""Prompt Intent Expander and Target Query Generator.

Deconstructs unstructured natural language prompts into structured target sectors,
categories, geographic entities, and focused search dorks for Sponsors and College Delegations.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from src.models.schema import CategoryEnum, TargetOrganization


class ParsedPromptContext(BaseModel):
    """Structured extraction of user search prompt."""
    model_config = ConfigDict(extra="ignore")

    raw_prompt: str = Field(..., description="Original user prompt")
    event_theme: str = Field(default="", description="Inferred theme or domain of the event")
    target_categories: list[CategoryEnum] = Field(
        default_factory=lambda: [CategoryEnum.SPONSOR, CategoryEnum.COLLEGE_DELEGATION]
    )
    locations: list[str] = Field(default_factory=list, description="Target cities or regions")
    target_industries: list[str] = Field(default_factory=list, description="Target sponsor industries")
    target_societies: list[str] = Field(default_factory=list, description="Target collegiate society domains")
    seed_organizations: list[TargetOrganization] = Field(
        default_factory=list, description="Explicit companies or colleges mentioned in prompt"
    )
    generated_search_queries: list[str] = Field(
        default_factory=list, description="Targeted web search queries"
    )


class PromptExpander:
    """Deconstructs user search prompts into structured prospecting targets."""

    MAJOR_CITIES = [
        "Bangalore", "Bengaluru", "Mumbai", "Delhi", "New Delhi", "Hyderabad",
        "Chennai", "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Chandigarh",
        "Noida", "Gurugram", "Gurgaon", "Indore", "Goa", "Kochi"
    ]

    def expand(self, prompt: str) -> ParsedPromptContext:
        """Parses and expands the search prompt into structured prospecting entities."""
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise ValueError("Search prompt cannot be empty.")

        # Attempt LLM structured parsing if API key is configured
        if settings.openai_api_key and not settings.openai_api_key.startswith("your_"):
            try:
                return self._expand_with_llm(clean_prompt)
            except Exception as e:
                logger.warning(f"LLM prompt expansion failed, falling back to heuristic parsing: {e}")

        # Deterministic regex / heuristic parsing fallback
        return self._heuristic_expand(clean_prompt)

    def _expand_with_llm(self, prompt: str) -> ParsedPromptContext:
        """Invokes OpenAI with structured output to expand prompt intent."""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.0,
            openai_api_key=settings.openai_api_key,
        )
        structured_llm = llm.with_structured_output(ParsedPromptContext)

        system_prompt = (
            "You are an expert event sponsorship director and collegiate delegation coordinator. "
            "Deconstruct the user's search prompt into target categories (Sponsor, College Delegation, or both), "
            "geographic cities, industry sectors, society domains, and high-impact search queries. "
            "Search queries must target corporate marketing/CSR leads or college society presidents."
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"User Search Prompt: {prompt}"),
        ]

        result = structured_llm.invoke(messages)
        if isinstance(result, ParsedPromptContext):
            return result
        elif isinstance(result, dict):
            return ParsedPromptContext(**result)
        return self._heuristic_expand(prompt)

    def _heuristic_expand(self, prompt: str) -> ParsedPromptContext:
        """Deterministic heuristic extraction of intent, locations, and categories."""
        prompt_lower = prompt.lower()

        # 1. Detect Category Focus
        categories: list[CategoryEnum] = []
        is_sponsor = any(k in prompt_lower for k in ["sponsor", "brand", "partner", "csr", "funding", "corporate"])
        is_delegation = any(k in prompt_lower for k in ["college", "society", "club", "delegation", "student", "campus", "conclave", "mun"])

        if is_sponsor and not is_delegation:
            categories = [CategoryEnum.SPONSOR]
        elif is_delegation and not is_sponsor:
            categories = [CategoryEnum.COLLEGE_DELEGATION]
        else:
            categories = [CategoryEnum.SPONSOR, CategoryEnum.COLLEGE_DELEGATION]

        # 2. Extract Locations
        locations: list[str] = []
        for city in self.MAJOR_CITIES:
            if re.search(rf"\b{city}\b", prompt, re.IGNORECASE):
                # Normalize Bangalore / Bengaluru, Gurgaon / Gurugram
                norm_city = "Bengaluru" if city.lower() in ["bangalore", "bengaluru"] else city
                norm_city = "Gurugram" if norm_city.lower() in ["gurgaon", "gurugram"] else norm_city
                if norm_city not in locations:
                    locations.append(norm_city)

        primary_location = locations[0] if locations else "India"

        # 3. Detect Industries
        industries: list[str] = []
        if any(k in prompt_lower for k in ["ai", "tech", "software", "saas", "robotics", "hackathon"]):
            industries.extend(["Artificial Intelligence", "Developer Tools", "FinTech", "Cloud Platforms"])
        if any(k in prompt_lower for k in ["fintech", "finance", "bank", "crypto"]):
            industries.extend(["FinTech", "Payments", "Wealth Management"])
        if any(k in prompt_lower for k in ["beverage", "drink", "food", "fmcg"]):
            industries.extend(["Beverages & Energy Drinks", "FMCG Brands", "Quick Service Restaurants"])
        if any(k in prompt_lower for k in ["gaming", "esports"]):
            industries.extend(["Gaming Hardware", "Game Developers", "Streaming Platforms"])
        if not industries:
            industries = ["Technology", "FinTech", "Consumer Brands"]

        # 4. Detect Society Domains
        societies: list[str] = []
        if any(k in prompt_lower for k in ["robotics", "hardware", "iot"]):
            societies.append("Robotics Society")
        if any(k in prompt_lower for k in ["coding", "hackathon", "computer", "developer"]):
            societies.append("Coding Club")
            societies.append("Developer Student Club")
        if any(k in prompt_lower for k in ["e-cell", "entrepreneurship", "startup"]):
            societies.append("Entrepreneurship Cell (E-Cell)")
        if any(k in prompt_lower for k in ["debate", "mun", "literary"]):
            societies.append("Debating Society")
            societies.append("Literary Society")
        if not societies:
            societies = ["Technical Society", "Entrepreneurship Cell", "Cultural Council"]

        # 5. Generate High-Yield Search Queries
        queries: list[str] = []
        if CategoryEnum.SPONSOR in categories:
            for ind in industries[:2]:
                queries.append(f"top {ind} startups {primary_location} sponsorship marketing head")
                queries.append(f"{ind} companies {primary_location} brand partnerships lead linkedin")
        if CategoryEnum.COLLEGE_DELEGATION in categories:
            for soc in societies[:2]:
                queries.append(f"top engineering colleges {primary_location} {soc} president linkedin")
                queries.append(f"college {soc} {primary_location} council contact")

        # 6. Seed Organizations (detect if specific companies/colleges were directly named)
        seed_orgs: list[TargetOrganization] = []
        for word in prompt.split(","):
            clean_word = word.strip()
            # If prompt mentions phrases like "sponsor like Red Bull", extract
            if any(clean_word.lower().startswith(p) for p in ["like ", "such as ", "including "]):
                entity_name = re.sub(r"^(like|such as|including)\s+", "", clean_word, flags=re.I).strip()
                if entity_name:
                    seed_orgs.append(
                        TargetOrganization(
                            name=entity_name,
                            category=CategoryEnum.SPONSOR if CategoryEnum.SPONSOR in categories else CategoryEnum.COLLEGE_DELEGATION,
                            city=primary_location,
                            notes="Extracted from user seed prompt",
                        )
                    )

        return ParsedPromptContext(
            raw_prompt=prompt,
            event_theme=f"Prospecting in {', '.join(industries[:2])} for {primary_location}",
            target_categories=categories,
            locations=locations if locations else [primary_location],
            target_industries=industries[:4],
            target_societies=societies[:4],
            seed_organizations=seed_orgs,
            generated_search_queries=queries[:6],
        )

