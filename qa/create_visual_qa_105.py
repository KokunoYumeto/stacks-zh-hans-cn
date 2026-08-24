from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path


QA = Path(__file__).resolve().parent
ROOT = QA.parent
PDF = ROOT / "build" / "stacks-zh-hans-cn-partial.pdf"
LOG = ROOT / "build" / "stacks-zh-hans-cn-partial.log"
MECHANICAL = QA / "pdf-mechanical-105.json"
RENDER_SUMMARY = QA / "visual" / "RENDER_SUMMARY_8C54DFF4.json"
RENDER_MANIFEST = QA / "visual" / "RENDER_MANIFEST_8C54DFF4.csv"
CONTACT_MANIFEST = QA / "visual" / "CONTACT_SHEETS_8C54DFF4.csv"
FULL_RES_SUMMARY = QA / "visual" / "FULL_RES_SUMMARY_8C54DFF4.json"
FULL_RES_MANIFEST = QA / "visual" / "FULL_RES_MANIFEST_8C54DFF4.csv"
TARGETS = QA / "VISUAL_TARGETS_8C54DFF4.json"
WARNING_MAP = QA / "WARNING_PAGE_MAP_8C54DFF4.json"
OUT = QA / "visual-qa-105.json"
REPORT = QA / "VISUAL_QA_8C54DFF4.md"

EXPECTED_PDF_SHA256 = "8C54DFF495B1642EB94828B192FFDF8A49A157E80FFE3CECC997356DB79A28FD"
EXPECTED_PAGES = 4877
EXPECTED_CONTACT_SHEETS = 244
EXPECTED_FULL_RES_TARGETS = 188
INSPECTED_AT = "2026-08-25T00:32:21+02:00"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def warning_count(log_text: str, pattern: str) -> int:
    return len(re.findall(pattern, log_text, flags=re.MULTILINE))


def main() -> int:
    mechanical = json.loads(MECHANICAL.read_text(encoding="utf-8"))
    rendered = json.loads(RENDER_SUMMARY.read_text(encoding="utf-8"))
    full_res = json.loads(FULL_RES_SUMMARY.read_text(encoding="utf-8"))
    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    warning_map = json.loads(WARNING_MAP.read_text(encoding="utf-8"))
    log_text = LOG.read_text(encoding="utf-8", errors="replace")

    pdf_hash = sha256(PDF)
    page_count = int(rendered["page_count"])
    if pdf_hash != EXPECTED_PDF_SHA256:
        raise ValueError(f"unexpected PDF hash: {pdf_hash}")
    if page_count != EXPECTED_PAGES or int(mechanical["pages"]) != EXPECTED_PAGES:
        raise ValueError("page-count mismatch")
    if not mechanical["passed_mechanical"] or not rendered["passed"] or not full_res["passed"]:
        raise ValueError("mechanical or render gate did not pass")
    if str(mechanical["pdf"]["sha256"]).upper() != pdf_hash:
        raise ValueError("mechanical audit binds another PDF")
    if str(full_res["pdf_sha256"]).upper() != pdf_hash or str(targets["pdf_sha256"]).upper() != pdf_hash:
        raise ValueError("full-resolution evidence binds another PDF")

    with CONTACT_MANIFEST.open("r", encoding="utf-8", newline="") as stream:
        contact_rows = list(csv.DictReader(stream))
    if len(contact_rows) != EXPECTED_CONTACT_SHEETS:
        raise ValueError("contact-sheet count mismatch")
    expected_first = 1
    for index, row in enumerate(contact_rows, start=1):
        first_page = int(row["first_page"])
        last_page = int(row["last_page"])
        if int(row["sheet"]) != index or first_page != expected_first or last_page < first_page:
            raise ValueError(f"contact-sheet coverage discontinuity at sheet {index}")
        expected_first = last_page + 1
    if expected_first != EXPECTED_PAGES + 1:
        raise ValueError("contact-sheet terminal coverage mismatch")

    with FULL_RES_MANIFEST.open("r", encoding="utf-8", newline="") as stream:
        full_res_rows = list(csv.DictReader(stream))
    full_res_pages = [int(row["page"]) for row in full_res_rows]
    selected_pages = [int(page) for page in targets["selected_pages"]]
    if len(full_res_rows) != EXPECTED_FULL_RES_TARGETS:
        raise ValueError("full-resolution target count mismatch")
    if full_res_pages != selected_pages or list(full_res["selected_pages"]) != selected_pages:
        raise ValueError("full-resolution render sequence differs from the selected target sequence")
    if int(warning_map["unmapped_count"]) != 0:
        raise ValueError("unmapped box-warning page remains")

    for stderr_name in ("render-105.stderr.txt", "contact-sheets-105.stderr.txt", "full-res-render-8C54DFF4.stderr.txt"):
        stderr_path = QA / stderr_name
        if not stderr_path.is_file() or stderr_path.stat().st_size != 0:
            raise ValueError(f"renderer stderr is missing or non-empty: {stderr_name}")

    warnings = {
        "tex_errors": warning_count(
            log_text,
            r"^! (?:LaTeX|Package .* Error|Class .* Error|Undefined control sequence|Missing .* inserted|Emergency stop|File .* not found|Fatal error)",
        ),
        "overfull_hbox_warnings": warning_count(log_text, r"Overfull \\hbox"),
        "underfull_hbox_warnings": warning_count(log_text, r"Underfull \\hbox"),
        "overfull_vbox_warnings": warning_count(log_text, r"Overfull \\vbox"),
        "underfull_vbox_warnings": warning_count(log_text, r"Underfull \\vbox"),
        "undefined_reference_warnings": warning_count(log_text, r"undefined references|Reference .* undefined"),
        "undefined_citation_warnings": warning_count(log_text, r"undefined citations|Citation .* undefined"),
        "label_rerun_warnings": warning_count(log_text, r"Label\(s\) may have changed|Rerun to get cross-references right"),
        "missing_character_warnings": warning_count(log_text, r"Missing character"),
        "fatal_errors": warning_count(log_text, r"Emergency stop|Fatal error"),
    }
    expected_warnings = {
        "tex_errors": 0,
        "overfull_hbox_warnings": 79,
        "underfull_hbox_warnings": 11,
        "overfull_vbox_warnings": 1,
        "underfull_vbox_warnings": 43,
        "undefined_reference_warnings": 0,
        "undefined_citation_warnings": 0,
        "label_rerun_warnings": 0,
        "missing_character_warnings": 0,
        "fatal_errors": 0,
    }
    if warnings != expected_warnings:
        raise ValueError(f"final-log warning drift: {warnings}")

    new_chapter_ranges = {
        str(chapter): f"{targets['chapter_ranges'][str(chapter)]['start']}-{targets['chapter_ranges'][str(chapter)]['end']}"
        for chapter in targets["new_chapters"]
    }
    result = {
        "schema": "stacks-zh-hans-cn-visual-qa/v7",
        "inspected_at": INSPECTED_AT,
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
            "page_sequence": "page-0001.png through page-4877.png",
            "total_bytes": rendered["total_bytes"],
            "dimensions_px": rendered["dimensions_px"],
            "ordered_page_hash_binding_sha256": rendered["ordered_page_hash_binding_sha256"],
            "manifest": {
                "path": "qa/visual/RENDER_MANIFEST_8C54DFF4.csv",
                "bytes": RENDER_MANIFEST.stat().st_size,
                "sha256": sha256(RENDER_MANIFEST),
            },
            "summary": {
                "path": "qa/visual/RENDER_SUMMARY_8C54DFF4.json",
                "bytes": RENDER_SUMMARY.stat().st_size,
                "sha256": sha256(RENDER_SUMMARY),
            },
        },
        "contact_sheet_evidence": {
            "count": EXPECTED_CONTACT_SHEETS,
            "page_coverage": "1-4877 without gaps",
            "manifest": {
                "path": "qa/visual/CONTACT_SHEETS_8C54DFF4.csv",
                "bytes": CONTACT_MANIFEST.stat().st_size,
                "sha256": sha256(CONTACT_MANIFEST),
            },
            "sheets_inspected": "1-244",
            "inspection_method": "direct original-detail inspection of every contact sheet in exact order",
            "review_allocations": [
                {"sheets": "1-122", "pages": "1-2440", "result": "pass"},
                {"sheets": "123-244", "pages": "2441-4877", "result": "pass"},
            ],
        },
        "full_resolution_evidence": {
            "dpi": full_res["render_dpi"],
            "target_count": EXPECTED_FULL_RES_TARGETS,
            "target_selection": "every mapped TeX box-warning page, every start/end boundary of the 30 chapters added since the 75-chapter release, and fixed cover/frontmatter/transition/terminal controls",
            "selected_pages": selected_pages,
            "ordered_page_hash_binding_sha256": full_res["ordered_page_hash_binding_sha256"],
            "manifest": {
                "path": "qa/visual/FULL_RES_MANIFEST_8C54DFF4.csv",
                "bytes": FULL_RES_MANIFEST.stat().st_size,
                "sha256": sha256(FULL_RES_MANIFEST),
            },
            "summary": {
                "path": "qa/visual/FULL_RES_SUMMARY_8C54DFF4.json",
                "bytes": FULL_RES_SUMMARY.stat().st_size,
                "sha256": sha256(FULL_RES_SUMMARY),
            },
            "targets": {
                "path": "qa/VISUAL_TARGETS_8C54DFF4.json",
                "bytes": TARGETS.stat().st_size,
                "sha256": sha256(TARGETS),
            },
            "warning_page_map": {
                "path": "qa/WARNING_PAGE_MAP_8C54DFF4.json",
                "bytes": WARNING_MAP.stat().st_size,
                "sha256": sha256(WARNING_MAP),
                "mapped_warning_records": len(warning_map["records"]),
                "unique_warning_pages": len(warning_map["unique_mapped_box_warning_pdf_pages"]),
                "unmapped_warnings": warning_map["unmapped_count"],
            },
            "inspection_method": "direct original-detail inspection of every 200-dpi target in exact manifest order",
            "review_allocations": [
                {"target_indices": "1-94", "page_envelope": "1-1691", "result": "pass"},
                {"target_indices": "95-188", "page_envelope": "1692-4877", "result": "pass"},
            ],
            "new_chapters": targets["new_chapters"],
            "new_chapter_physical_page_ranges": new_chapter_ranges,
        },
        "visual_findings": {
            "clipped_content": 0,
            "overlap": 0,
            "unintended_blank_pages": 0,
            "duplicate_pages": 0,
            "missing_glyph_boxes": 0,
            "malformed_diagrams": 0,
            "scale_or_centering_defects": 0,
            "unreadably_small_text": 0,
            "cover_toc_and_license": "pass",
            "body_readability": "pass; centered, page-filling A4 layout with readable mainland Simplified-Chinese scientific text",
            "chapter_transitions": "pass; sparse terminal-page whitespace is intentional and adjacent openings are intact",
            "new_chapters": "all 30 chapters added since the 75-chapter release passed complete-sheet and 200-dpi boundary review",
        },
        "mechanical_cross_check": {
            "named_destinations": mechanical["named_destinations"],
            "link_annotations": mechanical["annotations"]["total"],
            "malformed_link_rectangles": len(mechanical["annotations"]["malformed_rectangles"]),
            "zero_area_link_rectangles": len(mechanical["annotations"]["zero_area_rectangles"]),
            "out_of_page_link_rectangles": len(mechanical["annotations"]["out_of_page_rectangles"]),
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
            **warnings,
        },
        "adverse_evidence": [
            "The PDF is untagged: it has no StructTreeRoot or MarkInfo.",
            "Thirteen embedded legacy math/Xy-pic font subsets lack ToUnicode.",
            "The extracted text contains 184 literal double-question-mark pairs; deterministic source replay and the final TeX log show zero unresolved references, so these are preserved literal source placeholders rather than unresolved TeX references.",
            f"The final log retains {warnings['overfull_hbox_warnings']} overfull hbox, {warnings['underfull_hbox_warnings']} underfull hbox, {warnings['overfull_vbox_warnings']} overfull vbox, and {warnings['underfull_vbox_warnings']} underfull vbox warnings; every mapped warning page and all {page_count:,} rendered pages were visually reviewed, with no clipping or unreadable reflow.",
            "This producer/canon cumulative checkpoint does not claim independent Chinese-language certification; that limitation did not gate deterministic QA or release preparation.",
        ],
        "passed_visual": True,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    new_chapter_list = ", ".join(str(chapter) for chapter in targets["new_chapters"])
    report = f"""# Visual QA - Stacks Project zh-Hans-CN cumulative 105-chapter reader

- PDF: `{PDF.name}`
- Bytes: {PDF.stat().st_size:,}
- SHA-256: `{pdf_hash}`
- Pages: {page_count:,} A4
- Complete render: Poppler 24.04.0 at 100 dpi, pages 1-4877, ordered binding `{rendered['ordered_page_hash_binding_sha256']}`
- Contact sheets: {EXPECTED_CONTACT_SHEETS}, covering every page without gaps
- Full-resolution targets: {EXPECTED_FULL_RES_TARGETS} at 200 dpi, ordered binding `{full_res['ordered_page_hash_binding_sha256']}`

## Inspection result

Every contact sheet was directly inspected at original detail in exact order: sheets 1-122 (pages 1-2440) and sheets 123-244 (pages 2441-4877). Every 200-dpi target was also directly inspected in exact manifest order: targets 1-94 and 95-188. The target set covers all {len(warning_map['unique_mapped_box_warning_pdf_pages'])} mapped box-warning pages, the physical start/end boundaries of newly added Chapters {new_chapter_list}, and fixed cover/frontmatter/transition/terminal controls.

Result: **PASS**. No clipping, overlap, unintended blank or duplicate page, missing-glyph box, malformed diagram, scale/centering defect, or unreadably small text was found. Sparse chapter-ending whitespace is intentional, and adjacent chapter openings remain intact.

## Mechanical cross-check

- Named destinations: {mechanical['named_destinations']:,}
- Link annotations: {mechanical['annotations']['total']:,}; malformed, zero-area, and out-of-page rectangles: 0
- Fonts: {mechanical['fonts']['embedded']}/{mechanical['fonts']['total']} embedded; {mechanical['fonts']['with_to_unicode']} with ToUnicode
- Extracted text: {mechanical['text_extraction']['characters']:,} characters, including {mechanical['text_extraction']['cjk_unified_ideographs']:,} CJK unified ideographs; replacement characters: 0
- Final-log undefined references, citations, label-rerun warnings, missing characters, fatal errors, and TeX errors: 0

## Adverse evidence retained

The PDF is untagged. Thirteen embedded legacy math/Xy-pic font subsets lack ToUnicode. The 184 literal `??` pairs are preserved source placeholders; deterministic source replay and the final TeX log contain zero unresolved references. The final log retains {warnings['overfull_hbox_warnings']} overfull hbox, {warnings['underfull_hbox_warnings']} underfull hbox, {warnings['overfull_vbox_warnings']} overfull vbox, and {warnings['underfull_vbox_warnings']} underfull vbox warnings, but direct inspection of every mapped warning page and every rendered page found no clipping or unreadable reflow. This producer/canon checkpoint does not claim independent Chinese-language certification; that limitation did not gate deterministic QA or release preparation.
"""
    REPORT.write_text(report, encoding="utf-8", newline="\n")
    print(json.dumps({"path": str(OUT), "bytes": OUT.stat().st_size, "sha256": sha256(OUT), "passed_visual": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
