# AI Prompt & Coding Guidelines (`Ai_Prompt_guidelines.md`)

This document defines the strict, non-negotiable engineering principles, coding standards, and agent prompt constraints that **any AI agent, developer, or code generator must follow** when implementing or modifying this codebase.

Violating these rules directly risks evaluation failure under the **100-Point Judging Criteria** (particularly the rule: *"Submissions are tested on fixed prompts plus a sample brochure. Output is checked against the six-field schema, verification is spot-checked, and any invented contact fails the run"*).

---

## 1. The Zero-Hallucination Mandate (Absolute Rule)

> **CORE LAW:** NEVER invent, synthesize, predict, or guess a contact person's name, email address, phone number, or social media handle. Any invented contact instantly fails the entire evaluation.

1. **Strict Source Grounding:**
   - Every contact entity (Name, Role, Email, Profile Link) must be extracted verbatim from an actual scraped webpage, DNS record, or verified search engine snippet.
   - You must store the `source_url` alongside every extracted field for auditability.
2. **The "Unverified $\to$ Discard" Protocol:**
   - If an email cannot be verified through SMTP validation or derived with high statistical confidence from confirmed domain patterns, **DO NOT output it**.
   - Instead, attempt to find and verify the person's authentic personal profile link (LinkedIn, Instagram, or official university directory).
   - If neither a verified email nor an authentic live profile link is discovered, **drop the lead candidate entirely**. Never output placeholder values like `"N/A"`, `"unknown@company.com"`, or `"pending"`.
3. **No LLM Email Guesses Without Deterministic Evidence:**
   - The LLM must NEVER be prompted with: *"Guess what John Doe's email at Acme might be."*
   - Email pattern derivation is permitted **ONLY IF** at least two other verified employee emails on the same domain are observed (e.g., observing `alice.smith@acme.com` and `bob.jones@acme.com` enables deriving `{first}.{last}@acme.com`). Even then, it must be marked as `"Pattern-Derived"`.

---

## 2. Strict Adherence to the 6-Field Output Schema

Every lead returned by the agent and synced to Google Sheets or the database must strictly match this exact schema:

```
+-------------------+-------------------------------------------------------------+
| Field Name        | Validation Rule / Permitted Values                          |
+-------------------+-------------------------------------------------------------+
| Organization Name | Clean company or collegiate society name (No legal suffixes)|
| Category          | MUST BE EXACTLY "Sponsor" OR "College Delegation"           |
| Location          | City (or City, Country)                                     |
| Contact Person    | Format: "[Full Name] - [Job Title]"                         |
| Contact Channel   | Valid deliverable email OR authentic profile URL           |
| Verification Status| MUST BE EXACTLY "Verified" OR "Pattern-Derived"             |
+-------------------+-------------------------------------------------------------+
```

### Prohibited Output Patterns:
- **NO Generic Roles:** Prohibited: `"Marketing Team"`, `"Student Council"`, `"Admin"`, `"HR Department"`.
- **NO Generic Central Inboxes:** Prohibited: `info@*`, `contact@*`, `support@*`, `hello@*`, `admin@*`, `sales@*`, `office@*`.
- **NO Unformatted Names:** Contact Person must always link the human being to their title (e.g., `"Sarah Connor - Head of Brand Partnerships"`, not just `"Sarah Connor"`).

---

## 3. LangGraph Architectural Standards

When writing nodes, edges, and graphs in LangGraph:

1. **State Immutability & Typed Reducers:**
   - Always define states using `TypedDict` or Pydantic models.
   - For lists that accumulate over time (e.g., `verified_leads`, `dead_urls`, `logs`), use `Annotated[List[T], operator.add]`.
   - Never mutate state objects in-place. Always return a dictionary containing only the specific state keys being modified or appended.
2. **No Infinite Cycles (Guaranteed Termination):**
   - Every loop or retry branch must be bounded by an explicit `retry_count` or queue size check in conditional edges.
   - Max crawl depth per domain: $\le 2$. Max page fetches per domain: $\le 5$. Max search query reformulations: $\le 3$.
3. **Graceful Dead-Link & Failure Handling:**
   - Web scraping will encounter HTTP 404, 403 (Cloudflare), 500, and network timeouts.
   - Nodes must wrap network calls in `try/except` blocks.
   - When a page fails or is blocked, the node must **NOT crash the graph**. Instead, emit a dead-page event, append the URL to `dead_urls`, and route to an alternative fallback node (e.g., LinkedIn search dorking).
4. **Clean Decoupling of Nodes:**
   - Keep node functions lean. Node functions should orchestrate; heavy business logic (e.g., SMTP socket handshakes, PDF layout parsing) must reside in dedicated modular classes in `src/`.

---

## 4. Web Scraping & Crawler Protocols

1. **Polite, Async-First Crawling:**
   - All network fetching must use `httpx.AsyncClient` with connection pooling.
   - Enforce request timeouts (default 10.0–15.0 seconds).
   - Implement exponential backoff for transient HTTP 429 (Too Many Requests) or 503 errors.
2. **Dynamic SPA Fallback:**
   - Static HTML parsing via `Trafilatura` is the default for performance.
   - Headless browser rendering (`Crawl4AI` / `Playwright`) must only be triggered when the page is detected as a Single Page Application (e.g., body text $< 100$ words and presence of client-side JS bundles).
3. **URL Normalization:**
   - Always normalize URLs: strip URL fragments (`#...`), tracking parameters (`?utm_*`), and standardize protocol (`https://`).

---

## 5. Contact Verification Standards

1. **Deliverability Proof:**
   - Never assume an email is valid merely because it passes regex syntax checks.
   - Always verify DNS MX records exist and are responsive.
   - Execute non-intrusive SMTP `RCPT TO` sequences asynchronously (`aiosmtplib`).
   - Probe for Catch-All mailboxes using a randomized nonexistent username.
2. **Social Profile Liveness Verification:**
   - Any profile link passed to `Contact Channel` must be verified using an asynchronous HTTP `HEAD` or `GET` request.
   - It must return an HTTP 200 status code and confirm that the profile is live, public, and not a deactivated account.

---

## 6. Python Code Quality & Typing Rules

1. **Python 3.11+ Standards:**
   - Use modern union syntax (`X | Y` instead of `Union[X, Y]`).
   - Use built-in generics (`list[str]`, `dict[str, Any]` instead of `typing.List`, `typing.Dict`).
2. **Strict Type Annotations:**
   - Every function, method, and endpoint parameter must have complete type hints.
   - Return types must be explicitly declared (including `-> None`).
3. **No Naked Print Statements:**
   - All logging must use standard Python `logging` or `loguru` with structured log levels (`logger.info`, `logger.warning`, `logger.error`).
   - Log messages must provide actionable context (e.g., `logger.warning(f"Dead link encountered: {url}. Initiating fallback search.")`).
4. **Pydantic v2 Compatibility:**
   - Use `model_validate`, `model_dump`, and `Field` with descriptive documentation.
   - Leverage `ConfigDict` instead of legacy inner `class Config`.

---

## 7. Zero Regression Testing Mandate

1. Any new feature or module must be accompanied by a corresponding unit test in `tests/`.
2. Network-dependent modules (SMTP, Google Sheets, Search APIs) must provide mocked test fixtures (`pytest-mock` / `unittest.mock`) so CI/CD pipelines can run reliably without network credentials.
3. Every test suite run must verify that the 6-field schema is preserved and that no placeholder data escapes to the storage layer.
