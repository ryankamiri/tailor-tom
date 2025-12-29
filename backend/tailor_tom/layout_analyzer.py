import fitz
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional
from difflib import SequenceMatcher

from io import BytesIO
from PyPDF2 import PdfReader


@dataclass
class QualityResult:
    """Result of quality check on a compiled PDF resume."""
    
    passes: bool
    page_count: int
    page_target: int
    long_bullets: List[Dict]  # bullets with line_count > max_bullet_lines
    
    @property
    def issues_summary(self) -> str:
        """Human-readable summary of issues."""
        issues = []
        if self.page_count > self.page_target:
            issues.append(f"Page count: {self.page_count} (target: {self.page_target})")
        if self.long_bullets:
            issues.append(f"Long bullets (>3 lines): {len(self.long_bullets)}")
        return "; ".join(issues) if issues else "All criteria pass"
    
    @property
    def has_issues(self) -> bool:
        """Check if there are any quality issues."""
        return not self.passes


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Count pages in a PDF."""
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        return len(reader.pages)
    except Exception:
        # Fallback
        try:
            content = pdf_bytes.decode("latin-1")
            return content.count("/Type /Page") - content.count("/Type /Pages")
        except Exception:
            return 0


def check_quality(
    pdf_bytes: bytes,
    target_pages: int = 1,
    max_bullet_lines: int = 3,
    latex: Optional[str] = None,
) -> QualityResult:
    """Check if a compiled PDF resume meets all quality criteria.
    
    Quality criteria:
    1. Page count <= target_pages
    2. No bullet points longer than max_bullet_lines (default: 3)
    
    Args:
        pdf_bytes: Compiled PDF as bytes.
        target_pages: Maximum allowed page count.
        max_bullet_lines: Maximum lines allowed per bullet point (default: 3).
        latex: Optional LaTeX source for better bullet detection.
        
    Returns:
        QualityResult with pass/fail status and details about issues.
    """
    # Count pages
    page_count = _count_pdf_pages(pdf_bytes)
    
    # Extract bullet metrics (for line count detection only)
    # Use LaTeX-based detection if available for consistency with analyze_layout
    bullet_metrics = extract_line_metrics(pdf_bytes, latex=latex)
    bullets = bullet_metrics.get("bullets", [])
    
    # Find long bullets (> max_bullet_lines)
    long_bullets = [
        b for b in bullets 
        if b.get("line_count", 0) > max_bullet_lines
    ]
    
    logger = logging.getLogger(__name__)
    # Quality check completed
    
    # Determine if all criteria pass
    passes = (
        page_count <= target_pages and
        len(long_bullets) == 0
    )
    
    return QualityResult(
        passes=passes,
        page_count=page_count,
        page_target=target_pages,
        long_bullets=long_bullets,
    )


def _strip_item_text(latex_item: str) -> str:
    r"""Extract clean text from a LaTeX \item entry, removing commands but preserving content.
    
    Args:
        latex_item: LaTeX item text (content after \item).
        
    Returns:
        Clean text content.
    """
    text = latex_item
    
    # Remove LaTeX comments (% to end of line, but not \% which is escaped)
    # Use regex with negative lookbehind to find % not preceded by backslash
    # Split by lines to handle comments properly (comments go to end of line)
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # Find % that's not preceded by a backslash (using negative lookbehind)
        # Pattern: (?<!\\)% means % not preceded by backslash
        line = re.sub(r'(?<!\\)%.*$', '', line)
        cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)
    
    # Extract content from formatting commands (keep the text inside)
    formatting_commands = [
        (r'\\textbf\{([^}]*)\}', r'\1'),
        (r'\\textit\{([^}]*)\}', r'\1'),
        (r'\\underline\{([^}]*)\}', r'\1'),
        (r'\\emph\{([^}]*)\}', r'\1'),
        (r'\\textsc\{([^}]*)\}', r'\1'),
        (r'\\textsf\{([^}]*)\}', r'\1'),
        (r'\\texttt\{([^}]*)\}', r'\1'),
        (r'\\href\{[^}]*\}\{([^}]*)\}', r'\1'),
        (r'\\url\{([^}]*)\}', r'\1'),
    ]
    
    for pattern, replacement in formatting_commands:
        text = re.sub(pattern, replacement, text)
    
    # Replace escaped special characters
    text = text.replace('\\&', '&')
    text = text.replace('\\%', '%')
    text = text.replace('\\$', '$')
    text = text.replace('\\#', '#')
    text = text.replace('\\_', '_')
    text = text.replace('\\{', '{')
    text = text.replace('\\}', '}')
    text = text.replace('~', ' ')  # Non-breaking space
    text = text.replace('$|$', '|')  # Pipe in math mode
    
    # Remove any remaining LaTeX commands (single backslash followed by letters)
    text = re.sub(r'\\[a-zA-Z]+\*?(?:\{[^}]*\})*', ' ', text)
    
    # Remove braces
    text = text.replace('{', '').replace('}', '')
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text


def extract_items_from_latex(latex: str) -> List[Dict]:
    r"""Extract all \item entries from LaTeX with their text content.
    
    Args:
        latex: LaTeX source code.
        
    Returns:
        List of item dictionaries with:
        {
            "text": "...",  # Clean text content
            "latex": "...",  # Original LaTeX item text
        }
    """
    items = []
    
    # Extract document content (between \begin{document} and \end{document})
    if '\\begin{document}' in latex:
        latex = latex.split('\\begin{document}', 1)[1]
    if '\\end{document}' in latex:
        latex = latex.split('\\end{document}', 1)[0]
    
    # Find all \item entries
    # Pattern matches \item followed by optional whitespace and the content
    # We need to handle nested braces and environments
    
    # CRITICAL: Filter out commented-out \item entries
    # In LaTeX, % comments out to the end of the line, so we need to check
    # if the line containing \item starts with %
    item_pattern = r'\\item\s+'
    all_matches = list(re.finditer(item_pattern, latex))
    
    # Filter out matches that are on commented lines
    valid_matches = []
    for match in all_matches:
        match_start = match.start()
        # Find the start of the line containing this \item
        line_start = latex.rfind('\n', 0, match_start)
        if line_start == -1:
            line_start = 0
        else:
            line_start += 1  # Skip the newline character
        
        # Get the line text from line_start to match_start
        line_prefix = latex[line_start:match_start]
        # Check if the line (after stripping leading whitespace) starts with %
        # We need to be careful - if there's whitespace before %, it's still a comment
        stripped_prefix = line_prefix.lstrip()
        # If stripped_prefix is empty, the \item is at the start of the line (not commented)
        # If stripped_prefix starts with %, the line is commented
        if not stripped_prefix.startswith('%'):
            valid_matches.append(match)
    
    matches = valid_matches
    
    for i, match in enumerate(matches):
        start_pos = match.end()
        
        # Find the end of this item
        # CRITICAL: Use next \item as the primary boundary (most direct delimiter)
        # Only use environment boundaries if they come BEFORE the next \item
        
        end_pos = len(latex)
        
        # First, check for the next \item (most direct boundary)
        if i + 1 < len(matches):
            next_item_pos = matches[i + 1].start()
            end_pos = next_item_pos
        
        # Then check for environment boundaries that might come before the next item
        # (to handle cases where we're at the last item in a list)
        boundaries = [
            latex.find('\\end{subitems}', start_pos),
            latex.find('\\end{resume_subsection}', start_pos),
            latex.find('\\begin{resume_section}', start_pos),
        ]
        # Filter out -1 (not found) and find boundaries that come BEFORE end_pos
        valid_boundaries = [b for b in boundaries if b != -1 and b < end_pos]
        if valid_boundaries:
            # Use the earliest valid boundary (closest to start_pos)
            end_pos = min(valid_boundaries)
        
        # Extract the item content
        item_latex = latex[start_pos:end_pos].strip()
        
        # Remove trailing backslashes and whitespace
        item_latex = re.sub(r'\\+$', '', item_latex).strip()
        
        # Extract clean text
        item_text = _strip_item_text(item_latex)
        
        if item_text:  # Only add non-empty items
            items.append({
                "text": item_text,
                "latex": item_latex,
            })
    
    return items


def _fuzzy_match_text_in_pdf(doc: fitz.Document, search_text: str, threshold: float = 0.6) -> List[Dict]:
    """Find text blocks in PDF that fuzzy match the search text.
    
    Args:
        doc: PyMuPDF document.
        search_text: Text to search for (can be partial).
        threshold: Minimum similarity ratio (0.0 to 1.0).
        
    Returns:
        List of matching text blocks with coordinates and metadata, sorted by similarity.
    """
    matches = []
    search_text_lower = search_text.lower().strip()
    
    if not search_text_lower:
        return []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        text_dict = page.get_text("dict")
        
        # Collect all lines with their coordinates
        all_lines = []
        for block in text_dict.get("blocks", []):
            if "lines" not in block:
                continue
            
            for line in block["lines"]:
                if "spans" not in line:
                    continue
                
                line_text = ""
                line_spans = []
                line_bbox = line.get("bbox", [0, 0, 0, 0])
                
                for span in line["spans"]:
                    span_text = span.get("text", "").strip()
                    if span_text:
                        line_text += span_text + " "
                        # Get bbox from span, fallback to line bbox
                        span_bbox = span.get("bbox", line_bbox)
                        if len(span_bbox) == 4:
                            line_spans.append({
                                "text": span_text,
                                "bbox": span_bbox,
                            })
                        else:
                            line_spans.append({
                                "text": span_text,
                                "bbox": line_bbox,
                            })
                
                if line_text.strip():
                    all_lines.append({
                        "text": line_text.strip(),
                        "bbox": line_bbox,
                        "spans": line_spans,
                    })
        
        # Try matching individual lines and multi-line blocks
        # First, try matching individual lines
        for line in all_lines:
            line_text_lower = line["text"].lower()
            if len(line_text_lower) < 10:  # Skip very short lines
                continue
            
            ratio = SequenceMatcher(None, search_text_lower, line_text_lower).ratio()
            if ratio >= threshold:
                matches.append({
                    "page": page_num,
                    "text": line["text"],
                    "bbox": line["bbox"],
                    "spans": line["spans"],
                    "similarity": ratio,
                    "match_type": "line"
                })
        
        # Also try matching consecutive lines that might form a bullet point
        # This helps with multi-line bullets, but be more conservative
        # Only combine lines that are close together vertically (likely same bullet)
        for i in range(len(all_lines)):
            current_line = all_lines[i]
            combined_lines = [current_line]
            combined_text = current_line["text"]
            
            # Try extending with next lines if they're close (likely continuation)
            # Wrapped lines have VERY small gaps (1-4pt), new bullets have larger gaps (5pt+)
            for j in range(i + 1, min(i + 4, len(all_lines))):
                next_line = all_lines[j]
                # bbox is [x0, y0, x1, y1] list, not dict
                current_bbox = current_line["bbox"]
                next_bbox = next_line["bbox"]
                
                # Check if next line is close vertically (within 5pt - very tight for wrapped lines)
                y_gap = next_bbox[1] - current_bbox[3]  # next y0 - current y1
                if y_gap > 5 or y_gap < 0:
                    break  # Too far or above - not a continuation (likely new bullet)
                
                # Check if x position is very similar (wrapped lines should have almost identical x)
                x_diff = abs(next_bbox[0] - current_bbox[0])  # next x0 - current x0
                if x_diff > 8:  # Different indentation - likely new bullet or different section
                    break
                
                # Additional check: if next line starts with capital after punctuation,
                # it might be a new bullet (action verbs often start bullets)
                next_text = next_line["text"].strip()
                if next_text and next_text[0].isupper():
                    prev_text = current_line["text"].strip()
                    if prev_text and prev_text[-1] in ".!;":
                        # Previous ended with punctuation AND next starts with capital
                        # Even if gap is small, could be new bullet - be conservative
                        # Only combine if gap is very small (< 3pt)
                        if y_gap > 3:
                            break
                
                combined_lines.append(next_line)
                combined_text = " ".join([l["text"] for l in combined_lines]).strip()
                combined_text_lower = combined_text.lower()
                
                if len(combined_text_lower) < 10:
                    continue
                
                ratio = SequenceMatcher(None, search_text_lower, combined_text_lower).ratio()
                if ratio >= threshold:
                    # Check if we already have this match
                    if not any(abs(m.get("similarity", 0) - ratio) < 0.01 and 
                              m.get("text", "").lower() == combined_text_lower for m in matches):
                        # Calculate combined bbox
                        x0 = min(l["bbox"][0] for l in combined_lines)
                        y0 = min(l["bbox"][1] for l in combined_lines)
                        x1 = max(l["bbox"][2] for l in combined_lines)
                        y1 = max(l["bbox"][3] for l in combined_lines)
                        
                        # Collect all spans from combined lines
                        all_spans = []
                        for line in combined_lines:
                            if "spans" in line:
                                all_spans.extend(line["spans"])
                            else:
                                # Fallback: create span from bbox
                                all_spans.append({
                                    "bbox": line["bbox"],
                                    "text": line["text"]
                                })
                        
                        matches.append({
                            "page": page_num,
                            "text": combined_text,
                            "bbox": [x0, y0, x1, y1],
                            "spans": all_spans,
                            "similarity": ratio,
                            "match_type": "multi_line"
                        })
                
                current_line = next_line  # Update for next iteration
    
    # Sort by similarity (best matches first)
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches


def _is_not_a_bullet(first_line_text: str, full_text: str = None) -> bool:
    r"""Check if a line is definitely NOT a bullet point (e.g., section header, job title).
    
    Uses general heuristics to filter out non-bullet content. This is only used in the
    PDF-only fallback path. When LaTeX is available, we use LaTeX \item entries directly.
    
    Args:
        first_line_text: First line of the text block (most important for detection).
        full_text: Full combined text (optional, for additional checks).
        
    Returns:
        True if the line is NOT a bullet point.
    """
    first_line = first_line_text.strip() if first_line_text else ""
    
    # CRITICAL: Only lines that START with a bullet marker are bullets
    # Common bullet markers: "-", "•", "·", etc.
    bullet_markers = ["-", "•", "·", "▪", "▸"]
    starts_with_bullet = any(first_line.startswith(marker) for marker in bullet_markers)
    
    # If it doesn't start with a bullet marker, it's NOT a bullet
    if not starts_with_bullet:
        # Use general patterns to filter out common non-bullet content
        
        # All caps lines (likely section headers)
        if first_line == first_line.upper() and len(first_line) > 5:
            return True
        
        # Company/Job title lines (contain "|" separator - common pattern)
        if "|" in first_line:
            return True
        
        # Location patterns (City, State)
        if re.search(r'[A-Z][a-z]+,\s*[A-Z]{2}', first_line):
            return True
        
        # Date patterns (years, date ranges, months)
        if re.search(r'\(.*\d{4}.*\)', first_line) or re.search(r'\d{4}\s*[–-]\s*\d{4}', first_line):
            return True
        if re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', first_line, re.IGNORECASE):
            return True
        
        # Very short lines (likely headers or labels)
        if len(first_line.split()) <= 3:
            return True
        
        return True
    
    # If it starts with a bullet marker, it's likely a bullet point
    return False


def extract_line_metrics(pdf_bytes: bytes, latex: Optional[str] = None) -> Dict:
    r"""Extract line counts for each bullet point.
    
    If latex is provided, uses LaTeX \item entries as source of truth and fuzzy matches
    them to PDF. Otherwise, falls back to PDF-only detection.
    
    Args:
        pdf_bytes: PDF file as bytes.
        latex: Optional LaTeX source code for more accurate bullet detection.
        
    Returns:
        Dictionary with bullet metrics:
        {
            "bullets": [
                {
                    "text_preview": "...",
                    "line_count": 3,
                    "y_start": 200.0,
                    "y_end": 245.0,
                    "x_start": 72.0,
                    "last_line_x_end": 500.0,
                },
                ...
            ]
        }
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    bullets = []
    
    try:
        if latex:
            # Use LaTeX-based detection: extract items from LaTeX and match to PDF
            items = extract_items_from_latex(latex)
            
            for item in items:
                item_text = item["text"]
                if not item_text:
                    continue
                
                # Fuzzy match this item to PDF
                # Use a higher threshold (0.7) to avoid false matches
                # Use first ~150 chars as search text to avoid matching across multiple bullets
                # This helps ensure we match just this bullet, not combine with others
                search_text = item_text[:150] if len(item_text) > 150 else item_text
                matches = _fuzzy_match_text_in_pdf(doc, search_text, threshold=0.7)
                
                if not matches:
                    # Item not found in PDF - skip it
                    continue
                
                # Use the best match (but verify similarity is high enough)
                best_match = matches[0]
                similarity = best_match.get("similarity", 0)
                if similarity < 0.7:
                    # Match quality too low - skip this item to avoid false positives
                    continue
                
                # Also check that the matched text doesn't contain obvious artifacts
                # (like multiple dates, section markers, etc. which suggest wrong match)
                matched_text = best_match.get("text", "")
                # Count occurrences of patterns that suggest combining multiple bullets
                date_pattern_count = len(re.findall(r'\d{4}', matched_text))
                if date_pattern_count > 2:  # More than 2 years suggests combining multiple entries
                    continue  # Skip this match - likely combining multiple bullets
                
                # Extract line information from the match
                spans = best_match.get("spans", [])
                if not spans:
                    continue
                
                # Calculate bounding box
                # Ensure all spans have valid bbox (list format: [x0, y0, x1, y1])
                x_coords = []
                y_coords = []
                valid_spans = []
                for s in spans:
                    bbox = s.get("bbox", [])
                    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                        x_coords.extend([bbox[0], bbox[2]])
                        y_coords.extend([bbox[1], bbox[3]])
                        valid_spans.append(s)
                
                if not valid_spans:
                    continue  # Skip if no valid bboxes
                
                x_start = min(x_coords)
                x_end = max(x_coords)
                y_start = min(y_coords)
                y_end = max(y_coords)
                
                # Count lines: group spans by Y-coordinate (similar Y = same line)
                line_threshold = 3.0
                y_groups = defaultdict(list)
                for span in valid_spans:
                    bbox = span.get("bbox", [])
                    if len(bbox) < 4:
                        continue
                    y_center = (bbox[1] + bbox[3]) / 2
                    matched = False
                    for y_key in y_groups.keys():
                        if abs(y_key - y_center) < line_threshold:
                            y_groups[y_key].append(span)
                            matched = True
                            break
                    if not matched:
                        y_groups[y_center] = [span]
                
                line_count = len(y_groups)
                
                # Reconstruct text split by lines for display
                lines_text = []
                if y_groups and line_count > 1:
                    # Sort y_keys to get lines in top-to-bottom order (ascending Y)
                    sorted_y_keys = sorted(y_groups.keys())
                    for y_key in sorted_y_keys:
                        line_spans = y_groups[y_key]
                        # Sort spans by x0 (left to right) for reading order
                        sorted_line_spans = sorted(
                            [s for s in line_spans if isinstance(s.get("bbox"), (list, tuple)) and len(s.get("bbox", [])) >= 4],
                            key=lambda s: s.get("bbox", [0])[0]
                        )
                        # Join text from all spans on this line
                        line_text = " ".join(s.get("text", "").strip() for s in sorted_line_spans if s.get("text", "").strip())
                        if line_text:
                            lines_text.append(line_text)
                else:
                    # Single line - just use the full text
                    lines_text = [item_text]
                
                # Find the last line's left and right edges (for whitespace calculation)
                # Use the rightmost span on the last line from the fuzzy match
                # The fuzzy match should already give us the correct spans for this bullet
                last_line_x_end = None
                last_line_x_start = None
                if y_groups and len(y_groups) > 0:
                    last_line_y = max(y_groups.keys())  # Bottom-most line (highest Y in PDF - use max, not min!)
                    last_line_spans = y_groups[last_line_y]
                    
                    # Sort spans by x0 (left to right) to process in reading order
                    sorted_spans = sorted(
                        [s for s in last_line_spans if isinstance(s.get("bbox"), (list, tuple)) and len(s.get("bbox", [])) >= 4],
                        key=lambda s: s.get("bbox", [0])[0]
                    )
                    
                    last_line_x_coords_start = []
                    last_line_x_coords_end = []
                    
                    # Debug: Log all spans for first few bullets (FULL text, no truncation)
                    # Collect all span coordinates (from fuzzy match, so should be correct for this bullet)
                    for s in sorted_spans:
                        bbox = s.get("bbox", [])
                        
                        if bbox:
                            last_line_x_coords_start.append(bbox[0])
                            last_line_x_coords_end.append(bbox[2])
                    
                    # Use the rightmost span's x1 as the end of the last line
                    if last_line_x_coords_end:
                        last_line_x_end = max(last_line_x_coords_end)
                    
                    if last_line_x_coords_start:
                        last_line_x_start = min(last_line_x_coords_start)
                        # Ensure last_line_x_end is set (fallback if not set above)
                        if last_line_x_end is None and last_line_x_coords_end:
                            last_line_x_end = max(last_line_x_coords_end)
                
                # Fallback: if we couldn't extract last line coordinates, use overall bullet coordinates
                # (this should only happen for single-line bullets, which we don't check utilization for anyway)
                if last_line_x_start is None:
                    last_line_x_start = x_start
                if last_line_x_end is None:
                    last_line_x_end = x_end
                
                # Final values stored for utilization calculation
                
                bullets.append({
                    "text_preview": item_text,  # Store full text
                    "lines_text": lines_text,  # Store text split by lines (for showing line breaks)
                    "latex_source": item.get("latex", ""),  # Store LaTeX source for reference
                    "line_count": line_count,
                    "y_start": y_start,
                    "y_end": y_end,
                    "x_start": x_start,
                    "last_line_x_start": last_line_x_start,  # Left edge of last line
                    "last_line_x_end": last_line_x_end,      # Right edge of last line
                })
            
            # Don't close here - let finally block handle it
            return {"bullets": bullets}
        
        # Fallback to PDF-only detection (original implementation)
        # Analyze only the first page for resumes (usually one page)
        if len(doc) == 0:
            return {"bullets": []}
        
        page = doc[0]
        
        # Get all text blocks with coordinates
        text_dict = page.get_text("dict")
        
        # Collect all text spans with their positions
        text_spans = []
        for block in text_dict.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    if "spans" in line:
                        for span in line["spans"]:
                            if "text" in span and span["text"].strip():
                                bbox = span.get("bbox", [])
                                if len(bbox) == 4:
                                    text_spans.append({
                                        "text": span["text"],
                                        "x0": bbox[0],
                                        "y0": bbox[1],
                                        "x1": bbox[2],
                                        "y1": bbox[3],
                                        "bbox": bbox,  # Also store bbox as list for consistency
                                    })
        
        if not text_spans:
            return {"bullets": []}
        
        # Group spans by Y-coordinate (within threshold = same visual line)
        line_threshold = 3.0  # points - spans within 3pt are considered same line
        y_groups = defaultdict(list)
        
        for span in text_spans:
            # Use x0, y0, x1, y1 keys (these are set when we create text_spans)
            y_center = (span.get("y0", 0) + span.get("y1", 0)) / 2
            # Find closest group or create new one
            matched = False
            for y_key in y_groups.keys():
                if abs(y_key - y_center) < line_threshold:
                    y_groups[y_key].append(span)
                    matched = True
                    break
            if not matched:
                y_groups[y_center] = [span]
        
        # Sort lines by Y position (top to bottom)
        sorted_y_keys = sorted(y_groups.keys(), reverse=True)
        
        # Identify bullet points
        # Bullets typically have:
        # - Similar x-coordinate (left margin)
        # - Consecutive Y-coordinates (lines of same bullet)
        # - Text starting after bullet character/indentation
        
        current_bullet = None
        bullet_start_y = None
        bullet_lines = []
        bullet_x = None
        bullet_last_line_x_start = None  # Track left edge of last line for utilization
        bullet_last_line_x_end = None  # Track right edge of last line for utilization
        
        for y_key in sorted_y_keys:
            spans = sorted(y_groups[y_key], key=lambda s: s["x0"])
            if not spans:
                continue
            
            # Get the leftmost span (likely the bullet or start of text)
            first_span = spans[0]
            x_start = first_span.get("x0", 0)
            # Get the rightmost span (end of line)
            last_span = spans[-1]
            x_end = last_span.get("x1", 0)
            line_text = " ".join([s["text"] for s in spans]).strip()
            
            # CRITICAL: Only detect actual bullet points (must start with "-" or similar)
            # Heuristic: bullet points typically start at similar X position
            # and have some indentation from the left margin
            # Common bullet start positions: 36-100 points from left edge
            
            # Check if this is a bullet point by:
            # 1. Position check (indented)
            # 2. Starts with bullet marker OR is clearly a bullet continuation
            # 3. NOT a section header/job title/etc.
            
            starts_with_bullet_marker = any(line_text.startswith(marker) for marker in ["-", "•", "·", "▪", "▸"])
            
            is_bullet_start = (
                x_start >= 36 and  # Not too close to left edge (header)
                x_start <= 100 and  # Not too far (unlikely to be bullet)
                len(line_text) > 0 and
                starts_with_bullet_marker and  # MUST start with bullet marker
                not _is_not_a_bullet(line_text, line_text)  # Filter out section headers, etc.
            )
            
            if current_bullet is None:
                # Start new bullet
                if is_bullet_start:
                    current_bullet = line_text
                    bullet_start_y = y_key
                    bullet_lines = [line_text]
                    bullet_x = x_start
                    bullet_last_line_x_start = x_start  # Left edge of last line
                    bullet_last_line_x_end = x_end      # Right edge of last line
            else:
                # Check if this line belongs to current bullet
                # Lines of same bullet have similar X start and consecutive Y positions
                y_diff = bullet_start_y - y_key  # Positive since we're going top to bottom
                
                if (
                    abs(x_start - bullet_x) < 10 and  # Similar X position
                    y_diff > 0 and y_diff < 50  # Consecutive (within 50pt)
                ):
                    # Same bullet, continue
                    bullet_lines.append(line_text)
                    bullet_start_y = y_key  # Update to latest line
                    bullet_last_line_x_start = x_start  # Update last line left edge
                    bullet_last_line_x_end = x_end      # Update last line right edge
                else:
                    # End of current bullet, start new one
                    # ONLY add bullet if the FIRST line starts with a bullet marker
                    if bullet_lines:
                        first_line = bullet_lines[0].strip()
                        starts_with_bullet = any(first_line.startswith(marker) for marker in ["-", "•", "·", "▪", "▸"])
                        if starts_with_bullet and not _is_not_a_bullet(first_line, " ".join(bullet_lines[:3])):
                            bullets.append({
                                "text_preview": " ".join(bullet_lines[:3]),  # Full text from first 3 lines
                                "line_count": len(bullet_lines),
                                "y_start": bullet_start_y + (50 if current_bullet else 0),  # Approximate
                                "y_end": y_key,
                                "x_start": bullet_x,
                                "last_line_x_start": bullet_last_line_x_start,  # Left edge of last line
                                "last_line_x_end": bullet_last_line_x_end,      # Right edge of last line
                            })
                    
                    # Start new bullet
                    current_bullet = line_text if is_bullet_start else None
                    bullet_start_y = y_key if is_bullet_start else None
                    bullet_lines = [line_text] if is_bullet_start else []
                    bullet_x = x_start if is_bullet_start else None
                    bullet_last_line_x_start = x_start if is_bullet_start else None
                    bullet_last_line_x_end = x_end if is_bullet_start else None
        
        # Don't forget the last bullet
        # ONLY add bullet if the FIRST line starts with a bullet marker
        if current_bullet and bullet_lines:
            first_line = bullet_lines[0].strip()
            starts_with_bullet = any(first_line.startswith(marker) for marker in ["-", "•", "·", "▪", "▸"])
            if starts_with_bullet and not _is_not_a_bullet(first_line, " ".join(bullet_lines[:3])):
                bullets.append({
                    "text_preview": " ".join(bullet_lines[:3])[:100],
                    "line_count": len(bullet_lines),
                    "y_start": bullet_start_y + 50 if bullet_start_y else 0,
                    "y_end": sorted_y_keys[-1] if sorted_y_keys else 0,
                    "x_start": bullet_x,
                    "last_line_x_start": bullet_last_line_x_start,  # Left edge of last line
                    "last_line_x_end": bullet_last_line_x_end,      # Right edge of last line
                })
    
    finally:
        if not doc.is_closed:
            doc.close()
    
    return {"bullets": bullets}


def detect_overflow(pdf_bytes: bytes, margin: int = 30) -> List[Dict]:
    """Detect text exceeding page margins.
    
    Improved detection that checks full line width (not just individual spans)
    to catch overflow in long lines like skills lists. Uses actual content boundaries
    detected from the PDF, matching the logic used in analyze_layout.
    
    Args:
        pdf_bytes: PDF file as bytes.
        margin: Margin allowance in points (default: 30pt, but we use content boundaries instead).
        
    Returns:
        List of overflow issues:
        [
            {
                "section": "Skills",
                "text": "...",
                "x_end": 552.3,
                "content_boundary": 556.2,
                "overflow_by": 32.1,  # Overflow beyond typical content width
            },
            ...
        ]
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    overflow_issues = []
    
    try:
        if len(doc) == 0:
            return []
        
        page = doc[0]
        page_rect = page.rect
        page_width = page_rect.width
        
        # Get all text blocks to determine actual content boundaries (same logic as analyze_layout)
        text_dict = page.get_text("dict")
        
        # Find content boundaries by detecting leftmost and rightmost text
        # (excluding very short lines that might be bullets/markers)
        content_left = None
        content_right = None
        
        for block in text_dict.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    if "spans" in line:
                        # Get full line text to filter out short lines
                        line_text = " ".join([span.get("text", "") for span in line.get("spans", [])]).strip()
                        # Skip very short lines (likely bullets/markers)
                        if len(line_text) > 3:
                            for span in line["spans"]:
                                if "text" in span and span["text"].strip():
                                    bbox = span.get("bbox", [])
                                    if len(bbox) == 4:
                                        line_width = bbox[2] - bbox[0]
                                        # Skip very short lines (likely artifacts)
                                        if line_width > 20:
                                            if content_left is None or bbox[0] < content_left:
                                                content_left = bbox[0]
                                            if content_right is None or bbox[2] > content_right:
                                                content_right = bbox[2]
        
        # Fallback to page edges if we couldn't detect margins
        if content_left is None or content_right is None:
            if content_left is None:
                content_left = page_rect.x0 + 36  # Typical left margin
            if content_right is None:
                content_right = page_rect.x1 - 36  # Typical right margin
        
        # Use a percentile-based approach to detect overflow threshold
        # Collect all line endings to find the typical content boundary
        all_line_endings = []
        for block in text_dict.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    if "spans" in line:
                        for span in line["spans"]:
                            if "text" in span and span["text"].strip():
                                bbox = span.get("bbox", [])
                                if len(bbox) == 4:
                                    all_line_endings.append(bbox[2])  # x_end
        
        # Calculate threshold as 95th percentile of line endings
        # This excludes outliers (overflow lines) and uses typical content width
        if all_line_endings:
            sorted_endings = sorted(all_line_endings)
            percentile_95_idx = int(len(sorted_endings) * 0.95)
            if percentile_95_idx >= len(sorted_endings):
                percentile_95_idx = len(sorted_endings) - 1
            threshold_max_x = sorted_endings[percentile_95_idx]
            # Use 95th percentile as the threshold (no extra tolerance here)
            max_x = threshold_max_x
        else:
            # Fallback: Standard US letter paper (612pt width) with 0.5" margins = 36pt margins
            # Typical content area: 612 - 36 - 36 = 540pt, use 540pt as threshold
            max_x = min(540.0, page_width - 36)
        
        seen_lines = set()  # Track lines we've already checked to avoid duplicates
        
        for block in text_dict.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    if "spans" in line:
                        # Check the full line width (rightmost span's x_end)
                        line_x_end = None
                        line_text_parts = []
                        
                        for span in line["spans"]:
                            if "text" in span and span["text"].strip():
                                bbox = span.get("bbox", [])
                                if len(bbox) == 4:
                                    x_end = bbox[2]  # Right edge of this span
                                    if line_x_end is None or x_end > line_x_end:
                                        line_x_end = x_end
                                    line_text_parts.append(span["text"].strip())
                        
                        # Check if the full line extends beyond the content boundary
                        # Allow a small tolerance (5pt) for rendering differences to avoid false positives
                        if line_x_end is not None and line_x_end > (max_x + 5):
                            # Create a unique identifier for this line to avoid duplicates
                            line_text = " ".join(line_text_parts)
                            line_key = (line_x_end, line_text[:50])
                            
                            if line_key not in seen_lines:
                                seen_lines.add(line_key)
                                overflow_by = line_x_end - max_x
                                overflow_issues.append({
                                    "section": "Unknown",
                                    "text": line_text[:80],  # Preview of full line
                                    "x_end": line_x_end,
                                    "page_width": page_width,
                                    "content_boundary": max_x,
                                    "overflow_by": overflow_by,
                                })
    
    finally:
        doc.close()
    
    return overflow_issues


def analyze_section_layout(pdf_bytes: bytes) -> Dict:
    """Analyze section-level metrics.
    
    Groups text blocks by sections (based on Y-position ranges),
    calculates lines per section, vertical space usage, and % of page.
    
    Args:
        pdf_bytes: PDF file as bytes.
        
    Returns:
        Dictionary with section metrics:
        {
            "sections": [
                {
                    "name": "WORK EXPERIENCE",
                    "line_count": 45,
                    "y_start": 150.0,
                    "y_end": 450.0,
                    "percent_of_page": 45.5,
                },
                ...
            ],
            "page_height": 792.0,
        }
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    sections = []
    
    try:
        if len(doc) == 0:
            return {"sections": [], "page_height": 0}
        
        page = doc[0]
        page_rect = page.rect
        page_height = page_rect.height
        
        # Get all text blocks
        text_dict = page.get_text("dict")
        
        # Collect all lines with their Y positions
        lines = []
        for block in text_dict.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    if "spans" in line:
                        line_text = " ".join([span.get("text", "") for span in line.get("spans", [])])
                        if line_text.strip():
                            bbox = line.get("bbox", [])
                            if len(bbox) == 4:
                                lines.append({
                                    "text": line_text.strip(),
                                    "y": (bbox[1] + bbox[3]) / 2,  # Center Y
                                    "y0": bbox[1],
                                    "y1": bbox[3],
                                })
        
        if not lines:
            return {"sections": [], "page_height": page_height}
        
        # Sort lines by Y position (top to bottom)
        lines.sort(key=lambda l: l["y"], reverse=True)
        
        # Identify sections by looking for section headers
        # Section headers are typically:
        # - ALL CAPS or bold
        # - On their own line
        # - Have larger font size or spacing above them
        
        section_names = []
        section_y_positions = []
        
        for line in lines:
            text = line["text"]
            # Heuristic: section headers are short, often all caps or have special formatting
            is_likely_header = (
                len(text) < 50 and
                (text.isupper() or "EXPERIENCE" in text.upper() or "EDUCATION" in text.upper() or
                 "SKILLS" in text.upper() or "PROJECTS" in text.upper())
            )
            
            if is_likely_header:
                section_names.append(text)
                section_y_positions.append(line["y"])
        
        # If no headers found, create default sections based on position
        if not section_names:
            # Assume common sections: Header, Work Experience, Education, Skills
            section_names = ["HEADER", "WORK EXPERIENCE", "EDUCATION", "SKILLS"]
            # Distribute evenly (rough approximation)
            for idx, name in enumerate(section_names):
                section_y_positions.append(page_height - (idx * 200))
        
        # Group lines into sections
        sections_data = []
        for i, (name, y_pos) in enumerate(zip(section_names, section_y_positions)):
            y_start = y_pos
            y_end = section_y_positions[i + 1] if i + 1 < len(section_y_positions) else 0
            
            # Count lines in this section
            section_lines = [
                line for line in lines
                if y_end < line["y"] <= y_start
            ]
            
            if section_lines:
                actual_y_start = max([l["y"] for l in section_lines])
                actual_y_end = min([l["y"] for l in section_lines])
                height = actual_y_start - actual_y_end
                percent_of_page = (height / page_height) * 100
                
                sections_data.append({
                    "name": name,
                    "line_count": len(section_lines),
                    "y_start": actual_y_start,
                    "y_end": actual_y_end,
                    "percent_of_page": percent_of_page,
                })
        
        return {
            "sections": sections_data,
            "page_height": page_height,
        }
    
    finally:
        doc.close()


def analyze_spacing(pdf_bytes: bytes) -> Dict:
    """Analyze spacing between sections and bullets.
    
    Measures gaps between section boundaries and calculates
    average inter-bullet spacing.
    
    Args:
        pdf_bytes: PDF file as bytes.
        
    Returns:
        Dictionary with spacing metrics:
        {
            "avg_section_gap": 15.0,
            "avg_bullet_gap": 8.0,
        }
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    
    try:
        if len(doc) == 0:
            return {"avg_section_gap": 0.0, "avg_bullet_gap": 0.0}
        
        # Get section layout first
        section_layout = analyze_section_layout(pdf_bytes)
        sections = section_layout.get("sections", [])
        
        # Calculate gaps between sections
        section_gaps = []
        for i in range(len(sections) - 1):
            gap = sections[i]["y_end"] - sections[i + 1]["y_start"]
            if gap > 0:
                section_gaps.append(gap)
        
        avg_section_gap = sum(section_gaps) / len(section_gaps) if section_gaps else 0.0
        
        # Get bullet metrics
        bullet_metrics = extract_line_metrics(pdf_bytes)
        bullets = bullet_metrics.get("bullets", [])
        
        # Calculate gaps between bullets
        bullet_gaps = []
        for i in range(len(bullets) - 1):
            gap = bullets[i]["y_end"] - bullets[i + 1]["y_start"]
            if gap > 0:
                bullet_gaps.append(gap)
        
        avg_bullet_gap = sum(bullet_gaps) / len(bullet_gaps) if bullet_gaps else 0.0
        
        return {
            "avg_section_gap": avg_section_gap,
            "avg_bullet_gap": avg_bullet_gap,
        }
    
    finally:
        doc.close()


def format_layout_feedback(
    analysis: Dict,
    detail_level: int = 1,
    current_pages: int = 1,
    target_pages: int = 1,
) -> str:
    """Format layout analysis for LLM consumption.
    
    Creates simplified structured text format with basic metrics only:
    - Page count status
    - Long bullets (>3 lines) - only for Phase 2
    
    Args:
        analysis: Dictionary containing all layout analysis data.
        detail_level: Level of detail (not used in simplified version, kept for compatibility).
        current_pages: Current page count.
        target_pages: Target page count.
        
    Returns:
        Formatted layout feedback as string.
    """
    lines = []
    lines.append("LAYOUT ANALYSIS:")
    lines.append(f"Page Status: {current_pages} page(s) - {'FITS' if current_pages <= target_pages else 'OVER'} target of {target_pages} page(s)")
    
    if current_pages > target_pages:
        lines.append("ACTION: Condense resume to fit target page count")
        lines.append("- Remove filler words, use abbreviations, combine phrases")
    
    bullets = analysis.get("bullets", [])
    
    # Check if last line is very short (1-2 words) by analyzing the text
    def is_last_line_short(bullet):
        """Check if last line has 1-2 words (poor utilization)."""
        lines_text = bullet.get("lines_text", [])
        if not lines_text or len(lines_text) == 0:
            return False
        last_line = lines_text[-1].strip()
        words = last_line.split()
        # If last line has 1-2 words, it's very short
        return len(words) <= 2
    
    # Priority targets: >2 lines AND <50% utilization, OR any 2+ line bullet with very short last line (1-2 words)
    priority_targets = []
    # Secondary targets: All other 2+ line bullets
    secondary_targets = []
    
    for b in bullets:
        line_count = b.get("line_count", 0)
        utilization = b.get("last_line_utilization_percent", 0) if b.get("last_line_utilization_percent") else 100
        has_short_last_line = is_last_line_short(b)
        
        # Priority: >2 lines with <50% util, OR 2+ lines with very short last line (1-2 words)
        if (line_count > 2 and utilization < 50) or (line_count >= 2 and has_short_last_line):
            priority_targets.append(b)
        elif line_count >= 2:
            secondary_targets.append(b)
    
    if priority_targets:
        lines.append("*** PRIORITY CONDENSATION TARGETS ***")
        lines.append("These bullets are >2 lines with <50% utilization, OR 2+ line bullets with very short last lines (1-2 words).")
        lines.append("STRATEGY: Remove 15-20 words from each bullet to aggressively shrink from n lines → n-1 lines.")
        lines.append("Remember: LaTeX breaks lines at word boundaries, so removing words naturally reduces line count.")
        lines.append("Be VERY AGGRESSIVE - cut 15-20 words per bullet to move multi-line bullets to n-1 lines.")
        lines.append("")
        for i, bullet in enumerate(priority_targets[:15], 1):  # Limit to first 15
            text_preview = bullet.get("text_preview", "")[:100]
            line_count = bullet.get("line_count", 0)
            utilization = bullet.get("last_line_utilization_percent", 0) if bullet.get("last_line_utilization_percent") else 0
            has_short = is_last_line_short(bullet)
            target_lines = max(1, line_count - 1)  # Target n-1 lines
            reason = "short last line (1-2 words)" if has_short else f"low utilization ({utilization:.1f}%)"
            lines.append(f"  Priority {i}: {line_count} lines -> target {target_lines} lines ({reason})")
            lines.append(f"    '{text_preview}...'")
            lines.append(f"    ACTION: Remove 15-20 words to aggressively reduce to {target_lines} line(s)")
        lines.append("")
    
    if secondary_targets:
        lines.append(f"*** SECONDARY TARGETS: {len(secondary_targets)} bullets with 2+ lines ***")
        lines.append("Also condense these bullets: Remove 10-15 words to reduce from 2 lines → 1 line (or 3 lines → 2 lines).")
        lines.append("Every line saved helps fit the resume on 1 page.")
        lines.append("")
        for i, bullet in enumerate(secondary_targets[:10], 1):  # Show first 10
            text_preview = bullet.get("text_preview", "")[:80]
            line_count = bullet.get("line_count", 0)
            utilization = bullet.get("last_line_utilization_percent", 0) if bullet.get("last_line_utilization_percent") else 0
            target_lines = max(1, line_count - 1)
            lines.append(f"  Secondary {i}: {line_count} lines -> target {target_lines} lines (utilization: {utilization:.1f}%)")
            lines.append(f"    '{text_preview}...'")
            lines.append(f"    ACTION: Remove 10-15 words to reduce to {target_lines} line(s)")
        if len(secondary_targets) > 10:
            lines.append(f"    ... and {len(secondary_targets) - 10} more bullets to condense")
        lines.append("")
    
    return "\n".join(lines)


def analyze_layout(
    pdf_bytes: bytes,
    detail_level: int = 1,
    current_pages: int = 1,
    target_pages: int = 1,
    latex: Optional[str] = None,
) -> str:
    """Main function to analyze PDF layout and return formatted feedback.
    
    Args:
        pdf_bytes: PDF file as bytes.
        detail_level: Level of detail (1=basic, 2=section-level, 3=full).
        current_pages: Current page count.
        target_pages: Target page count.
        latex: Optional LaTeX source code for more accurate bullet detection.
        
    Returns:
        Formatted layout feedback string.
    """
    # Extract all metrics
    bullet_metrics = extract_line_metrics(pdf_bytes, latex=latex)
    
    # Calculate content boundaries for whitespace utilization
    # Use same logic as notebook: detect actual content boundaries by finding leftmost/rightmost text
    # (excluding very short lines that might be bullets/markers)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    content_left = None
    content_right = None
    
    try:
        if len(doc) > 0:
            page = doc[0]
            text_dict = page.get_text("dict")
            
            # Find leftmost and rightmost content (excluding very short lines) - same as notebook
            for block in text_dict.get("blocks", []):
                if "lines" in block:
                    for line in block["lines"]:
                        if "spans" in line:
                            # Get full line text to filter out short lines
                            line_text = " ".join([span.get("text", "") for span in line.get("spans", [])]).strip()
                            # Skip very short lines (likely bullets/markers) - same logic as notebook
                            if len(line_text) > 3:
                                for span in line["spans"]:
                                    if "text" in span and span["text"].strip():
                                        bbox = span.get("bbox", [])
                                        if len(bbox) == 4:
                                            line_width = bbox[2] - bbox[0]
                                            # Skip very short lines (likely artifacts) - same as notebook
                                            if line_width > 20:
                                                if content_left is None or bbox[0] < content_left:
                                                    content_left = bbox[0]
                                                if content_right is None or bbox[2] > content_right:
                                                    content_right = bbox[2]
            
            # Fallback to page edges if we couldn't detect margins (before closing doc)
            if content_left is None or content_right is None:
                page = doc[0]
                page_rect = page.rect
                if content_left is None:
                    content_left = page_rect.x0 + 36  # Typical left margin
                if content_right is None:
                    content_right = page_rect.x1 - 36  # Typical right margin
    finally:
        doc.close()
    
    # Calculate whitespace utilization for bullets
    # Utilization is based on how much of the available content width the LAST LINE uses
    # This matches the notebook logic: (last_line_x1 - last_line_x0) / (content_right - content_left) * 100
    logger = logging.getLogger(__name__)
    
    bullets = bullet_metrics.get("bullets", [])
    if content_left is not None and content_right is not None:
        available_width = content_right - content_left
        # Content boundaries calculated for layout analysis
        
        # Debug: Log first few bullets in detail
        for i, bullet in enumerate(bullets[:3], 1):
            last_line_x_end = bullet.get("last_line_x_end")
            last_line_x_start = bullet.get("last_line_x_start")
            x_start = bullet.get("x_start")
            line_count = bullet.get("line_count", 0)
            
            if last_line_x_end is not None and last_line_x_start is not None:
                # Calculate width of just the last line (not the entire bullet)
                used_width = last_line_x_end - last_line_x_start
                utilization_percent = (used_width / available_width) * 100 if available_width > 0 else 0
                whitespace_waste_percent = 100 - utilization_percent
                bullet["last_line_utilization_percent"] = utilization_percent
                bullet["whitespace_waste_percent"] = whitespace_waste_percent
                bullet["available_width"] = available_width
                bullet["used_width"] = used_width
                
                # Bullet metrics calculated for layout analysis
            else:
                # Missing last_line coordinates - using fallback
                pass
        
        # Calculate for all bullets (not just first 3)
        for bullet in bullets:
            last_line_x_end = bullet.get("last_line_x_end")
            last_line_x_start = bullet.get("last_line_x_start")
            if last_line_x_end is not None and last_line_x_start is not None:
                used_width = last_line_x_end - last_line_x_start
                utilization_percent = (used_width / available_width) * 100 if available_width > 0 else 0
                whitespace_waste_percent = 100 - utilization_percent
                bullet["last_line_utilization_percent"] = utilization_percent
                bullet["whitespace_waste_percent"] = whitespace_waste_percent
                bullet["available_width"] = available_width
                bullet["used_width"] = used_width
    
    analysis = {
        "bullets": bullets,
        "content_left": content_left,
        "content_right": content_right,
    }
    
    # Add section metrics for detail level 2+
    if detail_level >= 2:
        section_layout = analyze_section_layout(pdf_bytes)
        analysis["sections"] = section_layout.get("sections", [])
        analysis["page_height"] = section_layout.get("page_height", 0)
    
    # Add spacing metrics for detail level 3+
    if detail_level >= 3:
        spacing = analyze_spacing(pdf_bytes)
        analysis["spacing"] = spacing
    
    # Format and return
    return format_layout_feedback(
        analysis,
        detail_level=detail_level,
        current_pages=current_pages,
        target_pages=target_pages,
    )

