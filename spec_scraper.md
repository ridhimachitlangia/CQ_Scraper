# Technical Specification Sheet: Complex Modules (`spec_scraper.md`)

This document provides exhaustive technical specifications for the core, complex modules of the **Autonomous Lead Discovery & Verification Agent**. Every module details its exact responsibility, interface signatures (inputs and outputs), algorithmic pipeline, and failure/edge case mitigations.

---

## Module 1: `src/parsers/brochure_parser.py`
### Purpose
Extract structured event context, prospecting categories, past sponsor logos/mentions, and target collegiate delegation sectors from uploaded multi-page PDF event brochures or graphic posters.

### Inputs
- `pdf_source`: `Union[str, Path, bytes]` — Filepath or binary buffer of the uploaded PDF brochure.
- `max_pages`: `int = 10` — Upper limit for page analysis to manage compute and token efficiency.

### Outputs
- `BrochureContext` (Pydantic Model):
  ```python
  class BrochureContext(BaseModel):
      event_name: str
      event_edition: Optional[str]
      event_theme_summary: str
      event_location: str
      target_categories: List[str]  # e.g., ["Sponsor", "College Delegation"]
      past_sponsors_found: List[str]  # e.g., ["Red Bull", "GitHub", "AWS"]
      target_industries: List[str]   # e.g., ["Fintech", "Developer Tools", "Energy Drinks"]
      target_societies: List[str]    # e.g., ["Coding Club", "Robotics Society", "E-Cell"]
      seed_search_queries: List[str]
  ```

### Algorithmic Flow
1. **Digital Text Extraction:** Open PDF using PyMuPDF (`fitz`). Extract clean text blocks and font size metadata.
2. **Layout & Table Inspection:** Use `pdfplumber` to extract sponsorship tier tables ("Platinum", "Gold", "Silver", "Delegate Fees").
3. **Vision / OCR Fallback:**
   - Heuristic check: If extracted text length across all pages $< 150$ characters, the brochure is identified as a raster image/scanned poster.
   - Render pages to high-DPI PNGs (`pdf2image`).
   - Invoke Vision LLM (`gpt-4o` with multimodal image prompt) to transcribe visual text, logo emblems, and tier badges.
4. **Structured Entity Synthesis:** Pass consolidated text to an LLM using Pydantic structured output (`response_format=BrochureContext`).

### Edge Cases & Mitigations
| Edge Case | Failure Mode | Mitigation Strategy |
| :--- | :--- | :--- |
| **Raster-Only Scanned PDF** | PyMuPDF returns empty text string. | Fallback trigger: Auto-detect empty text; render page 1–3 to images and run Multimodal Vision OCR. |
| **Password-Protected PDF** | `fitz.FileDataError` exception. | Catch exception immediately; return clear structured error to UI: "PDF is password-encrypted." |
| **Huge Multi-hundred Page PDF** | OOM or high LLM token costs. | Process only the first 6 pages and the last 2 pages (where sponsors and organizing societies are invariably listed). |
| **Sponsorship Deck with Complex Graphics** | Text order scrambled across columns. | Use `pdfplumber` layout-aware word extraction (`extract_words(keep_blank_chars=False)`) sorted by vertical coordinate $y_0$. |

---

## Module 2: `src/crawler/deep_crawler.py`
### Purpose
Autonomously crawl corporate websites, collegiate society pages, and directory listings. Navigates deeply into high-intent subpages (`/team`, `/about`, `/contact`, `/council`), handles dead pages gracefully, and extracts clean markdown.

### Inputs
- `base_url`: `str` — Root or seed URL of the target organization.
- `max_depth`: `int = 2` — Maximum link traversal depth from seed.
- `page_limit`: `int = 5` — Maximum pages to scrape per organization.
- `timeout_seconds`: `float = 12.0` — HTTP socket timeout.

### Outputs
- `CrawlResult` (Pydantic Model):
  ```python
  class CrawledPage(BaseModel):
      url: str
      status_code: int
      title: str
      markdown_content: str
      extracted_internal_links: List[str]
      discovered_emails: List[str]
      discovered_social_links: List[str]
      is_dead: bool = False

  class CrawlResult(BaseModel):
      organization_name: str
      pages: List[CrawledPage]
      dead_urls_encountered: List[str]
      total_pages_crawled: int
  ```

### Algorithmic Flow
1. **Seed Request:** Make asynchronous `httpx.AsyncClient.get()` request to `base_url` with randomized desktop User-Agent and referer headers.
2. **Dead Page & Error Detection:**
   - If response status is $\ge 400$, timeout occurs, or DNS fails: Mark URL as `is_dead=True`, record in `dead_urls_encountered`, and trigger dead-link recovery branch.
3. **DOM Content Extraction:**
   - Static DOM: Run `trafilatura.extract(include_links=True, include_comments=False)` for high-precision content.
   - Dynamic SPA Detection: If raw HTML contains `<div id="app"></div>` or `<div id="__next"></div>` with empty body text, spawn headless browser via `Crawl4AI` / `Playwright` to execute JavaScript and harvest rendered DOM.
4. **Link Discovery & Scoring (`link_prioritizer.py`):**
   - Parse all `<a href>` elements. Convert relative URLs to absolute.
   - Filter to internal domain links.
   - Score URLs: High priority for `/team`, `/about`, `/leadership`, `/executives`, `/council`, `/sponsors`, `/contact`.
5. **Queue Traversal:** Fetch top-ranked candidate subpages up to `page_limit`.

### Edge Cases & Mitigations
| Edge Case | Failure Mode | Mitigation Strategy |
| :--- | :--- | :--- |
| **Dead / 404 / 500 Links** | Pipeline halts or hangs on broken URL. | Wrap requests in `try/except (httpx.HTTPError, httpx.TimeoutException)`. On failure, append to `dead_urls`, yield clean `is_dead` page, and continue to next link. |
| **Cloudflare / Bot-Block (403/503)** | Scraping blocked by CDN WAF. | Detect challenge headers. Fallback immediately to search engine snippet extraction and public LinkedIn Dorking rather than stalling. |
| **Infinite Spider Trap** | Recursive calendar or pagination links. | Strict domain whitelist, URL normalization (strip query parameters/hashes), and a visited URLs set (`Set[str]`). |
| **Single Page Apps (React/Vue)** | Static GET returns empty template. | Automated switch to `Crawl4AI` headless browser when extracted body text $< 100$ words. |

---

## Module 3: `src/extractors/decision_maker.py`
### Purpose
Extract the specific human decision-maker (Full Name and Role) from crawled content or search dorks, completely rejecting generic central inboxes (`info@`, `contact@`, `admin@`).

### Inputs
- `org_name`: `str` — Name of the target organization.
- `category`: `Literal["Sponsor", "College Delegation"]`
- `crawled_markdown`: `str` — Aggregated markdown content from crawled pages.
- `search_snippets`: `List[str]` — Supplemental search dork snippets from Google/Tavily.

### Outputs
- `DecisionMakerResult` (Pydantic Model):
  ```python
  class DecisionMakerResult(BaseModel):
      name: str = Field(..., description="Full personal name of the individual")
      role: str = Field(..., description="Specific official title or leadership position")
      direct_email: Optional[str] = Field(None, description="Direct personal email if found")
      profile_link: Optional[str] = Field(None, description="Personal LinkedIn, Instagram, or faculty profile")
      confidence_score: float = Field(..., ge=0.0, le=1.0)
      source_url: str = Field(..., description="URL where decision-maker was grounded")
      rationale: str
  ```

### Algorithmic Flow
1. **Pre-Filter Regex & Invalidation:**
   - Scan crawled text for all email addresses.
   - Hard-blacklist generic prefixes: `^(info|contact|support|help|sales|hello|enquiry|office|admin|careers|press|media|billing)@.*$`.
   - Any generic address is excluded from decision-maker candidates.
2. **Contextual Role Hierarchy:**
   - For **Sponsor**: Prioritize `["Chief Marketing Officer", "VP Marketing", "Head of Brand Partnerships", "CSR Lead", "Sponsorship Director", "Founder", "Managing Director"]`.
   - For **College Delegation**: Prioritize `["President", "Vice President", "Convenor", "General Secretary", "Faculty Advisor", "Secretary General"]`.
3. **Structured LLM Extraction (`ChatOpenAI(model="gpt-4o", temperature=0.0)`):**
   - Feed prioritized markdown and Dork snippets with prompt enforcing:
     - Name must belong to a natural person (e.g., "Sarah Connor", not "Acme Marketing Team").
     - Grounding check: Name and role MUST be cited verbatim from the source snippet. No hypothetical personas.
4. **Fallback Dork Trigger:** If no individual is found in crawled text, generate targeted persona search query:
   `f'"{org_name}" ("VP Marketing" OR "Head of Marketing" OR "CSR Head" OR "President") site:linkedin.com/in'` and execute targeted retrieval.

### Edge Cases & Mitigations
| Edge Case | Failure Mode | Mitigation Strategy |
| :--- | :--- | :--- |
| **Only Generic Inbox Available (`info@acme.com`)** | Agent tempted to return generic inbox. | Strict Pydantic validator: If extracted email matches generic regex, set `direct_email = None` and force agent to populate `profile_link` with the decision-maker's LinkedIn or Instagram profile. |
| **Former / Outdated Officer Listed** | Extracting an executive who graduated or left. | Extract year indicators (e.g., "Tenure 2023-24"). Prompt LLM to prefer current council (2024-2025/2026) or latest press releases. |
| **Multiple Co-Founders / Heads** | Ambiguity over who to select. | Tie-break policy: Select the role closest to Sponsorship/Finances (e.g., VP Brand > VP Technology; President > Secretary). |
| **Company Page Has No Names (Stealth/Corporate)** | Zero names on corporate website. | Autonomous pivot: Trigger Serper search query specifically dorking LinkedIn public directory profiles for that organization. |

---

## Module 4: `src/verifier/contact_verifier.py`
### Purpose
Execute multi-tier validation on discovered emails and social links. Guarantees that every contact is real, deliverable, and non-hallucinated. Enforces the strict `"Verified"` or `"Pattern-Derived"` classification.

### Inputs
- `email_candidate`: `Optional[str]`
- `profile_url_candidate`: `Optional[str]`
- `decision_maker_name`: `str`
- `domain_email_samples`: `List[str]` — Other emails found on the same corporate/college domain to detect naming patterns.

### Outputs
- `VerificationResult` (Pydantic Model):
  ```python
  class VerificationResult(BaseModel):
      contact_channel: str = Field(..., description="Final verified email or profile link")
      status: Literal["Verified", "Pattern-Derived"]
      is_deliverable: bool
      verification_method: str  # e.g., "SMTP_HANDSHAKE", "DNS_MX_ONLY", "HTTP_PROFILE_200", "PATTERN_MATCH"
      logs: List[str]
  ```

### Algorithmic Flow
```
                      [Contact Candidate Input]
                                  |
                +-----------------+-----------------+
                |                                   |
         [Email Provided]                  [Profile URL Provided]
                |                                   |
        (1) RFC Syntax Validation          (1) Domain Whitelist Check
                |                                   |
        (2) DNS MX Record Lookup           (2) Async HTTP HEAD/GET
                |                                   |
        (3) Non-Intrusive SMTP Handshake   (3) Status == 200 OK?
          - HELO / MAIL FROM / RCPT TO              |
          - Catch-All Probe Address                 v
                |                             [Profile Verified]
        +-------+-------+
        |               |
 [Direct 250 OK]  [Catch-All / 550]
        |               |
   "Verified"     [Pattern Derivation Test]
                        |
            +-----------+-----------+
            |                       |
      [Pattern Valid]         [Pattern Fails]
            |                       |
     "Pattern-Derived"       [Discard Email]
                                    |
                           [Fallback to Profile URL]
```

1. **Email Deliverability Verification Steps:**
   - **Step A: RFC Syntax & TLD Check:** Validate using `email-validator`.
   - **Step B: Asynchronous DNS MX Lookup:** Use `dns.asyncresolver.Resolver()` to query MX records. Sort by preference. If no MX records exist, drop email.
   - **Step C: Non-Intrusive SMTP Socket Handshake (`aiosmtplib`):**
     - Open TLS/STARTTLS connection to top MX host on port 25.
     - Send `HELO verify.leads-agent.com`.
     - Send `MAIL FROM:<check@verify.leads-agent.com>`.
     - Send `RCPT TO:<email_candidate>`. Read response code.
     - **Crucial:** Immediately send `RSET` and `QUIT`. Never send `DATA`. No actual email is transmitted.
   - **Step D: Catch-All Testing:**
     - In the same session or immediately after, send `RCPT TO:<random_hex_32_chars@domain.com>`.
     - If the mail server responds with `250 OK` for the random address, the domain is a **Catch-All**.
     - If Catch-All: Mark status as `"Pattern-Derived"` (if derived from verified domain format) rather than `"Verified"`, avoiding false confidence.
     - If Non-Catch-All and returns `250 OK`: Mark status as `"Verified"`.
     - If returns `550`, `551`, or `553`: Email is dead/invalid. Discard immediately.
2. **Social Profile URL Verification Steps:**
   - If email fails or is missing, test `profile_url_candidate`.
   - Execute asynchronous `httpx.AsyncClient.head(url, follow_redirects=True, timeout=8.0)`.
   - If status code is `200` and target URL contains valid username/slug: Mark channel as `profile_url_candidate` with status `"Verified"`.

### Edge Cases & Mitigations
| Edge Case | Failure Mode | Mitigation Strategy |
| :--- | :--- | :--- |
| **Port 25 Blocked by ISP/Host** | Socket connection to mail server hangs or is blocked. | Implement fallback to DNS MX existence + Pattern Derivation scoring. Log diagnostic warning. |
| **Greylisting (SMTP Code 451/421)** | Server temporarily rejects unknown IP. | Treat as transient; attempt retry after 2s. If persistent, verify via MX presence + known domain corporate pattern. |
| **Catch-All Mail Server** | Server accepts all emails (`250 OK`) even fake ones. | Catch-All probe with randomized UUID. If server accepts fake UUID, downgrade status to `"Pattern-Derived"` and flag for secondary confirmation. |
| **Dead / 404 LinkedIn Link** | Profile link points to deleted or private profile. | Validate with HTTP request. If 404 or redirected to generic login/error page without profile identity, discard URL. |
| **Hallucinated Email from LLM** | LLM invents plausible email that bounces. | Zero-Hallucination Gate: The verifier executes real socket/MX checks. Any email that returns SMTP 550 is dropped with zero tolerance. |

---

## Module 5: `src/graph/lead_graph.py`
### Purpose
The master LangGraph cyclical state machine. Orchestrates data flow across parsers, search engines, crawlers, extractors, verifiers, and the Google Sheets sync node. Enforces self-healing loops when encountering dead links or unverified contacts.

### Inputs
- Initial `AgentState` containing:
  - `search_prompt: Optional[str]`
  - `brochure_path: Optional[str]`
  - `category_focus: Optional[str]`
  - `max_target_count: int = 15`

### Outputs
- Final `AgentState` containing:
  - `verified_leads: List[FinalLeadRecord]` (Formatted to 6 fields)
  - `dead_urls: List[str]`
  - `audit_log: List[Dict[str, Any]]`
  - `google_sheet_url: str`

### Node Registry & State Responsibilities
```
1. `parse_input_node`: Deconstructs brochure PDF or search prompt into target entity seeds.
2. `expand_targets_node`: Generates search queries for target sponsors and student bodies.
3. `search_web_node`: Executes search requests; populates candidate URL pool.
4. `crawl_pages_node`: Traverses websites; handles dead links; extracts markdown.
5. `extract_decision_maker_node`: Extracts name, role, email/profile candidate.
6. `verify_contact_node`: Executes SMTP and social verification pipeline.
7. `dead_link_recovery_node`: Reformulates queries when pages return 404/500/blocked.
8. `sync_sheet_node`: Writes validated records directly into Google Sheets and SQLite DB.
```

### Conditional Edge Rules
- **Edge 1 (`route_crawl_result`):**
  - If page is dead or blocked $\to$ Route to `dead_link_recovery_node`.
  - If page is valid $\to$ Route to `extract_decision_maker_node`.
- **Edge 2 (`route_verification_result`):**
  - If lead contact is deliverable (`Verified` or `Pattern-Derived`) $\to$ Route to `accumulate_lead`.
  - If contact unverified AND retry count $< 2$ $\to$ Route to `search_web_node` (pivot to LinkedIn query).
  - Else $\to$ Discard and advance to next target organization.
- **Edge 3 (`route_queue_completion`):**
  - If more organizations remain in queue $\to$ Loop back to `search_web_node`.
  - If all organizations processed $\to$ Route to `sync_sheet_node` $\to$ `END`.

---

## Module 6: `src/storage/google_sheets.py`
### Purpose
Automate the creation, formatting, deduplication, and batch-population of the Google Sheet with the required 6-column schema.

### Inputs
- `records`: `List[FinalLeadRecord]` — Verified lead objects.
- `spreadsheet_id`: `Optional[str]` — Existing Google Sheet ID or None (to create new).
- `sheet_title`: `str = "Autonomous Event Leads - CQ Scraper"`

### Outputs
- `spreadsheet_url`: `str` — Publicly viewable/editable Google Sheet URL.
- `rows_written`: `int` — Count of unique rows appended.

### Algorithmic Flow
1. **Authentication:** Authenticate via Google Service Account credentials (`gspread.service_account()`).
2. **Spreadsheet Initialization:**
   - If ID provided, open existing sheet; otherwise, create a new spreadsheet.
   - Set sharing permissions: Make readable/editable by anyone with the link or share with user's email.
3. **Schema Header Enforcement:**
   - Ensure Row 1 strictly contains:
     `["Organization Name", "Category", "Location", "Contact Person", "Contact Channel", "Verification Status"]`
   - Apply styling: Navy blue background `#1E293B`, white bold text, frozen top row.
4. **Idempotency & Duplicate Elimination:**
   - Fetch existing column values (`Organization Name` and `Contact Channel`).
   - Filter out any incoming record whose organization name or contact channel already exists in the sheet.
5. **Batch Ingestion:**
   - Append records in a single batch call (`worksheet.append_rows(values, value_input_option='USER_ENTERED')`).
6. **Status Color Rules:**
   - Apply conditional formatting: Light green fill for `"Verified"` cells, light yellow/amber fill for `"Pattern-Derived"` cells.
