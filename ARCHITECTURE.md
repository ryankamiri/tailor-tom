# TailorTom LLM Optimization Architecture

## Overview

TailorTom uses a **compile-and-feedback loop** architecture where the LLM optimizes a resume, the result is compiled to PDF, analyzed for quality issues, and the LLM gets feedback to refine its output in subsequent iterations.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    INITIALIZATION PHASE                          │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────┐
        │  Compile Original Resume        │
        │  (to get initial layout info)   │
        └─────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────┐
        │  Analyze Layout (Detail Level 2)│
        │  - Page count                   │
        │  - Content boundaries           │
        │  - Section breakdown            │
        └─────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ITERATIVE OPTIMIZATION LOOP                   │
│                    (Max 5 iterations)                            │
└─────────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
        ▼                                   ▼
┌──────────────────┐              ┌──────────────────┐
│  LLM CALL        │              │  INPUT TO LLM:   │
│  (DSPy)          │◄─────────────┤  - resume_latex  │
│                  │              │  - job_desc      │
│  OptimizeResume  │              │  - layout_analysis│
│  Signature       │              │  - target_pages  │
└──────────────────┘              └──────────────────┘
        │
        ▼
┌──────────────────┐
│  OUTPUT:         │
│  optimized_latex │
└──────────────────┘
        │
        ▼
┌──────────────────┐
│  Fix LaTeX       │
│  Issues          │
│  (auto-repair)   │
└──────────────────┘
        │
        ▼
┌──────────────────┐
│  Compile to PDF  │
└──────────────────┘
        │
        ▼
┌──────────────────┐
│  Quality Gate    │
│  Check:          │
│  - Page count ≤ target│
│  - No overflow   │
│  - Bullets ≤ 3 lines│
└──────────────────┘
        │
        ├─► ALL PASS? ──YES──► RETURN SUCCESS
        │
        NO
        │
        ▼
┌──────────────────┐
│  Analyze Layout  │
│  (Progressive)   │
│  Detail Level:   │
│  - Iter 1: Basic │
│  - Iter 2: + Sections│
│  - Iter 3+: Full │
└──────────────────┘
        │
        ▼
┌──────────────────┐
│  Format Feedback │
│  (for LLM)       │
│  - Page status   │
│  - Overflow issues│
│  - Long bullets  │
│  - Whitespace %  │
│  - Section metrics│
└──────────────────┘
        │
        └─► FEEDBACK LOOP (back to LLM call)
```

## Components

### 1. **OptimizeResume Signature (DSPy)**

This is the LLM interface definition. It specifies:
- **Inputs:**
  - `resume_latex`: Current LaTeX resume
  - `job_description`: Job description to optimize for
  - `layout_analysis`: Formatted feedback string about layout issues
  - `target_pages`: Maximum allowed pages (usually 1)

- **Output:**
  - `optimized_latex`: Optimized resume with keywords integrated

- **Prompt Rules:**
  - **KEYWORD INTEGRATION - BE AGGRESSIVE**: Actively rephrase to include keywords
  - **PRESERVE CONTENT**: Keep all bullets, skills, sections
  - **PRESERVE LENGTH**: Most important - must stay same length
  - **NO HALLUCINATION**: Only rephrase, never invent
  - **LAYOUT FIXES**: Fix overflow/long bullets if mentioned in layout_analysis
  - **FORMATTING**: Preserve LaTeX structure

### 2. **ResumeOptimizerPipeline**

The main orchestrator that manages the iterative loop.

**Initialization:**
1. Compiles original resume to PDF
2. Analyzes initial layout (detail level 2 - includes sections)
3. Stores original page count for comparison

**Iteration Loop (max 5 iterations):**

**Step 1: LLM Call**
- Calls `self.optimizer` (DSPy ChainOfThought wrapper around OptimizeResume)
- Passes: current LaTeX, job description, layout_analysis, target_pages
- Receives: optimized LaTeX

**Step 2: LaTeX Repair**
- Runs `_fix_latex_issues()` to fix common LLM errors:
  - Escapes special characters (`|`, `&`)
  - Fixes incomplete commands (`\textbf{` → `\textbf{text}`)
  - Fixes incomplete environments (adds missing `\end{}` tags)
  - Balances braces

**Step 3: Compile to PDF**
- Compiles LaTeX to PDF using `pdflatex`
- If compilation fails, attempts to fix and retry (up to 3 times)
- If still fails, reverts to last valid version

**Step 4: Quality Gate**
- Runs `check_quality()` which checks:
  - ✅ Page count ≤ target_pages
  - ✅ No text overflow (text beyond margins)
  - ✅ No bullets > max_bullet_lines (default 3)
- If ALL pass → **SUCCESS, return result**
- If ANY fail → Continue to feedback generation

**Step 5: Generate Feedback (if quality issues)**
- Determines detail level based on iteration:
  - Iteration 1: Detail level 1 (basic - line counts, overflow)
  - Iteration 2: Detail level 2 (adds section metrics)
  - Iteration 3+: Detail level 3 (full - adds spacing analysis)
- Calls `analyze_layout()` to extract metrics from PDF
- Calls `format_layout_feedback()` to format for LLM
- **Special case**: If page count increased, prepends aggressive condensation instructions
- Feedback becomes the `layout_analysis` for next iteration

**Step 6: Loop**
- Uses the feedback as `layout_analysis` input for next LLM call
- Repeats until all quality criteria pass or max iterations reached

### 3. **Layout Analysis System**

**extract_line_metrics():**
- Analyzes PDF to find bullet points
- Counts lines per bullet
- Tracks last line right edge (for whitespace utilization)

**detect_overflow():**
- Finds text extending beyond page margins
- Returns list of overflow issues with positions

**analyze_section_layout():**
- Groups text by sections
- Calculates lines per section, % of page used
- Used in detail level 2+

**analyze_spacing():**
- Measures gaps between sections and bullets
- Used in detail level 3+

**format_layout_feedback():**
- Formats all analysis into human-readable string for LLM
- Structure:
  ```
  LAYOUT ANALYSIS:
  
  Page Status: X page(s) - FITS/OVER target
  
  Instructions: [what to do]
  
  Bullet Length: [status or issues]
  
  Overflow Status: [no overflow or specific issues with percentages]
  
  [Detail Level 2+: Section Breakdown]
  
  [Detail Level 3+: Spacing Analysis]
  ```

### 4. **Progressive Detail Levels**

The feedback becomes more detailed across iterations:

- **Level 1 (Iteration 1):**
  - Page status
  - Instructions (keyword integration vs. condensation)
  - Bullet length issues
  - Overflow issues (with percentages)
  - Whitespace utilization (if >50% waste)

- **Level 2 (Iteration 2):**
  - Everything from Level 1
  - Section breakdown (% of page per section)
  - Recommendations (which section to condense)

- **Level 3 (Iteration 3+):**
  - Everything from Level 2
  - Spacing analysis (gaps between sections/bullets)

### 5. **Quality Gate (check_quality)**

Checks multiple criteria:
- **Page count**: Must be ≤ target_pages
- **Overflow**: No text beyond margins
- **Bullet length**: No bullets > max_bullet_lines

All must pass for success. If any fail, provides specific feedback for the LLM to fix.

## Input/Output Flow

### Inputs to Pipeline:
1. **resume_latex**: Original LaTeX resume
2. **job_description**: Job description text

### Inputs to LLM (per iteration):
1. **resume_latex**: Current state of resume
2. **job_description**: Same job description each time
3. **layout_analysis**: Formatted feedback string (changes each iteration)
4. **target_pages**: Usually 1

### Outputs from LLM:
1. **optimized_latex**: New LaTeX with keywords integrated

### Final Output:
1. **OptimizationResult**:
   - `success`: Boolean (all quality criteria passed)
   - `optimized_latex`: Final optimized LaTeX
   - `pdf_bytes`: Compiled PDF
   - `page_count`: Final page count
   - `iterations`: Number of iterations used
   - `error_message`: Any errors (if not successful)

## Key Design Decisions

1. **Unified Model**: Single `OptimizeResume` signature handles both keyword integration and layout fixes (better context)

2. **Progressive Feedback**: Starts simple, adds detail as needed (avoids overwhelming LLM early)

3. **Quality Gate**: Multiple criteria must ALL pass (prevents stopping early with partial fixes)

4. **Auto-Repair**: LaTeX errors are automatically fixed before compilation (robustness)

5. **Page Expansion Detection**: Special handling if resume expands (aggressive condensation feedback)

6. **Whitespace Percentages**: Uses % instead of points for LLM comprehension (easier to understand)

7. **Last Valid Version**: Always keeps track of last working version for recovery

## Example Feedback String to LLM

```
LAYOUT ANALYSIS:

Page Status: 1 page(s) - FITS within target of 1 page(s)

Instructions: Actively integrate job keywords while keeping the same length.
- KEEP all bullet points, skills, and content
- REPHRASE to add keywords (swap words, don't add length)

Bullet Length: All bullets within limit (2-3 lines) - no changes needed

Overflow Status: No overflow detected - all text within margins

*** EXCESSIVE WHITESPACE - CONDENSE BULLETS ***
These bullets have poor space utilization (last line wastes >50%):
  Issue 1: 3 lines - 'Led a team of 4 to develop a Large Language...'
  Last line utilization: 22.4% used, 77.6% whitespace waste
  ACTION: Condense to fewer lines or add more content to fill the line
```

This feedback guides the LLM to make specific improvements in the next iteration.

