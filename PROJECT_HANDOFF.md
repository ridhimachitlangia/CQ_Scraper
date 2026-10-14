# PROJECT HANDOFF & CONTEXT TRANSFER DOCUMENT
**Project:** Autonomous Lead Discovery & Verification Agent (CQ Scraper)  
**Framework:** LangGraph Multi-Agent Architecture (Python 3.11+ / 3.14)  
**Status:** Phases 0, 1, 2, 3, 4, 5, and 6 Fully Implemented & Verified (92/92 Tests Passing)  
**Current Handover Point:** Ready for **Phase 7 (Hands-Free Google Sheets & Local SQLite Sync)**

---

## 1. Executive Summary & Problem Statement

Finding B2B event sponsors and collegiate delegations for events typically requires extensive manual digging across corporate websites, student councils, and social networks. Most public contact info is either hidden, outdated, or guarded by generic gatekeeper mailboxes (`info@`, `contact@`, `admin@`).

### The Objective
Build an autonomous AI agent using **LangGraph** that takes either a natural language search prompt or an uploaded event brochure (PDF), independently searches and crawls the web, extracts real human decision-makers (not generic inboxes), verifies their contact deliverability in real-time, and automatically streams clean, structured rows into a Google Sheet and database with zero manual intervention.

### 100-Point Evaluation Benchmark
| Metric | Points | Project Implementation Status |
| :--- | :---: | :--- |
| **Agent Flow & Autonomy** (searches, follows links, handles dead pages) | **40** | **Phases 3, 4 & 6 Done** (Resilient crawler, link prioritization, dead-page failover, query reformulation, compiled LangGraph state machine with self-healing feedback loops). |
| **Contact Accuracy** (real, deliverable contacts, no hallucinated data) | **30** | **Phases 4 & 5 Done** (Zero-hallucination extractor, pattern engine, DNS MX, non-intrusive SMTP handshake, catch-all detection, profile HEAD checks). |
| **Brochure / PDF Parsing** (extracts targets from uploaded brochure) | **15** | **Phase 2 Done** (Hybrid PyMuPDF + pdfplumber + Vision OCR raster fallback). |
| **End-to-End Pipeline** (hands-free, from query to populated sheet) | **15** | **Phases 1, 3 & 6 Done**. Phases 7 & 8 will wire live Google Sheet sync & streaming API. |
| **TOTAL** | **100** | On track for full 100/100 points. |

---

## 2. Strict 6-Field Output Schema & Data Constraints

The system outputs records matching this exact 6-field schema. Any violation or invented data immediately fails evaluation:

| Field Name | Type / Permitted Values | Enforcement & Business Logic |
| :--- | :--- | :--- |
| **`Organization Name`** | `string` | Company or student society name. Free of legal noise (Inc, LLC). Non-empty. |
| **`Category`** | `enum` | **Strictly** `"Sponsor"` or `"College Delegation"`. |
| **`Location`** | `string` | Base city (e.g., `"Bengaluru"`, `"Mumbai"`, `"Delhi"`). |
| **`Contact Person`** | `string` | **Strictly formatted as** `"[Full Name] - [Role]"` (e.g., `"Sarah Connor - VP Marketing"`, `"Devika Sen - Society President"`). Generic names/roles (*"Marketing Team"*, *"Admin"*, *"Student Council"*) are permanently rejected. |
| **`Contact Channel`** | `string` | Deliverable direct email (`sarah.connor@acme.com`) OR verified authentic profile URL (`https://linkedin.com/in/sarah-connor`, `https://instagram.com/robotics_club`). Generic inboxes (`info@*`, `contact@*`, `support@*`, etc.) are prohibited. |
| **`Verification Status`** | `enum` | **Strictly** `"Verified"` or `"Pattern-Derived"`. Unverified / hallucinated leads are discarded. |

---

## 3. Technology Stack & Environment

- **Python Runtime:** Python 3.14 in isolated virtual environment (`.venv/`)
- **Agent Orchestrator:** LangGraph 1.2+ (`StateGraph`, Checkpointing, Typed State Reducers)
- **LLM Layer:** LangChain Core, LangChain OpenAI (`gpt-4o`), LangChain Anthropic
- **Document & PDF Parsing:** PyMuPDF (`pymupdf`), `pdfplumber`, `pdf2image`, `Pillow`
- **Search & Crawling:** `tavily-python`, Serper API, `httpx`, `trafilatura`, `crawl4ai` (configured with local `.crawl4ai` cache), Playwright Chromium (pre-installed in `~/.cache/ms-playwright/chromium-1243`)
- **Deliverability & Verification:** `dnspython`, `aiosmtplib`, `email-validator`
- **Storage & Synchronization:** `gspread`, `google-auth`, `sqlalchemy`, `aiosqlite`
- **API & UI Protocol:** `fastapi`, `uvicorn`, `python-multipart`, Server-Sent Events (SSE)
- **Test Framework:** `pytest` (9.1+), `pytest-asyncio`, `pytest-mock`

---

## 4. Current Status: What Has Been Built & Tested

All tasks across **Phases 0 through 6** are 100% complete with **92 automated tests passing**:

```
============================== 92 passed in 1.39s ==============================
```

### Phase 0: Workspace & Dependency Isolation
- Virtual environment at `.venv/`.
- Clean `.gitignore` ignoring `.venv/`, `.env`, secrets, `.crawl4ai/`, and Playwright caches.
- `requirements.txt` with locked dependencies.
- `.env.example` defining all required API keys.
- `config/settings.py` built on `pydantic-settings` (with modern `SettingsConfigDict` and local `CRAWL4_AI_BASE_DIRECTORY` setup).

### Phase 1: Core Schemas, Data Contracts & LangGraph State (`src/models/`)
- **`src/models/schema.py`**:
  - `CategoryEnum` and `VerificationStatusEnum`.
  - `FinalLeadRecord`: Strictly enforces 6-field sheet schema, validator blocking generic inboxes and unformatted roles, `sheet_headers()`, and `to_sheet_row()`.
  - `TargetOrganization`, `DecisionMakerRole`, `DecisionMakerCandidate`, `EmailPatternRule`, `ScrapedPageSnapshot`.
- **`src/models/state.py`**:
  - `AgentState`: Master LangGraph `TypedDict` using `operator.add` reducers for accumulating verified leads, dead URLs, visited URLs, and audit logs.
  - `create_initial_state(...)`: Safe state initialization factory.
- **`tests/test_schema.py`**: 26 unit tests covering schema validation, generic inbox rejection, and state creation.

### Phase 2: Brochure & Prompt Parsing Subsystem (`src/parsers/`)
- **`src/parsers/brochure_parser.py` (`BrochureParser`)**:
  - Native digital text and font metadata extraction via PyMuPDF.
  - Sponsorship tier table extraction via `pdfplumber`.
  - Scanned/raster PDF detection (<150 text characters) with high-DPI base64 pixmap rendering for Vision OCR fallback.
  - LLM extraction via structured output with deterministic heuristic fallback when offline.
- **`src/parsers/prompt_expander.py` (`PromptExpander`)**:
  - Natural language query deconstruction into target categories, location normalization (e.g. Bangalore $\to$ Bengaluru), target industries, and high-affinity society domains.
  - Search dork query synthesis targeting marketing/CSR leads and society presidents.
- **`tests/test_brochure_parser.py`**: 8 unit tests testing synthetic multi-page PDFs, real problem statement PDF, and query expansion.

### Phase 3: Autonomous Web Search & Resilient Deep Crawling Engine (`src/search/` & `src/crawler/`)
- **`src/search/query_generator.py` (`QueryGenerator`)**:
  - Contextual search dork generator for sponsors, college delegations, and dead-page recovery.
- **`src/search/search_client.py` (`UnifiedSearchClient`)**:
  - Multi-provider async search with failover: Tavily API $\to$ Serper (Google Search) $\to$ deterministic offline candidate generator.
- **`src/crawler/link_prioritizer.py` (`LinkPrioritizer`)**:
  - URL normalization (resolves relative links, drops query params/fragments).
  - High-priority scoring (+10) for `/team`, `/about-us`, `/leadership`, `/people`, `/executive-board`, `/council`.
  - Immediate blacklisting (-100) of boilerplate/spider traps (`/privacy`, `/terms`, `/login`, `/careers`, `.pdf`, `.png`).
- **`src/crawler/resilience.py` (`DeadLinkHandler`, `ResilientFetcher`)**:
  - Dead page detection (404, 403, 500, 502, timeouts). Does **not** crash the run; logs to `dead_urls` and triggers query reformulation.
  - Async HTTP client with rotating desktop User-Agents, exponential backoff, and polite jitter delays.
- **`src/crawler/deep_crawler.py` (`DeepCrawler`)**:
  - Deep multi-page crawler parsing clean markdown via Trafilatura.
  - Dynamic SPA detection (React, Next.js, Vue) with automatic headless browser execution fallback via Crawl4AI.
  - Extraction of internal links, emails, and social profiles.
- **`tests/test_crawler_and_search.py`**: 12 unit tests validating crawling, link prioritization, and dead-link recovery.

### Phase 4: Decision-Maker Extraction & Pattern Derivation (`src/extractors/`)
- **`src/extractors/pattern_engine.py` (`EmailPatternEngine`)**:
  - Domain-level naming pattern recognition (`{first}.{last}@{domain}`, `{f}{last}@{domain}`, `{first}_{last}@{domain}`, etc.).
  - **Zero-Hallucination Mandate:** Requires **at least 2 non-generic employee sample emails** on the target domain before derivation is permitted.
  - Synthesizes candidate emails for identified decision-makers.
- **`src/extractors/decision_maker.py` (`DecisionMakerExtractor`)**:
  - Role hierarchy prioritization for Sponsors (CMO, VP Marketing, CSR Head) and College Delegations (President, Convenor, General Secretary).
  - Strict Negative Filter: Rejects generic departments (*"Marketing Team"*, *"Admin"*) as human names, and permanently strips central inboxes (`info@`, `contact@`) from `direct_email`.
  - Personal social profile filtering (preserves `linkedin.com/in/*`, `instagram.com/*`, `x.com/*`, while excluding company pages `linkedin.com/company/*`).
  - LLM structured output with deterministic regex fallback.
  - Automatic integration with `EmailPatternEngine` when email is absent.
- **`tests/test_decision_maker.py`**: 10 unit tests verifying extraction, pattern derivation, and generic email nullification.

### Phase 5: Multi-Stage Contact Deliverability & Verification Engine (`src/verifier/`)
- **`src/verifier/syntax_check.py` (`EmailSyntaxValidator`)**:
  - RFC 5321/5322 syntax validation via `email-validator`.
  - Common domain typo auto-detection and suggestion (`gmial.com` -> `gmail.com`, `outlok.com` -> `outlook.com`).
  - Negative filter rejecting generic corporate inboxes (`info@`, `contact@`, `admin@`, etc.).
- **`src/verifier/mx_resolver.py` (`DNSMXResolver`)**:
  - Asynchronous DNS MX record lookup via `dnspython` with priority-sorted records.
  - RFC 7505 Null MX detection (rejects domains with null mail exchangers).
  - Handles NXDOMAIN and NoAnswer with in-memory caching.
- **`src/verifier/smtp_handshake.py` (`SMTPHandshakeVerifier`)**:
  - Non-intrusive asynchronous socket handshake (`HELO` -> `MAIL FROM` -> `RCPT TO` -> `RSET` -> `QUIT`).
  - Never transmits message data (`DATA` command is prohibited).
  - Catch-All probing with randomized test recipient addresses.
  - Graceful port 25 blocking / firewall fallback handling.
- **`src/verifier/social_validator.py` (`SocialProfileValidator`)**:
  - Asynchronous HTTP HEAD/GET validation of personal profile links (LinkedIn `/in/*`, Instagram, X, faculty directories).
  - Negative filtering of corporate pages (`linkedin.com/company/*`, `instagram.com/p/*`, `x.com/explore`).
  - Detection of 404/suspended/deleted profile pages.
- **`src/verifier/contact_verifier.py` (`ContactVerifier`)**:
  - Master pipeline coordinating syntax check -> MX resolution -> SMTP handshake & catch-all test -> pattern derivation check -> social profile fallback.
  - Strictly enforces Zero-Hallucination mandate: unverified leads return `is_deliverable=False` or `None`.
  - `verify_decision_maker` helper generating validated 6-field `FinalLeadRecord`.
- **`tests/test_verifier.py`**: 20 unit tests covering syntax, typo correction, MX resolution, SMTP handshakes, catch-all detection, and end-to-end verification.

### Phase 6: LangGraph State Machine Assembly & Feedback Loops (`src/graph/`)
- **`src/graph/nodes.py`**:
  - `parse_input_node`: Ingests brochure PDF or search query; generates target seeds filtered by category focus.
  - `expand_targets_node`: Synthesizes corporate and delegation search queries via `QueryGenerator`.
  - `search_web_node`: Queries Google/Tavily via `UnifiedSearchClient` and ranks candidate URLs.
  - `crawl_page_node`: Deep crawls target domains, parses markdown, extracts emails and handles dead links.
  - `dead_link_recovery_node`: Generates dead-page pivot queries and increments retry counts without failing the run.
  - `extract_decision_maker_node`: Extracts human decision-makers, rejecting generic mailboxes.
  - `social_dork_search_node`: Fallback LinkedIn search when direct corporate websites contain no individual names.
  - `verify_contact_node`: Coordinates multi-stage deliverability verification via `ContactVerifier` and advances the target queue.
  - `sync_sheet_node`: Formats the final 6-column sheet rows and marks workflow completion.
- **`src/graph/edges.py`**:
  - `route_after_crawl`: Routes dead/blocked pages to `dead_link_recovery` or advances to extraction.
  - `route_after_extraction`: Routes to `social_dork_search` if website lacks names or advances to verification.
  - `route_after_verification`: Self-healing cyclical loop back to `expand_targets` until queue exhaustion or quota reached.
- **`src/graph/lead_graph.py`**:
  - Compiles master `StateGraph(AgentState)` with `MemorySaver` checkpointer for state auditability, pause/resume, and event streaming.
- **`tests/test_graph_flow.py`**: 16 unit and integration tests covering node execution, conditional branching, dead link recovery, and full end-to-end flow.

---

## 5. File & Module Structure

```
CQ_Scraper/
├── .gitignore                          # Configured for .venv, .crawl4ai, credentials, caches
├── .env.example                        # API keys template
├── requirements.txt                    # Locked production dependencies
├── problem-statement.pdf               # Original problem statement specification
├── Project_Architecture.md             # High-level architecture specification
├── Implementation roadmap.md           # Sequential phase roadmap with micro tasks
├── spec_scraper.md                     # Technical spec sheet for complex modules
├── Ai_Prompt_guidelines.md             # Strict coding & anti-hallucination rules
├── Design.md                           # Modern dashboard UI design guidelines
├── PROJECT_HANDOFF.md                  # This handover document
│
├── config/
│   ├── __init__.py
│   └── settings.py                     # Pydantic BaseSettings, env loader, Crawl4AI dir setup
│
├── src/
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── schema.py                   # FinalLeadRecord (6 fields), Enums, intermediate models
│   │   └── state.py                    # AgentState TypedDict & factory
│   │
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── brochure_parser.py          # PyMuPDF + pdfplumber + Pixmap Vision OCR parser
│   │   └── prompt_expander.py          # Natural language intent & dork generator
│   │
│   ├── search/
│   │   ├── __init__.py
│   │   ├── query_generator.py          # Corporate & delegation dork builder
│   │   └── search_client.py            # Unified search (Tavily / Serper / Mock fallback)
│   │
│   ├── crawler/
│   │   ├── __init__.py
│   │   ├── link_prioritizer.py         # Leadership URL scoring and blacklist
│   │   ├── resilience.py               # Dead-link handling & polite resilient HTTP fetcher
│   │   └── deep_crawler.py             # Trafilatura + Crawl4AI SPA crawler
│   │
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── pattern_engine.py           # Domain email pattern engine (>=2 samples rule)
│   │   └── decision_maker.py           # Persona extractor & generic email nullifier
│   │
│   ├── verifier/                       # [PHASE 5 TARGET]
│   │   ├── __init__.py
│   │   ├── syntax_check.py             # RFC-5322 compliance & typo checker
│   │   ├── mx_resolver.py              # Asynchronous DNS MX record resolver
│   │   ├── smtp_handshake.py           # Non-intrusive SMTP RCPT TO & catch-all tester
│   │   ├── social_validator.py         # HTTP HEAD/GET live status checker
│   │   └── contact_verifier.py         # Master multi-stage verification pipeline
│   │
│   ├── graph/                          # [PHASE 6 TARGET]
│   │   ├── __init__.py
│   │   ├── nodes.py                    # LangGraph execution nodes
│   │   ├── edges.py                    # Conditional routers (dead link pivot, retry loops)
│   │   └── lead_graph.py               # StateGraph compilation & MemorySaver checkpointer
│   │
│   ├── storage/                        # [PHASE 7 TARGET]
│   │   ├── __init__.py
│   │   ├── database.py                 # SQLite local persistence & audit logs
│   │   └── google_sheets.py            # gspread batch row sync & header styling
│   │
│   └── api/                            # [PHASE 8 TARGET]
│       ├── __init__.py
│       ├── app.py                      # FastAPI server instance
│       ├── routes.py                   # /api/run, /api/status, /api/export
│       └── stream.py                   # SSE event streaming generator
│
└── tests/                              # Comprehensive test suite (56 tests)
    ├── __init__.py
    ├── test_schema.py                  # 26 tests
    ├── test_brochure_parser.py         # 8 tests
    ├── test_crawler_and_search.py      # 12 tests
    └── test_decision_maker.py          # 10 tests
```

---

## 6. What Needs to Be Done Next: Step-by-Step

Phases 0 through 6 are complete and verified. The next step is **Phase 7 through Phase 10** in sequential order:

### NEXT STEP: Phase 7 — Hands-Free Google Sheets & Local SQLite Sync
*(Targeting 15 Points: End-to-End Pipeline)*
1. **`src/storage/google_sheets.py`**:
   - Authenticate with Google Service Account credentials via `gspread`.
   - Idempotent sheet initialization: enforce exact 6-column headers with navy styling (`#1E293B`) and frozen header row.
   - Deduplication against existing rows (`Organization Name` and `Contact Channel`).
   - Batch row insertion (`append_rows`) in chunks to respect Google API limits.
   - Color code `Verification Status` cells (Green for "Verified", Amber for "Pattern-Derived").
2. **`src/storage/database.py`**:
   - Local SQLite database (`aiosqlite`) storing run histories, raw crawl snippets, MX records, and timestamps for offline replayability and evaluation audit.
3. **`tests/test_storage.py`**:
   - Unit tests mocking `gspread` client, batch insertions, duplicate prevention, and SQLite persistence.

---

#### Phase 7: Hands-Free Google Sheets & Local SQLite Sync
- **`src/storage/google_sheets.py`**: Google Service Account authentication via `gspread`, automatic header creation with navy styling (`#1E293B`), deduplication against existing rows, and batch cell insertion (`append_rows`).
- **`src/storage/database.py`**: Local SQLite database for audit trails and offline replayability.

#### Phase 8: FastAPI Backend & Real-Time Event Streaming
- Endpoints: `POST /api/run` (FormData supporting prompt or brochure upload), `GET /api/stream/{session_id}` (SSE streaming events from LangGraph `astream_events()`), `GET /api/leads/{session_id}`.

#### Phase 9: Modern Frontend Dashboard UI
- Next.js 14 / React dashboard matching [`Design.md`](file:///home/vivekk-117/repositories/CQ_Scraper/Design.md):
  - Hero input zone with prompt textarea and PDF drag-and-drop dropzone.
  - Live pipeline stepper + JetBrains Mono terminal log feed.
  - Interactive 6-column leads table with status badges (Green = Verified, Amber = Pattern-Derived).
  - Prominent "Open in Google Sheets" action banner.

#### Phase 10: Verification, Testing & Benchmark Audit
- End-to-end integration run testing both an uploaded brochure and a natural language search query down to a live Google Sheet.

---

## 7. Developer Quickstart Guide

### 1. Activating Virtual Environment
```bash
cd /home/vivekk-117/repositories/CQ_Scraper
source .venv/bin/activate
```

### 2. Running Test Suite
```bash
# Run all 56 tests
pytest tests/ -v

# Run with short test output
pytest tests/ -q
```

### 3. Setting API Credentials (when available)
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in the credentials:
- `OPENAI_API_KEY`: For LLM structured outputs (heuristic fallback automatically engages if omitted).
- `TAVILY_API_KEY` / `SERPER_API_KEY`: For web search (mock search automatically engages if omitted).
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to Service Account JSON key for Google Sheets sync.
- `GOOGLE_SPREADSHEET_ID`: (Optional) Existing spreadsheet ID.

---

## 8. Critical Coding Principles & Non-Negotiables

Any engineer or AI modifying this codebase **must** adhere to [`Ai_Prompt_guidelines.md`](file:///home/vivekk-117/repositories/CQ_Scraper/Ai_Prompt_guidelines.md):
1. **Zero-Hallucination Mandate:** Never invent, predict, or guess an email address or contact person. Every lead must be grounded in an actual crawled page or search result with `source_url` provenance.
2. **Prohibited Generic Inboxes:** Central mailboxes (`info@`, `contact@`, `admin@`, `support@`, `sales@`, `hello@`, etc.) must never be output as `Contact Channel`. If only a generic email is found, nullify it and discover the decision-maker's LinkedIn/social profile instead.
3. **Format Integrity:** `Contact Person` must always be `"[Full Name] - [Role]"`.
4. **Pattern Derivation Rule:** Domain pattern derivation is strictly prohibited unless at least two non-generic employee emails on that domain are observed.
5. **Autonomy on Dead Pages:** Web crawlers must never fail an agent run due to 404, 403, or connection timeouts. Log to `dead_urls` and invoke `DeadLinkHandler` to pivot.

