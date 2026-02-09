"""DOCX to LaTeX conversion using python-docx and OpenAI.

Pipeline (Option D):
  1. python-docx extracts structured content from the .docx file.
  2. An LLM classifies that content into a structured JSON schema
     (section types, entry fields) — one cheap call.
  3. A deterministic Python renderer converts the JSON into LaTeX
     with pre-tuned templates.
  4. A binary-search page-fitting loop adjusts spacing and recompiles
     locally (no extra LLM calls).
"""

import io
import json
import logging
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from openai import OpenAI

from tailor_tom.config import settings
from tailor_tom.resume_renderer import fit_to_pages

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1: Extract structured content from .docx
# ---------------------------------------------------------------------------


def extract_content_from_docx(docx_bytes: bytes) -> dict:
    """Parse a .docx file and extract structured content with formatting metadata.

    Args:
        docx_bytes: Raw bytes of the .docx file.

    Returns:
        A dict with keys:
          - elements: list of element dicts (paragraph/table) in document order
          - raw_text: plain-text concatenation of all content
    """
    doc = Document(io.BytesIO(docx_bytes))

    elements: list[dict] = []
    raw_text_parts: list[str] = []

    # Process paragraphs and tables in document order
    for block in _iter_block_items(doc):
        if block["type"] == "paragraph":
            para = block["element"]
            para_data = _extract_paragraph(para)
            if para_data:
                elements.append(para_data)
                raw_text_parts.append(para_data["text"])

        elif block["type"] == "table":
            table = block["element"]
            table_data = _extract_table(table)
            if table_data:
                elements.append(table_data)
                for row in table_data["rows"]:
                    for cell in row:
                        raw_text_parts.append(cell["text"])

    return {
        "elements": elements,
        "raw_text": "\n".join(raw_text_parts),
    }


def _iter_block_items(doc: Document) -> list[dict]:
    """Iterate over paragraphs and tables in document body order."""
    items = []
    body = doc.element.body
    for child in body:
        if child.tag == qn("w:p"):
            # Find the matching paragraph object
            for para in doc.paragraphs:
                if para._element is child:
                    items.append({"type": "paragraph", "element": para})
                    break
        elif child.tag == qn("w:tbl"):
            for table in doc.tables:
                if table._element is child:
                    items.append({"type": "table", "element": table})
                    break
    return items


def _extract_paragraph(para) -> Optional[dict]:
    """Extract a single paragraph with formatting metadata, including tab stops."""
    text = para.text.strip()
    if not text:
        return None

    # Determine alignment
    alignment = "left"
    if para.alignment == WD_ALIGN_PARAGRAPH.CENTER:
        alignment = "center"
    elif para.alignment == WD_ALIGN_PARAGRAPH.RIGHT:
        alignment = "right"

    # Detect style (heading, list item, normal)
    style_name = para.style.name if para.style else "Normal"
    is_heading = style_name.startswith("Heading")
    heading_level = 0
    if is_heading:
        try:
            heading_level = int(style_name.replace("Heading", "").strip())
        except ValueError:
            heading_level = 1

    is_list = style_name.startswith("List") or "bullet" in style_name.lower()

    # Extract tab stop definitions from paragraph format (right/center/left tabs)
    tab_stop_type = _get_tab_stop_alignment(para)

    # Extract runs with formatting, detecting tab characters from XML
    runs = []
    has_tabs = False
    for run_element in para._element.findall(qn("w:r")):
        # Check for tab characters (<w:tab/>) inside this run
        for child in run_element:
            if child.tag == qn("w:tab"):
                has_tabs = True
                runs.append({"text": "\t", "tab": True})
            elif child.tag == qn("w:t"):
                run_text = child.text or ""
                if not run_text:
                    continue
                # Get formatting from the run's properties
                run_obj = None
                for r in para.runs:
                    if r._element is run_element:
                        run_obj = r
                        break
                run_data: dict = {"text": run_text}
                if run_obj:
                    if run_obj.bold:
                        run_data["bold"] = True
                    if run_obj.italic:
                        run_data["italic"] = True
                    if run_obj.underline:
                        run_data["underline"] = True
                    if run_obj.font.size:
                        run_data["font_size_pt"] = run_obj.font.size.pt
                    if run_obj.font.name:
                        run_data["font_name"] = run_obj.font.name
                runs.append(run_data)

    result = {
        "type": "paragraph",
        "text": text,
        "alignment": alignment,
        "style": style_name,
        "is_heading": is_heading,
        "heading_level": heading_level,
        "is_list": is_list,
        "runs": runs,
    }

    if has_tabs and tab_stop_type:
        result["tab_alignment"] = tab_stop_type

    return result


def _get_tab_stop_alignment(para) -> Optional[str]:
    """Get the alignment type of the first tab stop defined on a paragraph.

    Returns 'right', 'center', or None if no tab stops defined.
    """
    pPr = para._element.find(qn("w:pPr"))
    if pPr is None:
        return None
    tabs = pPr.find(qn("w:tabs"))
    if tabs is None:
        return None
    for tab in tabs.findall(qn("w:tab")):
        val = tab.get(qn("w:val"))
        if val in ("right", "center"):
            return val
    return None


def _extract_table(table) -> Optional[dict]:
    """Extract a table with cell content and formatting."""
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            cell_text = cell.text.strip()
            # Get alignment from the first paragraph in the cell
            alignment = "left"
            if cell.paragraphs:
                first_para = cell.paragraphs[0]
                if first_para.alignment == WD_ALIGN_PARAGRAPH.CENTER:
                    alignment = "center"
                elif first_para.alignment == WD_ALIGN_PARAGRAPH.RIGHT:
                    alignment = "right"
            cells.append({"text": cell_text, "alignment": alignment})
        rows.append(cells)

    # Skip empty tables
    if not any(cell["text"] for row in rows for cell in row):
        return None

    return {
        "type": "table",
        "rows": rows,
        "num_rows": len(rows),
        "num_cols": len(rows[0]) if rows else 0,
    }


# ---------------------------------------------------------------------------
# Step 2: Classify content into structured JSON via LLM
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a resume content classifier. Given structured text extracted from a \
.docx file, output a JSON object matching the schema below. Output ONLY valid \
JSON — no explanations, no markdown fences.

SCHEMA:
{
  "header": {
    "name": "Full Name",
    "contact_items": [{"text": "visible text", "url": "optional URL or empty"}]
  },
  "sections": [
    {
      "title": "Section Title",
      "type": "entry_list | skills | text",
      "entries": [{"primary":"Org","secondary":"Role","location":"City, ST",\
"dates":"Start - End","bullets":["..."]}],
      "items": [{"label":"Category","value":"item1, item2"}],
      "content": "freeform text"
    }
  ]
}

SECTION TYPES:
- "entry_list": Experience, Education, Projects, Awards, Certifications — \
anything with entries that have a primary title, optional subtitle/location/\
dates, and optional bullets.
- "skills": Label-value pairs (Technical Skills, Languages, etc.).
- "text": Free-form paragraph (Summary, Objective, etc.).

Include only the fields relevant to the chosen type (entries for entry_list, \
items for skills, content for text).

RULES:
- Preserve ALL text EXACTLY. Do not rephrase or omit anything.
- Bold text is usually primary (company/school name).
- Italic text is usually secondary (role/degree).
- [RIGHT-ALIGNED] text is usually dates or location.
- [TAB] separates left and right content in the same line.
- Tables at the top of the document are usually contact info.
- Bullet items go in the "bullets" array.
- For contact items, infer URLs: emails -> mailto:, linkedin/github -> https://
- Join split fragments (e.g. "Jan 20" + "25" -> "Jan 2025")."""


def generate_latex_from_docx(
    structured_content: dict,
    target_pages: int = 1,
    max_retries: int = 2,
) -> tuple[str, bytes]:
    """Generate LaTeX from structured .docx content.

    Pipeline:
      1. LLM classifies extracted content into structured JSON (one call).
      2. Deterministic renderer converts JSON to LaTeX.
      3. Binary-search page fitting via local compilation (no extra LLM calls).

    Args:
        structured_content: Output from ``extract_content_from_docx()``.
        target_pages: Desired number of pages.
        max_retries: Max LLM classification attempts.

    Returns:
        Tuple of ``(latex_string, compiled_pdf_bytes)``.

    Raises:
        RuntimeError: If conversion fails after all retries.
    """
    client = OpenAI(api_key=settings.openai_api_key)

    # Use the same model configured for the rest of the app
    model = settings.model_name
    if model.startswith("openai/"):
        model = model[len("openai/"):]

    # Format the structured content as a readable string for the LLM
    content_description = _format_content_for_llm(structured_content)

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Classify this resume content into the JSON schema:\n\n"
                + content_description
            ),
        },
    ]

    last_error = ""

    for attempt in range(1, max_retries + 1):
        logger.info("DOCX->JSON classification attempt %d/%d", attempt, max_retries)

        # --- Call LLM -------------------------------------------------------
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=4000,
                response_format={"type": "json_object"},
            )
            raw_output = response.choices[0].message.content or ""
        except Exception as e:
            logger.error("OpenAI API error on attempt %d: %s", attempt, e)
            last_error = str(e)
            continue

        # --- Parse JSON -----------------------------------------------------
        try:
            resume_json = _extract_json_from_response(raw_output)
            resume_json = _validate_resume_json(resume_json)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("JSON parsing failed on attempt %d: %s", attempt, e)
            last_error = str(e)
            messages.append({"role": "assistant", "content": raw_output})
            messages.append({
                "role": "user",
                "content": "Invalid JSON. Output ONLY valid JSON matching the schema.",
            })
            continue

        # --- Render + page-fit (deterministic, no LLM) ----------------------
        try:
            latex, pdf_bytes = fit_to_pages(resume_json, target_pages)
            logger.info("DOCX->LaTeX conversion succeeded on attempt %d", attempt)
            return latex, pdf_bytes
        except RuntimeError as e:
            logger.error("Rendering/compilation failed: %s", e)
            last_error = str(e)
            raise

    raise RuntimeError(
        f"DOCX to LaTeX conversion failed after {max_retries} attempts. "
        f"Last error: {last_error}"
    )


def _format_content_for_llm(structured_content: dict) -> str:
    """Format extracted .docx content into a readable description for the LLM."""
    lines: list[str] = []
    lines.append("=== DOCUMENT CONTENT ===\n")

    for i, elem in enumerate(structured_content.get("elements", [])):
        if elem["type"] == "paragraph":
            prefix = ""
            if elem.get("is_heading"):
                prefix = f"[HEADING level={elem['heading_level']}] "
            elif elem.get("is_list"):
                prefix = "[BULLET] "

            alignment_tag = ""
            if elem.get("alignment") != "left":
                alignment_tag = f" (align: {elem['alignment']})"

            # Determine tab alignment for this paragraph
            tab_align = elem.get("tab_alignment")  # "right", "center", or None

            # Show runs with formatting info, representing tabs
            formatted_runs = []
            for run in elem.get("runs", []):
                if run.get("tab"):
                    # Represent tab as alignment marker
                    if tab_align == "right":
                        formatted_runs.append(" [RIGHT-ALIGNED] ")
                    elif tab_align == "center":
                        formatted_runs.append(" [CENTER-ALIGNED] ")
                    else:
                        formatted_runs.append(" [TAB] ")
                    continue

                text = run["text"]
                modifiers = []
                if run.get("bold"):
                    modifiers.append("BOLD")
                if run.get("italic"):
                    modifiers.append("ITALIC")
                if run.get("underline"):
                    modifiers.append("UNDERLINE")

                if modifiers:
                    formatted_runs.append(f"[{','.join(modifiers)}]{text}[/]")
                else:
                    formatted_runs.append(text)

            run_text = "".join(formatted_runs)
            lines.append(f"{prefix}{run_text}{alignment_tag}")

        elif elem["type"] == "table":
            lines.append(f"\n[TABLE {elem['num_rows']}x{elem['num_cols']}]")
            for row in elem.get("rows", []):
                cells = []
                for cell in row:
                    align_note = f" (align:{cell['alignment']})" if cell.get("alignment") != "left" else ""
                    cells.append(f"{cell['text']}{align_note}")
                lines.append(" | ".join(cells))
            lines.append("[/TABLE]\n")

    return "\n".join(lines)


def _extract_json_from_response(raw: str) -> dict:
    """Extract and parse JSON from the LLM response."""
    raw = raw.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        first_newline = raw.index("\n") if "\n" in raw else len(raw)
        raw = raw[first_newline + 1:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try to locate a JSON object in the response
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response: {raw[:200]}")


def _validate_resume_json(data: dict) -> dict:
    """Validate and normalise the resume JSON to match the expected schema."""
    if not isinstance(data, dict):
        raise ValueError("Resume JSON must be a dict")

    # Header
    header = data.get("header", {})
    if not isinstance(header, dict):
        header = {}
    header.setdefault("name", "")
    header.setdefault("contact_items", [])
    data["header"] = header

    # Sections
    sections = data.get("sections", [])
    if not isinstance(sections, list):
        sections = []

    validated: list[dict] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        stype = section.get("type", "entry_list")
        if stype not in ("entry_list", "skills", "text"):
            stype = "entry_list"
        section["type"] = stype
        section.setdefault("title", "")

        if stype == "entry_list":
            entries = section.get("entries", [])
            if not isinstance(entries, list):
                entries = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                entry.setdefault("primary", "")
                entry.setdefault("secondary", "")
                entry.setdefault("location", "")
                entry.setdefault("dates", "")
                entry.setdefault("bullets", [])
            section["entries"] = [e for e in entries if isinstance(e, dict)]
        elif stype == "skills":
            section.setdefault("items", [])
        elif stype == "text":
            section.setdefault("content", "")

        validated.append(section)

    data["sections"] = validated
    return data
