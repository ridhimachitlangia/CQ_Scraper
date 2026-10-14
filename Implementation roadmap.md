# Implementation Roadmap: Autonomous Lead Discovery & Verification Agent

This roadmap outlines the complete, sequential engineering execution plan. Each phase is decomposed into micro elementary tasks with clear acceptance criteria (Definition of Done) to ensure the agent achieves **100/100 points** on the evaluation benchmark.

---

## Phase 0: Environment Setup, Tooling & Workspace Initialization

### Objective
Establish the repository baseline, virtual environment, dependency management, and configuration secrets.

#### Micro Elementary Tasks:
- [x] **Task 0.1: Virtual Environment & Dependency Isolation**
  - Initialize Python 3.11+ virtual environment (`python -m venv venv`).
  - Configure `requirements.txt` with locked versions (`langgraph>=0.2.20`, `langchain-core`, `langchain-openai`, `pydantic>=2.7`, `fitz` (PyMuPDF), `pdfplumber`, `trafilatura`, `crawl4ai`, `aiosmtplib`, `dnspython`, `gspread`, `fastapi`, `uvicorn`, `httpx`, `pytest`, `python-dotenv`).
  - Install Playwright browsers (`playwright install chromium`).
- [x] **Task 0.2: Configuration & Environment Management (`config/settings.py`)**
  - Create `.env.example` defining `OPENAI_API_KEY`, `TAVILY_API_KEY`, `SERPER_API_KEY`, `GOOGLE_SHEET_CREDENTIALS_JSON`, `GOOGLE_SPREADSHEET_ID`.
  - Implement `AppSettings` using `pydantic-settings` with strict type checking, fail-fast validations, and defaults.
- [ ] **Task 0.3: Google Cloud & Service Account Provisioning**
  - Enable Google Drive API and Google Sheets API in Google Cloud Console.
  - Generate Service Account JSON key, restrict permissions, and write automated credential loading helper in `src/storage/google_sheets.py`.

---

## Phase 1: Core Schemas, Data Contracts & LangGraph State Definition

### Objective
Establish the immutable data contracts for the 6-field sheet output and LangGraph's state machine.

#### Micro Elementary Tasks:
- [x] **Task 1.1: The 6-Field Output Schema (`src/models/schema.py`)**
  - Define `CategoryEnum` (`"Sponsor"`, `"College Delegation"`).
  - Define `VerificationStatusEnum` (`"Verified"`, `"Pattern-Derived"`).
  - Implement `FinalLeadRecord` with aliases matching the required sheet columns:
    1. `Organization Name` (str)
    2. `Category` (CategoryEnum)
    3. `Location` (str)
    4. `Contact Person` (str - formatted as `"[Full Name] - [Role]"`)
    5. `Contact Channel` (str - valid deliverable email or live profile URL)
    6. `Verification Status` (VerificationStatusEnum)
  - Implement Pydantic validators forbidding generic role-less contacts, placeholder values ("N/A", "Unknown"), or central inboxes (`info@`, `contact@`, `admin@`).
- [x] **Task 1.2: Intermediate Extraction Models**
  - Implement `TargetOrganization`, `DecisionMakerCandidate`, `EmailPatternRule`, and `ScrapedPageSnapshot`.
- [x] **Task 1.3: LangGraph State Modeling (`src/models/state.py`)**
  - Define `AgentState` TypedDict with typed reducers (`operator.add` for lists) for audit logs, candidate leads, visited URLs, and dead URLs.
  - Add state flags: `retry_count`, `active_org_index`, `is_complete`.

---

## Phase 2: Input Processing & Brochure / PDF Parsing Subsystem
*(Targeting 15 Points: Brochure / PDF Parsing)*

### Objective
Transform natural language search queries and event PDF brochures into structured target seeds.

#### Micro Elementary Tasks:
- [x] **Task 2.1: Native PDF Text & Layout Extractor (`src/parsers/brochure_parser.py`)**
  - Implement PyMuPDF (`fitz` / `pymupdf`) and `pdfplumber` extraction to extract text blocks, tables, and metadata.
  - Implement font-size heuristics to identify headlines, tier headers ("Title Sponsor", "Associate Sponsor", "College Chapters"), and past partners.
- [x] **Task 2.2: Visual OCR & Poster Image Fallback**
  - Handle graphic-heavy PDF brochures (where text is embedded in raster images) by converting PDF pages to images using `pymupdf` pixmaps.
  - Pass raster pages through an OCR/Vision LLM extraction prompt to parse logos and partner mentions.
- [x] **Task 2.3: Entity & Target Synthesis Prompting**
  - Construct prompt that ingests extracted brochure text/visuals and outputs:
    1. Event Domain / Theme (e.g., Tech Hackathon, Business Conclave, Cultural Fest).
    2. Existing / Past Sponsors mentioned in the brochure.
    3. Prospecting Sectors (e.g., FinTech, Cloud Hosting, FMCG, Beverage brands).
    4. Target College Clubs / Societies (e.g., Coding Clubs, Debating Societies, E-Cells).
- [x] **Task 2.4: Search Prompt Intent Deconstruction (`src/parsers/prompt_expander.py`)**
  - Parse unstructured search queries (e.g., *"Find AI startup sponsors and robotics college societies in Bangalore for our hackathon"*) into structured target entities and geographic filters.

---

## Phase 3: Autonomous Web Search & Resilient Deep Crawling Engine
*(Targeting 40 Points: Agent Flow & Autonomy)*

### Objective
Build an autonomous link harvester and crawler that navigates the web, prioritizes high-value leadership pages, handles dead pages, and circumvents anti-scraping blocks.

#### Micro Elementary Tasks:
- [x] **Task 3.1: Dual Search Client (`src/search/search_client.py`)**
  - Implement unified client for Tavily Search and Serper (Google Search) with automatic fallback.
  - Implement Dorking generators:
    - Corporate: `"{company} leadership team"`, `"{company} VP marketing"`, `"{company} CSR head email"`
    - College: `"{college} {society} president"`, `"{college} {society} team contact"`
- [x] **Task 3.2: Link Prioritization & Scoring Engine (`src/crawler/link_prioritizer.py`)**
  - Score discovered URLs based on path keywords:
    - High priority (+10): `/team`, `/about-us`, `/leadership`, `/people`, `/executive-board`, `/council`
    - Medium priority (+5): `/contact`, `/press`, `/sponsor`, `/partners`
    - Blacklisted (-100): `/privacy-policy`, `/terms`, `/login`, `/careers`, `/cart`
- [x] **Task 3.3: Resilient HTML Fetcher with Dead Page Handling (`src/crawler/resilience.py`)**
  - Implement async HTTP client (`httpx`) with rotating User-Agents, configurable timeouts (10s), and exponential backoff retry.
  - Implement explicit dead link handler: detects HTTP 404, 403, 500, 502, DNS NXDOMAIN, and connection timeouts.
  - When a page is dead, log the event, mark URL in `dead_urls`, and immediately trigger fallback query generation (e.g., search alternative domain or social page) without failing the run.
- [x] **Task 3.4: Headless Browser JS-Rendering Fallback (`src/crawler/deep_crawler.py`)**
  - Implement Crawl4AI / Playwright fallback for SPA websites (React, Vue, Webflow) that return empty `<div id="root">` via static requests.
  - Extract clean, readable markdown content via Trafilatura.

---

## Phase 4: Decision-Maker Extraction & Pattern Derivation
*(Targeting 30 Points: Contact Accuracy & No Generic Inboxes)*

### Objective
Extract the actual individual decision-maker (name and role) and discover their email or profile link, rejecting all generic mailboxes.

#### Micro Elementary Tasks:
- [x] **Task 4.1: Role-Specific Persona Extractor (`src/extractors/decision_maker.py`)**
  - Implement structured LLM extraction prompt enforcing the hierarchy of decision-makers:
    - Sponsors: Head of Marketing, VP Marketing, Chief Marketing Officer, CSR Head, Brand Partnerships Director, Founder.
    - College Delegations: Society President, Convenor, General Secretary, Team Captain, Faculty In-Charge.
  - Strict Negative Filter: Reject general support emails (`info@`, `contact@`, `hello@`, `admin@`, `support@`, `careers@`). If only a generic email is found, discard it and mandate discovering the specific individual's LinkedIn or social profile instead.
- [x] **Task 4.2: Social Profile Extraction**
  - Extract authentic personal profile links: LinkedIn (`linkedin.com/in/*`), Instagram (`instagram.com/*` for college societies), Twitter/X, and official university faculty/student directory URLs.
- [x] **Task 4.3: Email Format Pattern Derivation Engine (`src/extractors/pattern_engine.py`)**
  - If a decision-maker's name is known (e.g., "Arun Kumar") and corporate emails for other team members are visible on the domain (e.g., "priya.nair@acme.com", "vikram.singh@acme.com"):
    - Identify the domain pattern: `{first}.{last}@{domain}`.
    - Synthesize candidate email: `arun.kumar@acme.com`.
    - Tag as candidate for `"Pattern-Derived"` status.

---

## Phase 5: Multi-Stage Contact Deliverability & Verification Engine
*(Targeting 30 Points: Deliverable Contacts & Anti-Hallucination Guardrails)*

### Objective
Verify that every extracted contact channel is genuine, exists, and is deliverable before it reaches the final output sheet.

#### Micro Elementary Tasks:
- [x] **Task 5.1: RFC Syntax & Typo Validation (`src/verifier/syntax_check.py`)**
  - Validate syntax against RFC 5321/5322 via `email-validator`.
  - Check for common domain typos (`gmial.com`, `outlok.com`).
- [x] **Task 5.2: DNS MX Record Resolver (`src/verifier/mx_resolver.py`)**
  - Query DNS MX records via `dnspython` with asynchronous resolver.
  - Verify that the target domain has active, reachable mail exchange servers. Discard emails with missing or null MX records.
- [x] **Task 5.3: Non-Intrusive SMTP Handshake & Catch-All Detection (`src/verifier/smtp_handshake.py`)**
  - Connect to target MX host on port 25 with a polite HELO/EHLO identity.
  - Send `MAIL FROM:<verify@verified-leads.org>` and `RCPT TO:<candidate@domain.com>`.
  - Capture SMTP response codes (250 OK = deliverable, 550 = mailbox does not exist).
  - Catch-All Detection: Test a randomized fake address (e.g., `test_random_chk_99812@domain.com`). If the server returns 250 for the fake address, flag domain as Catch-All.
  - Classification:
    - Direct 250 OK on individual email (Non-Catch-All) $\to$ `"Verified"`.
    - Derived via pattern on Catch-All or confirmed domain $\to$ `"Pattern-Derived"`.
    - 550 / Dead $\to$ Discard completely.
- [x] **Task 5.4: Social Profile Liveness Verification (`src/verifier/social_validator.py`)**
  - Perform async HTTP `HEAD` or `GET` request to candidate profile URLs.
  - Confirm HTTP 200 response and absence of "Profile Not Found", "Page Expired", or "Login Required" error screens.
  - Mark verified live profile links as `"Verified"`.

---

## Phase 6: LangGraph State Machine Assembly & Autonomous Feedback Loops
*(Targeting 40 Points: Agent Flow & Autonomy)*

### Objective
Assemble the isolated nodes into an autonomous LangGraph `StateGraph` with conditional branches, retry limits, and dead-page recovery.

#### Micro Elementary Tasks:
- [x] **Task 6.1: Node Implementation (`src/graph/nodes.py`)**
  - Implement `parse_input_node`, `expand_targets_node`, `search_web_node`, `crawl_page_node`, `extract_decision_maker_node`, `verify_contact_node`, `sync_sheet_node`.
- [x] **Task 6.2: Conditional Edges & Routing (`src/graph/edges.py`)**
  - `route_after_crawl`: If current URL returned 404 or dead, route to `handle_dead_link_node` (reformulates search query) without aborting.
  - `route_after_extraction`: If decision-maker not found on website, route to `social_dork_search_node`.
  - `route_after_verification`: If contact unverified, attempt fallback to authentic social profile; if none, drop lead and proceed to next organization.
  - `check_completion`: Loop until all target organizations are processed or quota reached.
- [x] **Task 6.3: State Graph Compilation & Checkpointing (`src/graph/lead_graph.py`)**
  - Compile the `StateGraph` with `MemorySaver` checkpointer for auditability, pause/resume, and replayability.

---

## Phase 7: Hands-Free Google Sheets & Local SQLite Sync
*(Targeting 15 Points: End-to-End Pipeline)*

### Objective
Automatically push clean, verified 6-field rows into Google Sheets and local SQLite without manual intervention.

#### Micro Elementary Tasks:
- [ ] **Task 7.1: Google Sheets Client (`src/storage/google_sheets.py`)**
  - Authenticate using Service Account credentials via `gspread`.
  - Create or open designated spreadsheet and worksheet.
  - Automatically format header row if new:
    `["Organization Name", "Category", "Location", "Contact Person", "Contact Channel", "Verification Status"]`
  - Style header: Bold text, dark background, frozen top row.
- [ ] **Task 7.2: Idempotent Batch Row Insertion**
  - Implement deduplication: Query existing rows in sheet to prevent duplicate organization names or emails.
  - Batch append rows in chunks of 10 to respect Google Sheets rate limits.
  - Color-code `Verification Status` column (Green for "Verified", Amber for "Pattern-Derived").
- [ ] **Task 7.3: Local SQLite Storage & Audit Trail (`src/storage/database.py`)**
  - Store full run logs, raw HTML snippets, MX test logs, and timestamps for audit verification and replay.

---

## Phase 8: FastAPI Backend & Real-Time Event Streaming

### Objective
Expose high-performance REST and Server-Sent Events (SSE) endpoints to drive the user interface.

#### Micro Elementary Tasks:
- [ ] **Task 8.1: API Server Setup (`src/api/app.py` & `src/api/routes.py`)**
  - Initialize FastAPI with CORS middleware.
  - Endpoint `POST /api/run`: Accepts multipart form (`search_prompt: str` or `brochure: UploadFile`). Returns `session_id`.
  - Endpoint `GET /api/stream/{session_id}`: Streams real-time LangGraph execution events via SSE.
  - Endpoint `GET /api/leads/{session_id}`: Returns JSON array of collected leads.
- [ ] **Task 8.2: SSE Event Streaming Generator (`src/api/stream.py`)**
  - Subscribe to LangGraph node events using `graph.astream_events()`.
  - Stream standardized SSE events: `node_start`, `log_message`, `lead_discovered`, `lead_verified`, `sheet_synced`, `error`.

---

## Phase 9: Modern Frontend Dashboard UI

### Objective
Build a modern, polished, responsive dashboard (Next.js/React + Tailwind CSS) providing live execution monitoring and instant Google Sheet links.

#### Micro Elementary Tasks:
- [ ] **Task 9.1: Next.js 14 App Shell & Design System Setup**
  - Setup Tailwind CSS with modern dark/light slate color tokens, Inter font, and JetBrains Mono for logs.
  - Install Lucide React icons and shadcn/ui components.
- [ ] **Task 9.2: Input Zone Component (`components/input-zone.tsx`)**
  - Create tabbed input:
    - Tab 1: Natural Language Prompt textarea with pre-built example chips (e.g., "Find FinTech Sponsors in Mumbai", "Robotics Societies in Delhi").
    - Tab 2: Drag-and-drop PDF dropzone with PDF preview and file size validation.
- [ ] **Task 9.3: Live Execution Visualizer & Terminal Feed (`components/live-agent-feed.tsx`)**
  - Render active node indicator (Searching $\to$ Crawling $\to$ Extracting $\to$ Verifying $\to$ Syncing).
  - Terminal-style streaming log viewer showing real-time decisions, dead link bypasses, and MX handshake results.
- [ ] **Task 9.4: The 6-Field Leads Table (`components/leads-table.tsx`)**
  - Render clean, data-dense table matching the exact 6 columns.
  - Distinct badge colors for `Category` (Sponsor: Teal, Delegation: Indigo) and `Verification Status` (Verified: Green, Pattern-Derived: Amber).
  - Prominent banner with direct clickable link: `"Open in Google Sheets"`.

---

## Phase 10: Verification, Testing & Benchmark Audit (100/100 Pts)

### Objective
Execute rigorous integration tests and benchmark runs to guarantee maximum score against the judging rubric.

#### Micro Elementary Tasks:
- [ ] **Task 10.1: Autonomy & Dead Link Stress Test (`tests/test_graph_flow.py`)**
  - Simulate dead URLs (404, 500, timeouts) in mock crawler; verify LangGraph catches errors, logs dead link, pivots to alternate queries, and completes run.
- [ ] **Task 10.2: Zero-Hallucination & Verification Audit (`tests/test_verifier.py`)**
  - Test verifier against:
    - Known invalid domains $\to$ must fail.
    - Generic inboxes (`info@`, `contact@`) $\to$ must be filtered out.
    - Catch-all domains $\to$ correctly tagged as "Pattern-Derived" or verified profile link.
- [ ] **Task 10.3: Brochure Parsing Benchmark (`tests/test_brochure_parser.py`)**
  - Run test against real multi-page conference brochure; verify extraction of sponsors, categories, and locations.
- [ ] **Task 10.4: End-to-End Hands-Free Verification Run**
  - Execute full prompt-to-sheet run. Confirm Google Sheet populates with zero manual intervention.
  - Document setup in `README.md` and record demo video walkthrough.
