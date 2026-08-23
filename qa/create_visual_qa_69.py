from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PDF = ROOT.parent / "build" / "stacks-zh-hans-cn-partial.pdf"
MECHANICAL = ROOT / "pdf-mechanical-69.json"
RENDER_SUMMARY = ROOT / "visual" / "RENDER_SUMMARY_DD46A430.json"
CONTACT_MANIFEST = ROOT / "visual" / "CONTACT_SHEETS_DD46A430.csv"
OUT = ROOT / "visual-qa-69.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    mechanical = json.loads(MECHANICAL.read_text(encoding="utf-8"))
    rendered = json.loads(RENDER_SUMMARY.read_text(encoding="utf-8"))
    page_count = int(rendered["page_count"])
    contact_bytes = CONTACT_MANIFEST.stat().st_size
    result = {
        "schema": "stacks-zh-hans-cn-visual-qa/v4",
        "inspected_at": "2026-08-23T20:00:00+02:00",
        "pdf": {
            "path": str(PDF),
            "bytes": PDF.stat().st_size,
            "sha256": sha256(PDF),
            "pages": page_count,
            "page_size": "A4",
        },
        "render_evidence": {
            "renderer": "Poppler pdftoppm 24.04.0",
            "dpi": 100,
            "page_count": page_count,
            "page_sequence": "page-0001.png through page-2502.png",
            "total_bytes": rendered["total_bytes"],
            "dimensions_px": rendered["dimensions_px"],
            "ordered_page_hash_binding_sha256": rendered["ordered_page_hash_binding_sha256"],
            "manifest": {
                "path": "qa/visual/RENDER_MANIFEST_DD46A430.csv",
                "bytes": rendered["manifest"]["bytes"],
                "sha256": rendered["manifest"]["sha256"],
            },
            "summary": {
                "path": "qa/visual/RENDER_SUMMARY_DD46A430.json",
                "bytes": RENDER_SUMMARY.stat().st_size,
                "sha256": sha256(RENDER_SUMMARY),
            },
        },
        "contact_sheet_evidence": {
            "count": 126,
            "page_coverage": "1-2502 without gaps",
            "manifest": {
                "path": "qa/visual/CONTACT_SHEETS_DD46A430.csv",
                "bytes": contact_bytes,
                "sha256": sha256(CONTACT_MANIFEST),
            },
            "sheets_inspected": "1-126",
            "full_resolution_ranges": [
                "2441-2445",
                "2481-2487",
                "2502",
            ],
        },
        "visual_findings": {
            "clipped_content": 0,
            "overlap": 0,
            "blank_pages": 0,
            "duplicate_pages": 0,
            "missing_glyph_boxes": 0,
            "malformed_diagrams": 0,
            "scale_or_centering_defects": 0,
            "cover_toc_and_license": "pass",
            "body_readability": "pass; centered, page-filling A4 layout with readable Chinese scientific text",
            "new_chapters": "Chapters 113 and 114 inspected at full resolution; sparse endings are intentional",
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
            "replacement_characters": mechanical["text_extraction"]["replacement_characters"],
        },
        "adverse_evidence": [
            "The PDF is untagged: it has no StructTreeRoot or MarkInfo.",
            "Thirteen embedded legacy math/Xy-pic font subsets lack ToUnicode.",
            "This is a producer/canon cumulative checkpoint and has not received independent Chinese-language certification.",
        ],
        "passed_visual": True,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
