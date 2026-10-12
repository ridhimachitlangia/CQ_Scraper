"""Hybrid Multi-Modal Brochure and PDF Parsing Subsystem.

Combines native PDF text extraction (PyMuPDF), tabular layout analysis (pdfplumber),
and LLM-based entity synthesis with deterministic heuristic fallbacks.
Extracts past sponsors, target sectors, and collegiate delegation profiles.
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Any, Optional, Union
import pymupdf  # Modern PyMuPDF import
import pdfplumber
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from src.models.schema import CategoryEnum, TargetOrganization


class SponsorshipTier(BaseModel):
    """Extracted sponsorship tier or delegate package from brochure."""
    model_config = ConfigDict(extra="ignore")

    tier_name: str = Field(..., description="e.g. Title, Platinum, Gold, Silver, Delegate")
    price_or_perks: Optional[str] = Field(default=None)
    entities_listed: list[str] = Field(default_factory=list)


class BrochureContext(BaseModel):
    """Complete structured context extracted from an event brochure."""
    model_config = ConfigDict(extra="ignore")

    event_name: str = Field(default="Annual Event", description="Name of the event")
    event_edition: Optional[str] = Field(default=None, description="e.g. 2025, 10th Edition")
    event_theme_summary: str = Field(default="", description="Summary of event theme, scope and audience")
    event_location: str = Field(default="National", description="Primary host city or location")
    target_categories: list[CategoryEnum] = Field(
        default_factory=lambda: [CategoryEnum.SPONSOR, CategoryEnum.COLLEGE_DELEGATION]
    )
    past_sponsors_found: list[str] = Field(
        default_factory=list, description="Companies explicitly mentioned or badged in brochure"
    )
    target_industries: list[str] = Field(
        default_factory=list, description="Industries relevant for sponsorship outreach"
    )
    target_societies: list[str] = Field(
        default_factory=list, description="Student societies or clubs relevant for delegations"
    )
    seed_search_queries: list[str] = Field(
        default_factory=list, description="Initial search queries derived from brochure context"
    )
    seed_organizations: list[TargetOrganization] = Field(
        default_factory=list, description="Explicit target companies or societies identified"
    )


class BrochureParser:
    """Extracts structured entities, tiers, and context from PDF event brochures."""

    def __init__(self, max_pages: int = 10):
        self.max_pages = max_pages

    def parse(self, pdf_source: Union[str, Path, bytes]) -> BrochureContext:
        """Main parsing entry point for PDF path or bytes."""
        pdf_bytes = self._load_bytes(pdf_source)
        
        # 1. Digital text & layout extraction
        extracted_text, font_metadata, page_count = self._extract_native_text(pdf_bytes)
        
        # 2. Table extraction for tiers
        table_rows = self._extract_tables(pdf_bytes)
        
        # 3. Raster detection & image rendering if digital text is empty/minimal
        is_raster = len(extracted_text.strip()) < 150
        rendered_images: list[str] = []
        if is_raster:
            logger.warning(
                f"Minimal digital text detected ({len(extracted_text.strip())} chars). "
                f"Falling back to high-DPI raster rendering for Vision extraction."
            )
            rendered_images = self._render_page_images_base64(pdf_bytes, max_images=3)

        # 4. Synthesize structured context via LLM or heuristic fallback
        return self._synthesize_context(
            extracted_text=extracted_text,
            table_rows=table_rows,
            is_raster=is_raster,
            rendered_images=rendered_images,
        )

    def _load_bytes(self, pdf_source: Union[str, Path, bytes]) -> bytes:
        if isinstance(pdf_source, bytes):
            return pdf_source
        path = Path(pdf_source)
        if not path.is_file():
            raise FileNotFoundError(f"PDF brochure not found at path: {path}")
        return path.read_bytes()

    def _extract_native_text(self, pdf_bytes: bytes) -> tuple[str, list[dict[str, Any]], int]:
        """Extracts text blocks and font size metrics using PyMuPDF."""
        text_chunks: list[str] = []
        font_metadata: list[dict[str, Any]] = []

        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            page_count = len(doc)
            pages_to_read = min(page_count, self.max_pages)

            for page_idx in range(pages_to_read):
                page = doc[page_idx]
                text = page.get_text("text")
                if text.strip():
                    text_chunks.append(f"--- Page {page_idx + 1} ---\n{text}")

                # Extract font sizes for hierarchy detection
                blocks = page.get_text("dict").get("blocks", [])
                for b in blocks:
                    for l in b.get("lines", []):
                        for s in l.get("spans", []):
                            font_metadata.append({
                                "text": s.get("text", "").strip(),
                                "size": s.get("size", 0.0),
                                "flags": s.get("flags", 0),
                            })
            doc.close()
            return "\n\n".join(text_chunks), font_metadata, page_count
        except Exception as e:
            logger.error(f"Error extracting native text from PDF: {e}")
            raise ValueError(f"Corrupt or unreadable PDF document: {e}")

    def _extract_tables(self, pdf_bytes: bytes) -> list[list[str]]:
        """Extracts tabular data using pdfplumber."""
        rows: list[list[str]] = []
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for idx, page in enumerate(pdf.pages[:self.max_pages]):
                    tables = page.extract_tables()
                    for t in tables:
                        for row in t:
                            cleaned_row = [str(cell).strip() for cell in row if cell is not None]
                            if cleaned_row:
                                rows.append(cleaned_row)
        except Exception as e:
            logger.warning(f"pdfplumber table extraction warning: {e}")
        return rows

    def _render_page_images_base64(self, pdf_bytes: bytes, max_images: int = 3) -> list[str]:
        """Renders raster pages to base64 JPEG images without external poppler binary."""
        base64_images: list[str] = []
        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            for page_idx in range(min(len(doc), max_images)):
                page = doc[page_idx]
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("jpeg")
                b64_str = base64.b64encode(img_bytes).decode("utf-8")
                base64_images.append(b64_str)
            doc.close()
        except Exception as e:
            logger.error(f"Error rendering PDF pages to image: {e}")
        return base64_images

    def _synthesize_context(
        self,
        extracted_text: str,
        table_rows: list[list[str]],
        is_raster: bool,
        rendered_images: list[str],
    ) -> BrochureContext:
        """Synthesizes structured context using LLM or robust heuristic fallback."""
        # Check if OpenAI API key is available
        if settings.openai_api_key and not settings.openai_api_key.startswith("your_"):
            try:
                return self._synthesize_with_llm(
                    extracted_text=extracted_text,
                    table_rows=table_rows,
                    is_raster=is_raster,
                    rendered_images=rendered_images,
                )
            except Exception as e:
                logger.warning(f"LLM synthesis failed, failing over to heuristic parsing: {e}")

        # Deterministic heuristic fallback
        return self._heuristic_parse(extracted_text, table_rows)

    def _synthesize_with_llm(
        self,
        extracted_text: str,
        table_rows: list[list[str]],
        is_raster: bool,
        rendered_images: list[str],
    ) -> BrochureContext:
        """Extracts structured entities via LangChain ChatOpenAI with structured output."""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.0,
            openai_api_key=settings.openai_api_key,
        )
        structured_llm = llm.with_structured_output(BrochureContext)

        system_prompt = (
            "You are an expert event sponsorship director and collegiate delegation scout. "
            "Analyze the provided event brochure content to extract target corporate sponsors, "
            "collegiate society chapters, past partners, and high-value search queries. "
            "Be precise and never invent partners that are not referenced or logical."
        )

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"Extracted Text:\n{extracted_text[:8000]}\n\n"
                    f"Tabular Tiers:\n{table_rows[:20]}"
                ),
            }
        ]

        # Add multimodal images if raster-based
        if is_raster and rendered_images:
            for b64 in rendered_images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=content),
        ]

        result = structured_llm.invoke(messages)
        if isinstance(result, BrochureContext):
            return result
        elif isinstance(result, dict):
            return BrochureContext(**result)
        return self._heuristic_parse(extracted_text, table_rows)

    def _heuristic_parse(self, text: str, tables: list[list[str]]) -> BrochureContext:
        """Deterministic heuristic extraction when LLM is unavailable or offline."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        # 1. Event Name Heuristic: Usually first non-empty prominent line
        event_name = lines[0] if lines else "Event Outreach Campaign"
        for line in lines[:5]:
            if any(k in line.lower() for k in ["fest", "conclave", "hackathon", "summit", "conference", "carnival"]):
                event_name = line
                break

        # 2. Location Heuristic: Look for major cities or addresses
        location = "National"
        indian_metro_cities = [
            "Mumbai", "Delhi", "Bengaluru", "Bangalore", "Hyderabad", "Chennai",
            "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Chandigarh", "Noida", "Gurugram"
        ]
        for line in lines:
            for city in indian_metro_cities:
                if re.search(rf"\b{city}\b", line, re.IGNORECASE):
                    location = city
                    break
            if location != "National":
                break

        # 3. Past Sponsors / Partners mentions
        past_sponsors: list[str] = []
        capture_sponsors = False
        for line in lines:
            line_lower = line.lower()
            if any(k in line_lower for k in ["past sponsor", "previous sponsor", "our partners", "powered by", "title sponsor"]):
                capture_sponsors = True
                continue
            if capture_sponsors:
                if any(k in line_lower for k in ["contact", "about us", "register", "agenda", "schedule"]):
                    capture_sponsors = False
                elif len(line) < 40 and not line.startswith("---"):
                    past_sponsors.append(line)

        # 4. Target industries based on event keywords
        target_industries: list[str] = []
        text_lower = text.lower()
        if any(k in text_lower for k in ["code", "tech", "hackathon", "ai", "developer", "software"]):
            target_industries.extend(["Developer Tools", "Cloud Infrastructure", "FinTech", "EdTech"])
        if any(k in text_lower for k in ["business", "case", "consulting", "e-cell", "entrepreneurship"]):
            target_industries.extend(["Venture Capital", "Financial Services", "Management Consulting"])
        if any(k in text_lower for k in ["cultural", "dance", "music", "drama", "fashion"]):
            target_industries.extend(["Beverages & FMCG", "Apparel", "Entertainment & Media"])
        if not target_industries:
            target_industries = ["Consumer Brands", "FinTech", "Technology"]

        # 5. Target college societies
        target_societies = [
            "Coding Club",
            "Robotics Society",
            "E-Cell (Entrepreneurship Cell)",
            "Debating Society",
            "Student Council",
        ]

        # 6. Seed search queries
        seed_queries = [
            f"{location} corporate sponsors for {event_name}",
            f"{target_industries[0]} companies sponsorship contact {location}",
            f"top college technical societies {location} president",
        ]

        # 7. Seed Target Organizations
        seed_orgs: list[TargetOrganization] = []
        for sponsor in past_sponsors[:5]:
            seed_orgs.append(
                TargetOrganization(
                    name=sponsor,
                    category=CategoryEnum.SPONSOR,
                    city=location,
                    notes="Identified from brochure past sponsors",
                )
            )

        return BrochureContext(
            event_name=event_name,
            event_theme_summary=f"Event identified as {event_name} based in {location}.",
            event_location=location,
            target_categories=[CategoryEnum.SPONSOR, CategoryEnum.COLLEGE_DELEGATION],
            past_sponsors_found=past_sponsors[:8],
            target_industries=list(set(target_industries))[:5],
            target_societies=target_societies,
            seed_search_queries=seed_queries,
            seed_organizations=seed_orgs,
        )

