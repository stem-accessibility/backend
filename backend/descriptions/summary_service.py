from __future__ import annotations

from typing import Any, Dict, Optional, Union
import json
import os
import re

from backend import llm

Json = Dict[str, Any]


# ---------- helpers ----------
def extract_json_fenced(text: str) -> Dict[str, Any]:
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if not m:
        raw = text.strip()
        if raw.startswith("{") and raw.endswith("}"):
            return json.loads(raw)
        raise ValueError("No ```json fenced block found (and not raw JSON).")
    return json.loads(m.group(1))


def normalize_section_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def build_long_markdown_from_sections(sections: Dict[str, str]) -> str:
    ordered = [
        ("Purpose", sections.get("purpose", "")),
        ("Structure", sections.get("structure", "")),
        ("Key Components", sections.get("keyComponents", "")),
        ("Traversal", sections.get("traversal", "")),
        ("Main Takeaway", sections.get("mainTakeaway", "")),
    ]

    parts = []
    for heading, text in ordered:
        text = normalize_section_text(text)
        if text:
            parts.append(f"## {heading}\n{text}")

    return "\n\n".join(parts).strip() + ("\n" if parts else "")


# ---------- LLM generation ----------
def llm_generate_accessible_summary(
    *,
    diagram_json: Json,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    json_payload = json.dumps(diagram_json, ensure_ascii=False, indent=2)

    prompt = f"""
You are an accessibility writing assistant that writes long textual descriptions of diagrams for blind and low vision readers.

Your goal is to help the reader understand the diagram’s meaning, structure, and logic without seeing it. Help the reader build a clear mental model of how the diagram works.

WRITING RULES
- Focus on meaning over appearance
- Use plain language and short, direct sentences
- Write at about a Grade 8–9 reading level
- Prefer active voice
- Use common words instead of formal or academic ones
- Keep each sentence focused on one idea
- Avoid repetition
- If the diagram is simple, keep the writing simple
- Prioritize clarity and usefulness over sounding polished

STYLE PREFERENCES
- Prefer words like "shows," "uses," "includes," "leads to," and "supports"
- Avoid words like "illustrates," "features," "collectively," "adequate," "composed of," "contributes to," and "overall concept" unless truly necessary
- Avoid long or layered sentences
- Avoid abstract summary language when more concrete wording is possible

TASK
Return ONLY a JSON object in a ```json code fence``` with this exact structure:

{{
  "long_description_sections": {{
    "purpose": "string",
    "structure": "string",
    "keyComponents": "string",
    "traversal": "string",
    "mainTakeaway": "string"
  }},
  "alt_text": "2-3 sentences: what the diagram is and covers, then the main takeaway from mainTakeaway above"
}}

Write the long_description_sections first and alt_text last, so alt_text can reuse the mainTakeaway.

REQUIREMENTS
- alt_text must be 2-3 short sentences and should not start with "Image of"
- alt_text MUST end with the main takeaway: its last sentence restates mainTakeaway in one short
  sentence. The earlier sentence(s) say what kind of diagram it is and what it covers. A reader who
  only hears the alt text should still learn the most important point.
- long_description_sections must use the exact five keys above
- Use the actual concept names from the diagram
- Do not invent missing nodes, edges, labels, or categories
- Only mention layout, shapes, or position if needed for understanding
- Keep the writing concrete, readable, and concise

OUTPUT FORMAT FOR SECTIONS

PURPOSE:
Explain what the diagram is meant to communicate in 1–2 short sentences.

STRUCTURE:
Describe the diagram type and high-level organization in 1–3 short sentences. Explain how the information is grouped using the actual concepts in the diagram. Use plain language but avoid generic phrases. Include the main categories or ideas by name. Only mention visual layout, shapes, or position if they help the reader understand the diagram.

KEY COMPONENTS:
List the main ideas or categories in the diagram and briefly explain what each one represents.
When helpful, group smaller supporting items under the larger category they belong to instead of listing every item separately.
Use short, simple entries.

TRAVERSAL:
Explain how the parts connect and how the reader can mentally move through the diagram. Focus on how smaller ideas build into larger ones, or how categories support the main concept. Do not simply repeat the component list.

MAIN TAKEAWAY:
Summarize the most important idea the reader should leave with in 1–2 short, clear sentences.

Diagram JSON:
{json_payload}
""".strip()

    raw = llm.complete(
        prompt,
        model=model or llm.MODEL_SUMMARY,
        json_mode=True,
        temperature=0.2,
        max_tokens=1800,
    )
    parsed = extract_json_fenced(raw)

    sections = parsed.get("long_description_sections") or {}

    normalized_sections = {
        "purpose": normalize_section_text(sections.get("purpose")),
        "structure": normalize_section_text(sections.get("structure")),
        "keyComponents": normalize_section_text(sections.get("keyComponents")),
        "traversal": normalize_section_text(sections.get("traversal")),
        "mainTakeaway": normalize_section_text(sections.get("mainTakeaway")),
    }

    return {
        "alt_text": normalize_section_text(parsed.get("alt_text")),
        "long_description_sections": normalized_sections,
        "long_markdown": build_long_markdown_from_sections(normalized_sections),
    }


# ---------- main orchestration ----------
def generate_summary_bundle(
    *,
    diagram_json: Union[Json, str],
    model: Optional[str] = None,
) -> Dict[str, Any]:
    if isinstance(diagram_json, str):
        diagram_obj = json.loads(diagram_json)
    else:
        diagram_obj = diagram_json

    llm_bits = llm_generate_accessible_summary(
        diagram_json=diagram_obj,
        model=model,
    )

    return {
        "short_alt": llm_bits["alt_text"],
        "long_description_sections": llm_bits["long_description_sections"],
        "long_markdown": llm_bits["long_markdown"],
    }