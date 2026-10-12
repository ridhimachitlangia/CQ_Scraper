# UI/UX Design System & Anti-Sloppiness Guidelines (`Design.md`)

This document defines the comprehensive design system, visual language, typographic rules, color palette, component specifications, and anti-sloppiness standards for the **Autonomous Lead Discovery & Verification Agent** web application.

Following these specifications ensures the dashboard feels like a high-craft, tier-1 SaaS product (comparable to Linear, Vercel, Supabase, and Raycast) rather than an unpolished developer prototype.

---

## 1. Design Philosophy & Visual Aesthetic

- **Theme Baseline:** Refined Dark Mode First. High contrast, deep slate/obsidian foundations with luminous accent highlights.
- **Craft Philosophy:**
  - High information density without visual clutter.
  - Clear visual hierarchy with distinct elevation levels.
  - Live feedback for every background agent action (crawling, verifying, dead-link recovery).
  - Pixel-perfect typography and intentional micro-interactions.

---

## 2. Color Palette & Semantic Tokens

All colors are defined using modern CSS variables / Tailwind tokens:

### 2.1 Base Neutrals & Surfaces
| Token Name | HEX | Tailwind Class | Usage |
| :--- | :--- | :--- | :--- |
| **Canvas Background** | `#080B11` | `bg-[#080B11]` | Main page backdrop (deep space obsidian). |
| **Card Surface (Level 1)** | `#0F172A` | `bg-slate-900` | Primary cards, panels, and input containers. |
| **Card Surface (Level 2)** | `#1E293B` | `bg-slate-800` | Sub-panels, table headers, hovered rows. |
| **Card Surface (Level 3)** | `#334155` | `bg-slate-700` | Popovers, dropdown menus, modal dialogs. |
| **Border Subtle** | `#1E293B` | `border-slate-800` | Card borders, table dividers. |
| **Border Active / Focus** | `#3B82F6` | `border-blue-500` | Focused inputs, active tab rings. |

### 2.2 Typography Colors
| Token Name | HEX | Tailwind Class | Contrast / Usage |
| :--- | :--- | :--- | :--- |
| **Text Primary** | `#F8FAFC` | `text-slate-50` | Headings, lead names, critical values ($15:1$ contrast). |
| **Text Secondary** | `#94A3B8` | `text-slate-400` | Body copy, table cells, secondary metadata. |
| **Text Muted / Subdued**| `#64748B` | `text-slate-500` | Helper text, timestamps, input placeholders. |

### 2.3 Semantic Brand & Status Accents
| State / Entity | Background (10% tint) | Border (30% tint) | Text & Icon (Solid) | Hex Code |
| :--- | :--- | :--- | :--- | :--- |
| **Primary Brand / Action** | `bg-indigo-500/10` | `border-indigo-500/30` | `text-indigo-400` | `#6366F1` |
| **Category: Sponsor** | `bg-teal-500/10` | `border-teal-500/30` | `text-teal-400` | `#14B8A6` |
| **Category: College Del.** | `bg-violet-500/10` | `border-violet-500/30` | `text-violet-400` | `#8B5CF6` |
| **Status: Verified** | `bg-emerald-500/10` | `border-emerald-500/30` | `text-emerald-400` | `#10B981` |
| **Status: Pattern-Derived**| `bg-amber-500/10` | `border-amber-500/30` | `text-amber-400` | `#F59E0B` |
| **Dead Link / Failed** | `bg-rose-500/10` | `border-rose-500/30` | `text-rose-400` | `#F43F5E` |

---

## 3. Typography System

The application uses a dual-font strategy: **Inter** or **Plus Jakarta Sans** for interface controls and tabular data, and **JetBrains Mono** for all system logs, emails, URLs, and code snippets.

```
Font Pairings:
UI & Headings:  Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif
Technical Data: "JetBrains Mono", "Fira Code", monospace
```

### Type Scale & Hierarchy
| Level | Font Size | Line Height | Weight | Letter Spacing | Font Family |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Display Heading** | `32px` (`text-3xl`) | `38px` | `700` (Bold) | `-0.025em` | UI Sans |
| **Section Heading** | `20px` (`text-xl`) | `28px` | `600` (Semibold) | `-0.02em` | UI Sans |
| **Card Header** | `16px` (`text-base`)| `24px` | `600` (Semibold) | `-0.01em` | UI Sans |
| **Body Regular** | `14px` (`text-sm`) | `20px` | `400` (Regular) | `0em` | UI Sans |
| **Body Medium** | `14px` (`text-sm`) | `20px` | `500` (Medium) | `0em` | UI Sans |
| **Caption / Badge** | `12px` (`text-xs`) | `16px` | `500` (Medium) | `+0.01em` | UI Sans |
| **Terminal Log** | `13px` (`text-[13px]`)| `20px` | `400` (Regular) | `0em` | JetBrains Mono |
| **Email / URL Data**| `13px` (`text-[13px]`)| `18px` | `500` (Medium) | `0em` | JetBrains Mono |

---

## 4. Layout Grid, Spacing & Container Architecture

### 4.1 Spatial Grid
- Base unit: **4px / 8px** spacing scale (`p-1`, `p-2`, `p-4`, `p-6`, `p-8`).
- Maximum page container width: `1440px` (`max-w-7xl mx-auto px-4 sm:px-6 lg:px-8`).

### 4.2 Application Page Architecture

```
+-----------------------------------------------------------------------------------------------+
| TOP NAVBAR: Logo | Active Session Status Pill | Live Google Sheet Link CTA | API Health Badge |
+-----------------------------------------------------------------------------------------------+
| HERO CONTROL PANEL (Max-w-5xl):                                                               |
|   +-----------------------------------------------------------------------------------------+ |
|   | [Tab 1: Natural Language Prompt]   |   [Tab 2: Drag & Drop Event Brochure (PDF)]         | |
|   +-----------------------------------------------------------------------------------------+ |
|   | Input Textarea / Interactive PDF Dropzone                                                | |
|   | Quick Chips: ["Fintech Sponsors Bangalore", "Robotics Societies Delhi", "EDC Sponsors"]  | |
|   | [Action Button: "Start Autonomous Discovery & Extraction" (Shimmer Gradient)]            | |
|   +-----------------------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------------------+
| METRICS BAR: Total Scraped | Verified Leads | Pattern-Derived Leads | Dead Links Handled      |
+-----------------------------------------------------------------------------------------------+
| SPLIT EXECUTION MONITOR:                                                                      |
| +-----------------------------------------------+-------------------------------------------+ |
| | LIVE AGENT PIPELINE STATUS                    | REAL-TIME EXECUTION LOGS                  | |
| | (Stepper: Parse -> Search -> Crawl -> Verify) | (JetBrains Mono terminal with auto-scroll)| |
| +-----------------------------------------------+-------------------------------------------+ |
+-----------------------------------------------------------------------------------------------+
| THE 6-FIELD MASTER LEADS TABLE:                                                               |
| [Search filter] [Category Filter: All/Sponsors/Delegations] [Status Filter] [Export to Sheet] |
| +-------------------------------------------------------------------------------------------+ |
| | Organization | Category | Location | Contact Person | Contact Channel | Status            | |
| |--------------|----------|----------|----------------|-----------------|-------------------| |
| | Acme FinTech | Sponsor  | Mumbai   | A. Sen - VP Mkt| a.sen@acme.com  | [VERIFIED]        | |
| +-------------------------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------------------+
```

---

## 5. UI Component Specifications

### 5.1 The Brochure Upload Dropzone
- **Visual Design:** Dashed border (`border-2 border-dashed border-slate-700 hover:border-indigo-500/60`).
- **Surface:** Subtle radial gradient (`bg-gradient-to-b from-slate-900 to-slate-950`).
- **Dropzone States:**
  - *Default:* Cloud upload icon, "Drop event brochure PDF here or browse", helper text: "PDF files up to 25MB".
  - *Drag Active:* Border transitions to glowing Indigo (`ring-4 ring-indigo-500/20`), text highlights.
  - *File Loaded:* Renders mini PDF document badge with filename, page count, and clear ("x") button.

### 5.2 Live Agent Pipeline Stepper
- 5 Visual States: `1. Brochure / Prompt Analysis` $\to$ `2. Entity Discovery` $\to$ `3. Deep Web Crawling` $\to$ `4. Contact Verification` $\to$ `5. Sheet Sync`.
- **Active State:** Glowing animated pulse pill (`animate-pulse text-indigo-400 bg-indigo-500/10 ring-1 ring-indigo-500/30`).
- **Completed State:** Check icon in emerald green circle.
- **Dead-Page Recovery Event:** Renders subtle amber badge: *"Dead page handled (404) $\to$ Pivoting to LinkedIn Dork"*.

### 5.3 Live Terminal Log Feed
- **Container:** Dark terminal background (`bg-[#05080E] border border-slate-800/80 rounded-xl`).
- **Header:** Three subtle Mac-style window dots (Red, Yellow, Green) + "Agent Activity Stream" label + "Auto-scroll: ON" toggle.
- **Content:** Font `JetBrains Mono`, text size `13px`.
- **Syntax Highlighting:**
  - Timestamps: `text-slate-500`
  - Targets: `text-blue-400`
  - Crawl actions: `text-slate-300`
  - Dead links: `text-rose-400`
  - Verification results: `text-emerald-400`

### 5.4 The 6-Field Master Leads Table
- **Header:** Sticky table header (`sticky top-0 bg-slate-900/95 backdrop-blur border-b border-slate-800`).
- **Row Styling:** Alternating subtle row backgrounds (`hover:bg-slate-800/50 transition-colors`).
- **Badges:**
  - **Category Pill:**
    - Sponsor: `bg-teal-500/10 text-teal-400 border border-teal-500/20 rounded-md px-2.5 py-0.5 text-xs font-medium`
    - College Delegation: `bg-violet-500/10 text-violet-400 border border-violet-500/20 rounded-md px-2.5 py-0.5 text-xs font-medium`
  - **Verification Status Pill:**
    - Verified: `bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-md px-2.5 py-0.5 text-xs font-medium flex items-center gap-1.5` (Includes checkmark icon).
    - Pattern-Derived: `bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-md px-2.5 py-0.5 text-xs font-medium flex items-center gap-1.5` (Includes spark/formula icon).
  - **Contact Channel:**
    - Email: Rendered in monospace with a one-click copy button (`hover:text-indigo-400`).
    - Profile Link: External link icon, opens in new tab with `rel="noopener noreferrer"`.

---

## 6. The "Anti-Sloppiness" Checklist & Rules

To ensure the web app never appears unpolished, sloppy, or amateurish, the following rules must be strictly implemented in code:

### ❌ What Looks Sloppy & Must Be Prevented:
1. **Raw JSON Dumps:** Never display `{ "error": 404, "raw": ... }` to the user. Always render structured cards, formatted alerts, or clean terminal log lines.
2. **Text Overflow & Unformatted URLs:** Long emails or URLs wrapping awkwardly and breaking table layout.
   - *Fix:* Enforce `truncate max-w-[220px]` with a hover tooltip showing the full address and a copy-to-clipboard button.
3. **Horizontal Page Scrollbars:** Accidental `w-screen` or negative margins causing unwanted horizontal page scrolling.
   - *Fix:* Enforce `max-w-full overflow-x-hidden` on the parent layout container; only table components are granted internal `overflow-x-auto`.
4. **Generic Loading Spinners Without Context:** A lonely spinner in the center of a blank white/black screen.
   - *Fix:* Use skeleton loaders mimicking the exact card/table structure + contextual status messages (*"Parsing brochure pages 1–4..."*, *"Checking MX records for acme.com..."*).
5. **Missing Empty States:** An empty table with just column headers looking broken.
   - *Fix:* Provide an illustrated empty state: *"No leads discovered yet. Upload an event brochure or enter a search query above to begin."*
6. **Harsh Hard-Edge Borders:** Thick, 100% opaque borders making the UI look dated.
   - *Fix:* Use low-opacity border tokens (`border-slate-800` or `border-white/10`).
7. **Inconsistent Spacing & Button Heights:** Buttons having mismatched heights (38px vs 42px).
   - *Fix:* Standardize on strict height tokens (`h-9` for compact, `h-10` for standard, `h-12` for hero CTA).
8. **Unresponsive Tables on Mobile/Tablet:**
   - *Fix:* The table must have horizontal scroll support with sticky column headers and a visual scroll shadow indicator.
