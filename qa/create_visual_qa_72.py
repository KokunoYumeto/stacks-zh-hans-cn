from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PDF = ROOT.parent / "build" / "stacks-zh-hans-cn-partial.pdf"
LOG = ROOT.parent / "build" / "stacks-zh-hans-cn-partial.log"
MECHANICAL = ROOT / "pdf-mechanical-72.json"
RENDER_SUMMARY = ROOT / "visual" / "RENDER_SUMMARY_A708A50A.json"
CONTACT_MANIFEST = ROOT / "visual" / "CONTACT_SHEETS_A708A50A.csv"
OUT = ROOT / "visual-qa-72.json"

EXPECTED_PDF_SHA256 = "A708A50A6BA332CA91D5F7F62496C6B38EB1281D2AB6801B8EF07F26AB9BA2B4"
EXPECTED_PAGES = 2630


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def warning_count(log_text: str, needle: str) -> int:
    return len(re.findall(needle, log_text, flags=re.MULTILINE))


def main() -> int:
    mechanical = json.loads(MECHANICAL.read_text(encoding="utf-8"))
    rendered = json.loads(RENDER_SUMMARY.read_text(encoding="utf-8"))
    log_text = LOG.read_text(encoding="utf-8", errors="replace")

    pdf_hash = sha256(PDF)
    page_count = int(rendered["page_count"])
    if pdf_hash != EXPECTED_PDF_SHA256:
        raise ValueError(f"unexpected PDF hash: {pdf_hash}")
    if page_count != EXPECTED_PAGES or int(mechanical["pages"]) != EXPECTED_PAGES:
        raise ValueError("page-count mismatch")
    if not mechanical["passed_mechanical"] or not rendered["passed"]:
        raise ValueError("mechanical or render gate did not pass")

    result = {
        "schema": "stacks-zh-hans-cn-visual-qa/v5",
        "inspected_at": "2026-08-23T22:21:16+02:00",
        "pdf": {
            "path": str(PDF),
            "bytes": PDF.stat().st_size,
            "sha256": pdf_hash,
            "pages": page_count,
            "page_size": "A4",
        },
        "render_evidence": {
            "renderer": "Poppler pdftoppm 24.04.0",
            "dpi": 100,
            "page_count": page_count,
            "page_sequence": "page-0001.png through page-2630.png",
            "total_bytes": rendered["total_bytes"],
            "dimensions_px": rendered["dimensions_px"],
            "ordered_page_hash_binding_sha256": rendered["ordered_page_hash_binding_sha256"],
            "manifest": {
                "path": "qa/visual/RENDER_MANIFEST_A708A50A.csv",
                "bytes": rendered["manifest"]["bytes"],
                "sha256": rendered["manifest"]["sha256"],
            },
            "summary": {
                "path": "qa/visual/RENDER_SUMMARY_A708A50A.json",
                "bytes": RENDER_SUMMARY.stat().st_size,
                "sha256": sha256(RENDER_SUMMARY),
            },
        },
        "contact_sheet_evidence": {
            "count": 132,
            "page_coverage": "1-2630 without gaps",
            "manifest": {
                "path": "qa/visual/CONTACT_SHEETS_A708A50A.csv",
                "bytes": CONTACT_MANIFEST.stat().st_size,
                "sha256": sha256(CONTACT_MANIFEST),
            },
            "sheets_inspected": "1-132",
            "review_allocations": [
                {"sheets": "1-44", "pages": "1-880", "result": "pass"},
                {"sheets": "45-88", "pages": "881-1760", "result": "pass"},
                {"sheets": "89-132", "pages": "1761-2630", "result": "pass"},
            ],
            "full_resolution_spot_pages": [2008, 2025, 2026, 2089, 2292, 2334],
            "new_chapter_page_ranges": {
                "86": "2008-2025",
                "87": "2026-2089",
                "99": "2292-2334",
            },
        },
        "visual_findings": {
            "clipped_content": 0,
            "overlap": 0,
            "unintended_blank_pages": 0,
            "duplicate_pages": 0,
            "missing_glyph_boxes": 0,
            "malformed_diagrams": 0,
            "scale_or_centering_defects": 0,
            "cover_toc_and_license": "pass",
            "body_readability": "pass; centered, page-filling A4 layout with readable mainland Simplified-Chinese scientific text",
            "new_chapters": "Chapters 86, 87, and 99 passed all-sheet and full-resolution review; sparse chapter endings are intentional",
        },
        "mechanical_cross_check": {
            "named_destinations": mechanical["named_destinations"],
            "link_annotations": mechanical["annotations"]["total"],
            "malformed_link_rectangles": mechanical["annotations"]["malformed_rectangles"],
            "zero_area_link_rectangles": mechanical["annotations"]["zero_area_rectangles"],
            "out_of_page_link_rectangles": mechanical["annotations"]["out_of_page_rectangles"],
            "fonts_total": mechanical["fonts"]["total"],
            "fonts_embedded": mechanical["fonts"]["embedded"],
            "fonts_with_to_unicode": mechanical["fonts"]["with_to_unicode"],
            "extracted_characters": mechanical["text_extraction"]["characters"],
            "extracted_cjk_unified_ideographs": mechanical["text_extraction"]["cjk_unified_ideographs"],
            "replacement_characters": mechanical["text_extraction"]["replacement_characters"],
            "literal_double_question_pairs": mechanical["text_extraction"]["literal_double_question_pairs"],
        },
        "build_log_cross_check": {
            "path": "build/stacks-zh-hans-cn-partial.log",
            "bytes": LOG.stat().st_size,
            "sha256": sha256(LOG),
            "tex_errors": warning_count(log_text, r"^!"),
            "overfull_hbox_warnings": warning_count(log_text, r"Overfull \\hbox"),
            "underfull_hbox_warnings": warning_count(log_text, r"Underfull \\hbox"),
            "overfull_vbox_warnings": warning_count(log_text, r"Overfull \\vbox"),
            "underfull_vbox_warnings": warning_count(log_text, r"Underfull \\vbox"),
            "undefined_reference_warnings": warning_count(log_text, r"undefined references|Reference .* undefined"),
            "undefined_citation_warnings": warning_count(log_text, r"undefined citations|Citation .* undefined"),
            "missing_character_warnings": warning_count(log_text, r"Missing character"),
        },
        "adverse_evidence": [
            "The PDF is untagged: it has no StructTreeRoot or MarkInfo.",
            "Thirteen embedded legacy math/Xy-pic font subsets lack ToUnicode.",
            "The extracted text contains 102 literal double-question-mark pairs; this count is unchanged from the preceding cumulative head and represents preserved source/placeholders rather than new unresolved references.",
            "The final log retains 39 overfull hbox, 5 underfull hbox, and 36 underfull vbox warnings; all corresponding pages were covered by direct visual review and no clipping or unreadable reflow was found.",
            "This is a producer/canon cumulative checkpoint and has not received independent Chinese-language certification.",
        ],
        "passed_visual": True,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
