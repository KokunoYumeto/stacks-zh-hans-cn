from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


QA = Path(__file__).resolve().parent
ROOT = QA.parent
PDF = ROOT / "build" / "stacks-zh-hans-cn-partial.pdf"
LOG = ROOT / "build" / "stacks-zh-hans-cn-partial.log"
FLS = ROOT / "build" / "stacks-zh-hans-cn-partial.fls"
SOURCE_MANIFEST = ROOT / "manifest.json"
READER = ROOT / "src" / "reader.tex"
SOURCE_REPLAY = QA / "source-replay.json"
SOURCE_REPLAY_VERIFICATION = QA / "source-replay-verification-r14.json"
BUILD_RECEIPT = QA / "R14_BUILD_RECEIPT.json"
MECHANICAL = QA / "pdf-mechanical-112.json"
# POST-REPAIR IDENTITY PATCH POINT.  A rejected build must never remain bound here.
# This block binds the final repaired R14 bytes and their completed deterministic
# and explicit visual evidence.
EXPECTED_PDF_SHA256: str | None = "BB67A7AB0F7FDBA919E06DD1EAAA7F10E01EAD3116CA270FD339FD8516AD3A71"
EXPECTED_PDF_BYTES: int | None = 32_610_750
EXPECTED_PAGES = 5_546
EXPECTED_CHAPTERS = 112
EXPECTED_CONTACT_SHEETS = 278
EXPECTED_FULL_RES_TARGETS: int | None = 155
EXPECTED_WARNING_RECORDS: int | None = 135
EXPECTED_WARNING_PAGES: int | None = 128
EXPECTED_AUTHORITY_COMMIT = "a04446e57ec1fbc252a871afcec7752fb2807b14"

OUTPUT_STEM = EXPECTED_PDF_SHA256[:8] if EXPECTED_PDF_SHA256 else "UNBOUND"
TARGETS = QA / f"VISUAL_TARGETS_{OUTPUT_STEM}.json"
WARNING_MAP = QA / f"WARNING_PAGE_MAP_{OUTPUT_STEM}.json"

PAGE_DIR = QA / f"rendered-{OUTPUT_STEM}-100dpi"
RENDER_SUMMARY = QA / "visual" / f"RENDER_SUMMARY_{OUTPUT_STEM}.json"
RENDER_MANIFEST = QA / "visual" / f"RENDER_MANIFEST_{OUTPUT_STEM}.csv"
CONTACT_MANIFEST = QA / "visual" / f"CONTACT_SHEETS_{OUTPUT_STEM}.csv"
FULL_RES_DIR = QA / "visual" / f"full-res-{OUTPUT_STEM}"
FULL_RES_SUMMARY = QA / "visual" / f"FULL_RES_SUMMARY_{OUTPUT_STEM}.json"
FULL_RES_MANIFEST = QA / "visual" / f"FULL_RES_MANIFEST_{OUTPUT_STEM}.csv"
INSPECTION_RECEIPT = QA / "visual" / f"EXPLICIT_VISUAL_INSPECTION_{OUTPUT_STEM}.json"

RENDER_STDERR = QA / "visual" / f"render-{OUTPUT_STEM}.stderr.txt"
CONTACT_STDERR = QA / "visual" / f"contact-sheets-{OUTPUT_STEM}.stderr.txt"
FULL_RES_STDERR = QA / "visual" / f"full-res-render-{OUTPUT_STEM}.stderr.txt"

OUT = QA / "visual-qa-112.json"
REPORT = QA / f"VISUAL_QA_{OUTPUT_STEM}.md"

EXPECTED_STATIC_HASHES: dict[Path, str | None] = {
    SOURCE_MANIFEST: "252B14733A8F85EA675F0F807244814745320094B28642F6A80364CE1A10A019",
    READER: "F6F408A06BA08D1D879B68AD29E25839E7A9DF22B75D7D9679A4E56D84FAE7D6",
    SOURCE_REPLAY: "DE58B1ADE1E2BA38380A54727D94504A86E043D373E21C55C13D536BF2E1E475",
    SOURCE_REPLAY_VERIFICATION: "7251319ED6FA1F85E476B4EED2D56CAA892D8D5A62741E0C1678A8E1AACF5F44",
    BUILD_RECEIPT: "F20788C00BCDF13BB5CFA92F36508343A5C974AAFDFF4DACBCE261428E0BA6EA",
    MECHANICAL: "032D5CF2F8522F5EC9A76226575B7D6AE5103A1382DA6B111B20F66F30899B72",
    TARGETS: "C87D3E0AA053ED3408C020BB5EB20B0566DFC2B5FC7E3423A44FFDC14903A6A8",
    WARNING_MAP: "3C86400E17527AF4363D112D654FAFFC62E170EB9E44C2A203A9442C5502CCEE",
    LOG: "74DED9916674C2B4B1C42C1E92CD831E6293C7DAD77E97C05B63526EE09C6D4B",
    FLS: "847FD8DCE786F622887CF8D1E7B87427C9E51F1FC2293FAC86CC127905EE98B7",
}

EXPECTED_BLOCKING_COUNTS = {
    "true_tex_error_banners": 0,
    "fatal_errors": 0,
    "undefined_reference_warnings": 0,
    "undefined_citation_warnings": 0,
    "missing_character_warnings": 0,
    "invalid_character_warnings": 0,
    "rerun_requests": 0,
}

EXPECTED_NONBLOCKING_COUNTS: dict[str, int] | None = {
    "overfull_hbox_warnings": 0,
    "underfull_hbox_warnings": 0,
    "overfull_vbox_warnings": 0,
    "underfull_vbox_warnings": 0,
    "all_box_warnings": 135,
    "unique_mapped_box_warning_pdf_pages": 128,
    "latex_or_package_warning_blocks": 22,
    "amsmath_foreign_command": 2,
    "font_command_small_invalid_in_math_mode": 1,
    "hyperref_pdf_string_token_removed": 16,
    "latex_release_request_newer_than_available": 3,
    "line_start_bang_lines": 1,
    "rerunfilecheck_text_occurrences": 5,
}

REQUIRED_ZERO_FINDINGS = (
    "clipped_content",
    "overlap",
    "unintended_blank_pages",
    "duplicate_pages",
    "missing_glyph_boxes",
    "malformed_diagrams",
    "scale_or_centering_defects",
    "unreadably_small_text",
    "other_blocking_visual_defects",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def file_record(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": relative(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def resolve_record_path(value: object) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def assert_record(binding: object, path: Path, label: str) -> dict[str, object]:
    if not isinstance(binding, dict):
        raise RuntimeError(f"{label} is not a file binding")
    actual = file_record(path)
    if int(binding.get("bytes", -1)) != int(actual["bytes"]):
        raise RuntimeError(f"{label} byte-count drift")
    if str(binding.get("sha256", "")).upper() != actual["sha256"]:
        raise RuntimeError(f"{label} hash drift")
    if "path" not in binding or resolve_record_path(binding["path"]) != path.resolve():
        raise RuntimeError(f"{label} path drift")
    return actual


def require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = sha256(path)
    if actual != expected:
        raise RuntimeError(f"{label} identity drift: {actual}")


def validate_post_repair_binding() -> None:
    """Refuse to inspect any PDF until every final-build value is explicit."""
    missing: list[str] = []
    if EXPECTED_PDF_SHA256 is None:
        missing.append("EXPECTED_PDF_SHA256")
    else:
        try:
            if len(EXPECTED_PDF_SHA256) != 64:
                raise ValueError
            int(EXPECTED_PDF_SHA256, 16)
        except ValueError:
            missing.append("EXPECTED_PDF_SHA256(valid 64-hex value)")
    if EXPECTED_PDF_BYTES is None or EXPECTED_PDF_BYTES <= 0:
        missing.append("EXPECTED_PDF_BYTES")
    if EXPECTED_FULL_RES_TARGETS is None or EXPECTED_FULL_RES_TARGETS <= 0:
        missing.append("EXPECTED_FULL_RES_TARGETS")
    if EXPECTED_WARNING_RECORDS is None or EXPECTED_WARNING_RECORDS < 0:
        missing.append("EXPECTED_WARNING_RECORDS")
    if EXPECTED_WARNING_PAGES is None or EXPECTED_WARNING_PAGES < 0:
        missing.append("EXPECTED_WARNING_PAGES")
    for path, expected in EXPECTED_STATIC_HASHES.items():
        if expected is None:
            missing.append(f"EXPECTED_STATIC_HASHES[{relative(path)}]")
    if EXPECTED_NONBLOCKING_COUNTS is None:
        missing.append("EXPECTED_NONBLOCKING_COUNTS")
    if missing:
        raise RuntimeError(
            "post-repair visual-QA identity is intentionally unbound; patch only after "
            "the replacement PDF and receipts are stable: " + ", ".join(missing)
        )


def validate_static_inputs() -> dict[str, Any]:
    validate_post_repair_binding()
    if not PDF.is_file():
        raise FileNotFoundError(PDF)
    if PDF.stat().st_size != EXPECTED_PDF_BYTES:
        raise RuntimeError("R14 PDF byte-count drift")
    if sha256(PDF) != EXPECTED_PDF_SHA256:
        raise RuntimeError("R14 PDF identity drift")
    for path, expected in EXPECTED_STATIC_HASHES.items():
        require_hash(path, expected, relative(path))

    manifest = load_json(SOURCE_MANIFEST)
    replay = load_json(SOURCE_REPLAY)
    replay_check = load_json(SOURCE_REPLAY_VERIFICATION)
    build = load_json(BUILD_RECEIPT)
    mechanical = load_json(MECHANICAL)
    targets = load_json(TARGETS)
    warning_map = load_json(WARNING_MAP)

    if len(manifest.get("chapters", [])) != EXPECTED_CHAPTERS:
        raise RuntimeError("manifest chapter-count drift")
    if manifest.get("authority", {}).get("commit") != EXPECTED_AUTHORITY_COMMIT:
        raise RuntimeError("manifest authority commit drift")
    if replay.get("schema") != "stacks-zh-hans-cn-source-replay/v1":
        raise RuntimeError("unexpected source-replay schema")
    if replay.get("passed") is not True or int(replay.get("chapter_count", -1)) != EXPECTED_CHAPTERS:
        raise RuntimeError("source replay did not pass all 112 chapters")
    if replay.get("authority_commit") != EXPECTED_AUTHORITY_COMMIT:
        raise RuntimeError("source-replay authority commit drift")
    assert_record(replay.get("manifest"), SOURCE_MANIFEST, "source-replay manifest")

    if replay_check.get("schema") != "stacks-zh-hans-cn-source-replay-verification/v1":
        raise RuntimeError("unexpected source-replay verification schema")
    if replay_check.get("passed") is not True:
        raise RuntimeError("source-replay verification did not pass")
    if int(replay_check.get("chapter_count", -1)) != EXPECTED_CHAPTERS:
        raise RuntimeError("source-replay verification chapter-count drift")
    if int(replay_check.get("verified_input_bindings", -1)) != 345:
        raise RuntimeError("verified input-binding count drift")
    if int(replay_check.get("verified_generated_outputs", -1)) != 119:
        raise RuntimeError("verified generated-output count drift")
    if int(replay_check.get("unique_reference_targets", -1)) != 16_047:
        raise RuntimeError("unique reference-target count drift")
    if int(replay_check.get("unresolved_reference_targets", -1)) != 0:
        raise RuntimeError("unresolved source-replay targets remain")
    assert_record(replay_check.get("source_replay"), SOURCE_REPLAY, "verified source replay")
    assert_record(replay_check.get("manifest"), SOURCE_MANIFEST, "verified manifest")

    if build.get("schema") != "stacks-zh-hans-cn-r14-build-receipt/v1":
        raise RuntimeError("unexpected R14 build-receipt schema")
    if build.get("release_candidate") != "2026.08.26-r14":
        raise RuntimeError("R14 release-candidate drift")
    if build.get("authority_commit") != EXPECTED_AUTHORITY_COMMIT:
        raise RuntimeError("R14 build authority commit drift")
    if build.get("status") != "PASS" or build.get("passed") is not True:
        raise RuntimeError("R14 build receipt did not pass")
    source_bindings = build.get("source_bindings", {})
    if int(source_bindings.get("chapter_count", -1)) != EXPECTED_CHAPTERS:
        raise RuntimeError("R14 build chapter-count drift")
    assert_record(source_bindings.get("manifest"), SOURCE_MANIFEST, "build-bound manifest")
    assert_record(source_bindings.get("reader"), READER, "build-bound reader")
    assert_record(source_bindings.get("source_replay"), SOURCE_REPLAY, "build-bound source replay")
    assert_record(
        source_bindings.get("source_replay_verification"),
        SOURCE_REPLAY_VERIFICATION,
        "build-bound source-replay verification",
    )
    build_bindings = build.get("build_bindings", {})
    assert_record(build_bindings.get("pdf"), PDF, "build-bound PDF")
    if int(build_bindings["pdf"].get("pages", -1)) != EXPECTED_PAGES:
        raise RuntimeError("build-bound PDF page-count drift")
    assert_record(build_bindings.get("final_log"), LOG, "build-bound final log")
    assert_record(build_bindings.get("final_fls"), FLS, "build-bound final FLS")
    diagnostics = build.get("diagnostics", {})
    if diagnostics.get("blocking_condition_counts") != EXPECTED_BLOCKING_COUNTS:
        raise RuntimeError("R14 blocking diagnostic-count drift")
    if diagnostics.get("nonblocking_counts") != EXPECTED_NONBLOCKING_COUNTS:
        raise RuntimeError("R14 nonblocking diagnostic-count drift")

    if mechanical.get("schema") != "stacks-zh-hans-cn-pdf-audit/v1":
        raise RuntimeError("unexpected mechanical-QA schema")
    if mechanical.get("passed_mechanical") is not True:
        raise RuntimeError("mechanical QA did not pass")
    assert_record(mechanical.get("pdf"), PDF, "mechanically audited PDF")
    if int(mechanical.get("pages", -1)) != EXPECTED_PAGES:
        raise RuntimeError("mechanical page-count drift")
    if int(mechanical.get("expected_pages", -1)) != EXPECTED_PAGES:
        raise RuntimeError("mechanical expected-page count drift")
    if int(mechanical.get("fonts", {}).get("embedded", -1)) != int(
        mechanical.get("fonts", {}).get("total", -2)
    ):
        raise RuntimeError("not all fonts are embedded")
    annotations = mechanical.get("annotations", {})
    if (
        annotations.get("malformed_rectangles")
        or annotations.get("zero_area_rectangles")
        or annotations.get("out_of_page_rectangles")
    ):
        raise RuntimeError("invalid link rectangles remain")
    extraction = mechanical.get("text_extraction", {})
    if extraction.get("errors") or int(extraction.get("replacement_characters", -1)) != 0:
        raise RuntimeError("mechanical text extraction failed")

    if targets.get("schema") != "stacks-zh-hans-cn-visual-targets/v2":
        raise RuntimeError("unexpected visual-target schema")
    if str(targets.get("pdf_sha256", "")).upper() != EXPECTED_PDF_SHA256:
        raise RuntimeError("visual targets bind another PDF")
    if int(targets.get("page_count", -1)) != EXPECTED_PAGES:
        raise RuntimeError("visual-target page-count drift")
    selected_pages = [int(page) for page in targets.get("selected_pages", [])]
    if (
        int(targets.get("selected_page_count", -1)) != EXPECTED_FULL_RES_TARGETS
        or len(selected_pages) != EXPECTED_FULL_RES_TARGETS
    ):
        raise RuntimeError("visual-target count drift")
    if selected_pages != sorted(set(selected_pages)):
        raise RuntimeError("visual-target pages are not unique and strictly increasing")
    if selected_pages[0] != 1 or selected_pages[-1] != EXPECTED_PAGES:
        raise RuntimeError("visual-target terminal controls drift")
    assert_record(targets.get("warning_page_map"), WARNING_MAP, "target-bound warning map")

    if warning_map.get("schema") != "stacks-zh-hans-cn-warning-page-map/v3":
        raise RuntimeError("unexpected warning-page-map schema")
    if str(warning_map.get("pdf_sha256", "")).upper() != EXPECTED_PDF_SHA256:
        raise RuntimeError("warning-page map binds another PDF")
    if str(warning_map.get("log_sha256", "")).upper() != EXPECTED_STATIC_HASHES[LOG]:
        raise RuntimeError("warning-page map binds another final log")
    if int(warning_map.get("page_count", -1)) != EXPECTED_PAGES:
        raise RuntimeError("warning-page-map page-count drift")
    if int(warning_map.get("record_count", -1)) != EXPECTED_WARNING_RECORDS:
        raise RuntimeError("warning-page-map record-count drift")
    warning_pages = [int(page) for page in warning_map.get("unique_mapped_box_warning_pdf_pages", [])]
    if (
        int(warning_map.get("unique_mapped_box_warning_pdf_page_count", -1))
        != EXPECTED_WARNING_PAGES
        or len(warning_pages) != EXPECTED_WARNING_PAGES
    ):
        raise RuntimeError("warning-page-map unique-page count drift")
    if int(warning_map.get("unmapped_count", -1)) != 0:
        raise RuntimeError("unmapped box-warning page remains")
    if [int(page) for page in targets.get("box_warning_pages", [])] != warning_pages:
        raise RuntimeError("visual targets do not contain the exact warning-page sequence")

    return {
        "manifest": manifest,
        "replay": replay,
        "replay_check": replay_check,
        "build": build,
        "mechanical": mechanical,
        "targets": targets,
        "warning_map": warning_map,
        "selected_pages": selected_pages,
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def validate_render_evidence() -> tuple[dict[str, Any], list[dict[str, str]]]:
    summary = load_json(RENDER_SUMMARY)
    rows = read_csv(RENDER_MANIFEST)
    if summary.get("schema") != "stacks-zh-hans-cn-render-audit/v1":
        raise RuntimeError("unexpected complete-render summary schema")
    if summary.get("passed") is not True:
        raise RuntimeError("complete-render audit did not pass")
    if int(summary.get("render_dpi", -1)) != 100:
        raise RuntimeError("complete-render DPI drift")
    if (
        int(summary.get("page_count", -1)) != EXPECTED_PAGES
        or int(summary.get("expected_page_count", -1)) != EXPECTED_PAGES
    ):
        raise RuntimeError("complete-render page-count drift")
    if summary.get("first_file") != "page-0001.png" or summary.get("last_file") != "page-5546.png":
        raise RuntimeError("complete-render filename bounds drift")
    if summary.get("dimensions_px") != [[827, 1170]]:
        raise RuntimeError("complete-render dimensions drift")
    if "pdf_sha256" in summary and str(summary["pdf_sha256"]).upper() != EXPECTED_PDF_SHA256:
        raise RuntimeError("complete-render summary binds another PDF")
    assert_record(summary.get("manifest"), RENDER_MANIFEST, "complete-render manifest")
    if len(rows) != EXPECTED_PAGES:
        raise RuntimeError("complete-render manifest row-count drift")

    expected_names = [f"page-{page:04d}.png" for page in range(1, EXPECTED_PAGES + 1)]
    actual_paths = sorted(PAGE_DIR.glob("page-*.png"), key=lambda path: path.name)
    if [path.name for path in actual_paths] != expected_names:
        raise RuntimeError("complete-render page-file sequence drift")

    ordered_digest = hashlib.sha256()
    total_bytes = 0
    for page, row, path in zip(range(1, EXPECTED_PAGES + 1), rows, actual_paths, strict=True):
        if int(row.get("page", -1)) != page or row.get("filename") != path.name:
            raise RuntimeError(f"complete-render manifest sequence drift at page {page}")
        if (int(row.get("width_px", -1)), int(row.get("height_px", -1))) != (827, 1170):
            raise RuntimeError(f"complete-render dimensions drift at page {page}")
        if row.get("mode") != "RGB":
            raise RuntimeError(f"complete-render image-mode drift at page {page}")
        row_bytes = int(row.get("bytes", -1))
        if row_bytes <= 0 or path.stat().st_size != row_bytes:
            raise RuntimeError(f"complete-render byte-count drift at page {page}")
        row_hash = str(row.get("sha256", "")).upper()
        if len(row_hash) != 64 or any(character not in "0123456789ABCDEF" for character in row_hash):
            raise RuntimeError(f"invalid complete-render hash at page {page}")
        total_bytes += row_bytes
        ordered_digest.update(f"{page}\t{row_hash}\n".encode("ascii"))
    if total_bytes != int(summary.get("total_bytes", -1)):
        raise RuntimeError("complete-render total-byte drift")
    if ordered_digest.hexdigest().upper() != str(
        summary.get("ordered_page_hash_binding_sha256", "")
    ).upper():
        raise RuntimeError("complete-render ordered hash binding drift")
    return summary, rows


def validate_contact_evidence() -> list[dict[str, str]]:
    rows = read_csv(CONTACT_MANIFEST)
    if len(rows) != EXPECTED_CONTACT_SHEETS:
        raise RuntimeError("contact-sheet count drift")
    expected_first_page = 1
    for sheet, row in enumerate(rows, start=1):
        first_page = int(row.get("first_page", -1))
        last_page = int(row.get("last_page", -1))
        expected_last_page = min(sheet * 20, EXPECTED_PAGES)
        if int(row.get("sheet", -1)) != sheet:
            raise RuntimeError(f"contact-sheet index drift at sheet {sheet}")
        if first_page != expected_first_page or last_page != expected_last_page:
            raise RuntimeError(f"contact-sheet coverage drift at sheet {sheet}")
        expected_name = (
            f"sheet-{sheet:03d}-pages-{first_page:03d}-{last_page:03d}.jpg"
        )
        expected_path = resolve_record_path(row.get("path", ""))
        if expected_path.name != expected_name:
            raise RuntimeError(f"contact-sheet filename drift at sheet {sheet}")
        if not expected_path.is_file():
            raise FileNotFoundError(expected_path)
        if int(row.get("bytes", -1)) != expected_path.stat().st_size:
            raise RuntimeError(f"contact-sheet byte-count drift at sheet {sheet}")
        if str(row.get("sha256", "")).upper() != sha256(expected_path):
            raise RuntimeError(f"contact-sheet hash drift at sheet {sheet}")
        expected_first_page = last_page + 1
    if expected_first_page != EXPECTED_PAGES + 1:
        raise RuntimeError("contact sheets do not terminate on page 5546")
    return rows


def validate_full_res_evidence(
    selected_pages: list[int],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    summary = load_json(FULL_RES_SUMMARY)
    rows = read_csv(FULL_RES_MANIFEST)
    if summary.get("schema") != "stacks-zh-hans-cn-full-resolution-target-audit/v2":
        raise RuntimeError("unexpected full-resolution summary schema")
    if summary.get("passed") is not True:
        raise RuntimeError("full-resolution audit did not pass")
    if str(summary.get("pdf_sha256", "")).upper() != EXPECTED_PDF_SHA256:
        raise RuntimeError("full-resolution summary binds another PDF")
    assert_record(summary.get("pdf"), PDF, "full-resolution audited PDF")
    if int(summary.get("page_count", -1)) != EXPECTED_PAGES:
        raise RuntimeError("full-resolution PDF page-count drift")
    if int(summary.get("render_dpi", -1)) != 200:
        raise RuntimeError("full-resolution DPI drift")
    if summary.get("dimensions_px") != [[1654, 2339]] or summary.get("mode") != "RGB":
        raise RuntimeError("full-resolution image contract drift")
    if int(summary.get("selected_page_count", -1)) != EXPECTED_FULL_RES_TARGETS:
        raise RuntimeError("full-resolution target-count drift")
    if [int(page) for page in summary.get("selected_pages", [])] != selected_pages:
        raise RuntimeError("full-resolution summary target sequence drift")
    assert_record(summary.get("targets"), TARGETS, "full-resolution target receipt")
    assert_record(summary.get("manifest"), FULL_RES_MANIFEST, "full-resolution manifest")
    if len(rows) != EXPECTED_FULL_RES_TARGETS:
        raise RuntimeError("full-resolution manifest row-count drift")

    ordered_digest = hashlib.sha256()
    total_bytes = 0
    for index, (page, row) in enumerate(zip(selected_pages, rows, strict=True), start=1):
        expected_path = FULL_RES_DIR / f"page-{page:04d}.png"
        if int(row.get("page", -1)) != page or row.get("filename") != expected_path.name:
            raise RuntimeError(f"full-resolution target sequence drift at index {index}")
        if (int(row.get("width_px", -1)), int(row.get("height_px", -1))) != (1654, 2339):
            raise RuntimeError(f"full-resolution dimensions drift at target {index}")
        if row.get("mode") != "RGB":
            raise RuntimeError(f"full-resolution image-mode drift at target {index}")
        if not expected_path.is_file():
            raise FileNotFoundError(expected_path)
        row_bytes = int(row.get("bytes", -1))
        if row_bytes != expected_path.stat().st_size:
            raise RuntimeError(f"full-resolution byte-count drift at target {index}")
        row_hash = str(row.get("sha256", "")).upper()
        if row_hash != sha256(expected_path):
            raise RuntimeError(f"full-resolution hash drift at target {index}")
        total_bytes += row_bytes
        ordered_digest.update(f"{page}\t{row_hash}\n".encode("ascii"))
    if total_bytes != int(summary.get("total_bytes", -1)):
        raise RuntimeError("full-resolution total-byte drift")
    if ordered_digest.hexdigest().upper() != str(
        summary.get("ordered_page_hash_binding_sha256", "")
    ).upper():
        raise RuntimeError("full-resolution ordered hash binding drift")
    return summary, rows


def validate_inspection_ranges(
    ranges: object,
    *,
    total: int,
    first_key: str,
    last_key: str,
    endpoints: list[tuple[int, int]],
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(ranges, list) or not ranges:
        raise RuntimeError(f"{label} must be a non-empty list")
    expected_first = 1
    validated: list[dict[str, Any]] = []
    for position, value in enumerate(ranges, start=1):
        if not isinstance(value, dict):
            raise RuntimeError(f"{label} entry {position} is not an object")
        first = int(value.get(first_key, -1))
        last = int(value.get(last_key, -1))
        if first != expected_first or last < first or last > total:
            raise RuntimeError(f"{label} coverage drift at entry {position}")
        if int(value.get("first_page", -1)) != endpoints[first - 1][0]:
            raise RuntimeError(f"{label} first-page envelope drift at entry {position}")
        if int(value.get("last_page", -1)) != endpoints[last - 1][1]:
            raise RuntimeError(f"{label} last-page envelope drift at entry {position}")
        if value.get("result") != "pass":
            raise RuntimeError(f"{label} entry {position} did not pass")
        if value.get("blockers") != []:
            raise RuntimeError(f"{label} entry {position} has blockers")
        if value.get("evidence_mode") not in {
            "inherited_byte_identical",
            "reinspected_changed",
        }:
            raise RuntimeError(f"{label} entry {position} has an invalid evidence_mode")
        expected_first = last + 1
        validated.append(value)
    if expected_first != total + 1:
        raise RuntimeError(f"{label} does not cover the exact 1-{total} sequence")
    return validated


def validate_inspection_receipt(
    contact_rows: list[dict[str, str]],
    selected_pages: list[int],
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    receipt = load_json(INSPECTION_RECEIPT)
    if receipt.get("schema") != "stacks-zh-hans-cn-explicit-visual-inspection/v1":
        raise RuntimeError("unexpected explicit visual-inspection receipt schema")
    if receipt.get("performed") is not True or receipt.get("passed") is not True:
        raise RuntimeError("explicit visual inspection is not attested as performed and passed")
    if str(receipt.get("pdf_sha256", "")).upper() != EXPECTED_PDF_SHA256:
        raise RuntimeError("visual-inspection receipt binds another PDF")
    if int(receipt.get("page_count", -1)) != EXPECTED_PAGES:
        raise RuntimeError("visual-inspection receipt page-count drift")
    if int(receipt.get("contact_sheet_count", -1)) != EXPECTED_CONTACT_SHEETS:
        raise RuntimeError("visual-inspection receipt contact-sheet count drift")
    if int(receipt.get("full_resolution_target_count", -1)) != EXPECTED_FULL_RES_TARGETS:
        raise RuntimeError("visual-inspection receipt target-count drift")
    if receipt.get("blockers") != [] or int(receipt.get("blocker_count", -1)) != 0:
        raise RuntimeError("visual-inspection receipt contains blockers")
    inspection_id = receipt.get("inspection_id")
    if not isinstance(inspection_id, str) or not inspection_id.strip():
        raise RuntimeError("visual-inspection receipt needs a non-empty inspection_id")
    inspector = receipt.get("inspector")
    if not isinstance(inspector, dict):
        raise RuntimeError("visual-inspection receipt needs an inspector object")
    if inspector.get("kind") not in {"human", "agent"}:
        raise RuntimeError("inspector.kind must be human or agent")
    if not isinstance(inspector.get("id"), str) or not inspector["id"].strip():
        raise RuntimeError("inspector.id must be a non-empty opaque identifier")
    inspected_at = receipt.get("inspected_at")
    if not isinstance(inspected_at, str) or not inspected_at.strip():
        raise RuntimeError("visual-inspection receipt needs inspected_at")
    parsed_time = datetime.fromisoformat(inspected_at.replace("Z", "+00:00"))
    if parsed_time.tzinfo is None:
        raise RuntimeError("visual-inspection inspected_at must include a timezone")

    assert_record(
        receipt.get("contact_sheet_manifest"),
        CONTACT_MANIFEST,
        "inspection-bound contact-sheet manifest",
    )
    assert_record(
        receipt.get("full_resolution_manifest"),
        FULL_RES_MANIFEST,
        "inspection-bound full-resolution manifest",
    )
    contact_endpoints = [
        (int(row["first_page"]), int(row["last_page"])) for row in contact_rows
    ]
    target_endpoints = [(page, page) for page in selected_pages]
    contact_ranges = validate_inspection_ranges(
        receipt.get("contact_sheet_ranges"),
        total=EXPECTED_CONTACT_SHEETS,
        first_key="first_sheet",
        last_key="last_sheet",
        endpoints=contact_endpoints,
        label="contact_sheet_ranges",
    )
    full_resolution_ranges = validate_inspection_ranges(
        receipt.get("full_resolution_target_ranges"),
        total=EXPECTED_FULL_RES_TARGETS,
        first_key="first_target_index",
        last_key="last_target_index",
        endpoints=target_endpoints,
        label="full_resolution_target_ranges",
    )
    findings = receipt.get("findings")
    if not isinstance(findings, dict):
        raise RuntimeError("visual-inspection receipt needs a findings object")
    missing_findings = [key for key in REQUIRED_ZERO_FINDINGS if key not in findings]
    if missing_findings:
        raise RuntimeError(f"visual-inspection findings are missing: {missing_findings}")
    nonzero_findings = {
        key: findings[key] for key in REQUIRED_ZERO_FINDINGS if int(findings[key]) != 0
    }
    if nonzero_findings:
        raise RuntimeError(f"visual-inspection findings contain blockers: {nonzero_findings}")

    delta_inheritance = receipt.get("delta_inheritance")
    if not isinstance(delta_inheritance, dict):
        raise RuntimeError("visual-inspection receipt lacks delta_inheritance")
    delta_binding = delta_inheritance.get("receipt")
    if not isinstance(delta_binding, dict) or "path" not in delta_binding:
        raise RuntimeError("visual-inspection receipt lacks a bound delta receipt")
    delta_path = resolve_record_path(delta_binding["path"])
    assert_record(delta_binding, delta_path, "inspection-bound render delta")
    delta = load_json(delta_path)
    if delta.get("schema") != "stacks-zh-hans-cn-render-delta/v1":
        raise RuntimeError("unexpected render-delta schema")
    if delta.get("status") != "PASS" or delta.get("passed") is not True:
        raise RuntimeError("render-delta receipt did not pass")
    assert_record(delta.get("new_pdf"), PDF, "delta-bound new PDF")

    complete_delta = delta.get("complete_render_delta", {})
    assert_record(
        complete_delta.get("new_manifest"),
        RENDER_MANIFEST,
        "delta-bound complete-render manifest",
    )
    assert_record(
        complete_delta.get("new_summary"),
        RENDER_SUMMARY,
        "delta-bound complete-render summary",
    )
    changed_render_pages = {
        int(page) for page in complete_delta.get("changed_pages", [])
    }
    if int(complete_delta.get("changed_page_count", -1)) != len(changed_render_pages):
        raise RuntimeError("render-delta changed-page count drift")
    if not changed_render_pages:
        raise RuntimeError("render-delta contains no changed pages after a visual repair")

    contact_delta = delta.get("contact_sheet_delta", {})
    assert_record(
        contact_delta.get("new_manifest"),
        CONTACT_MANIFEST,
        "delta-bound contact-sheet manifest",
    )
    changed_sheets = {int(sheet) for sheet in contact_delta.get("changed_sheets", [])}
    if int(contact_delta.get("changed_sheet_count", -1)) != len(changed_sheets):
        raise RuntimeError("render-delta changed-contact-sheet count drift")
    affected_sheets = {(page - 1) // 20 + 1 for page in changed_render_pages}
    if not affected_sheets.issubset(changed_sheets):
        raise RuntimeError("a changed page lacks changed-contact-sheet coverage")

    full_delta = delta.get("full_resolution_delta", {})
    assert_record(
        full_delta.get("new_manifest"),
        FULL_RES_MANIFEST,
        "delta-bound full-resolution manifest",
    )
    assert_record(
        full_delta.get("new_summary"),
        FULL_RES_SUMMARY,
        "delta-bound full-resolution summary",
    )
    old_blocked_pages = {int(page) for page in full_delta.get("old_blocked_pages", [])}
    required_old_blocked_pages = {
        int(page) for page in full_delta.get("required_old_blocked_pages", [])
    }
    changed_full_pages = {
        int(page) for page in full_delta.get("changed_or_new_pages", [])
    }
    required_reinspection_pages = {
        int(page)
        for page in full_delta.get("required_full_resolution_reinspection_pages", [])
    }
    if 4909 not in required_old_blocked_pages or not required_old_blocked_pages.issubset(
        old_blocked_pages
    ):
        raise RuntimeError("the prior page-4909 failure is not preserved as adverse history")
    if not (changed_render_pages | old_blocked_pages).issubset(required_reinspection_pages):
        raise RuntimeError("render-delta omits a required full-resolution reinspection page")
    if not required_reinspection_pages.issubset(changed_full_pages):
        raise RuntimeError("a required full-resolution page was incorrectly inherited")
    if int(full_delta.get("changed_or_new_page_count", -1)) != len(changed_full_pages):
        raise RuntimeError("render-delta changed full-resolution count drift")

    aggregate_failed_pages = {
        int(page)
        for page in delta_inheritance.get("old_failed_full_resolution_pages", [])
    }
    aggregate_required_failed_pages = {
        int(page)
        for page in delta_inheritance.get(
            "required_old_failed_full_resolution_pages", []
        )
    }
    if aggregate_failed_pages != old_blocked_pages:
        raise RuntimeError("aggregate/delta old failed-page disposition drift")
    if aggregate_required_failed_pages != required_old_blocked_pages:
        raise RuntimeError("aggregate/delta required failed-page disposition drift")

    def count_mode(ranges: list[dict[str, Any]], first_key: str, last_key: str, mode: str) -> int:
        return sum(
            int(item[last_key]) - int(item[first_key]) + 1
            for item in ranges
            if item.get("evidence_mode") == mode
        )

    if count_mode(
        contact_ranges,
        "first_sheet",
        "last_sheet",
        "reinspected_changed",
    ) != len(changed_sheets):
        raise RuntimeError("aggregate contact-sheet reinspection count drift")
    if count_mode(
        full_resolution_ranges,
        "first_target_index",
        "last_target_index",
        "reinspected_changed",
    ) != len(changed_full_pages):
        raise RuntimeError("aggregate full-resolution reinspection count drift")
    if not delta.get("inspection_evidence", {}).get("new_reinspection_receipts"):
        raise RuntimeError("render delta lacks explicit new reinspection receipt bindings")
    if not delta.get("inspection_evidence", {}).get("old_high_resolution_receipts"):
        raise RuntimeError("render delta lacks the bound old failed inspection receipt")
    if not delta.get("adverse_evidence") or not receipt.get("adverse_evidence"):
        raise RuntimeError("page-4909 adverse visual history is not disclosed")
    return receipt, delta, delta_path


def require_empty_stderr() -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for path in (RENDER_STDERR, CONTACT_STDERR, FULL_RES_STDERR):
        if not path.is_file() or path.stat().st_size != 0:
            raise RuntimeError(f"missing or non-empty renderer stderr evidence: {relative(path)}")
        records[path.name] = file_record(path)
    return records


def dynamic_requirements() -> list[Path]:
    return [
        PAGE_DIR,
        RENDER_SUMMARY,
        RENDER_MANIFEST,
        CONTACT_MANIFEST,
        FULL_RES_DIR,
        FULL_RES_SUMMARY,
        FULL_RES_MANIFEST,
        INSPECTION_RECEIPT,
        RENDER_STDERR,
        CONTACT_STDERR,
        FULL_RES_STDERR,
    ]


def missing_dynamic_requirements() -> list[str]:
    return [relative(path) for path in dynamic_requirements() if not path.exists()]


def validate_dynamic_inputs(static: dict[str, Any]) -> dict[str, Any]:
    missing = missing_dynamic_requirements()
    if missing:
        raise FileNotFoundError("missing visual evidence: " + ", ".join(missing))
    render, render_rows = validate_render_evidence()
    contact_rows = validate_contact_evidence()
    full_res, full_res_rows = validate_full_res_evidence(static["selected_pages"])
    inspection, delta, delta_path = validate_inspection_receipt(
        contact_rows, static["selected_pages"]
    )
    stderr_records = require_empty_stderr()
    return {
        "render": render,
        "render_rows": render_rows,
        "contact_rows": contact_rows,
        "full_res": full_res,
        "full_res_rows": full_res_rows,
        "inspection": inspection,
        "delta": delta,
        "delta_path": delta_path,
        "stderr_records": stderr_records,
    }


def create_result(static: dict[str, Any], dynamic: dict[str, Any]) -> dict[str, Any]:
    mechanical = static["mechanical"]
    build = static["build"]
    warning_map = static["warning_map"]
    targets = static["targets"]
    render = dynamic["render"]
    full_res = dynamic["full_res"]
    inspection = dynamic["inspection"]
    delta = dynamic["delta"]
    findings = {key: int(inspection["findings"][key]) for key in REQUIRED_ZERO_FINDINGS}
    new_chapter_ranges = {
        str(chapter): {
            "start": int(targets["chapter_ranges"][str(chapter)]["start"]),
            "end": int(targets["chapter_ranges"][str(chapter)]["end"]),
        }
        for chapter in targets["new_chapters"]
    }
    return {
        "schema": "stacks-zh-hans-cn-visual-qa/v8",
        "release_candidate": "2026.08.26-r14",
        "locale": "zh-Hans-CN",
        "generation_basis": (
            "Deterministic evidence validation plus a separate explicit inspection receipt; "
            "this builder does not perform or fabricate visual inspection."
        ),
        "pdf": {
            **file_record(PDF),
            "pages": EXPECTED_PAGES,
            "page_size": "A4",
        },
        "input_receipts": {
            "r14_build": file_record(BUILD_RECEIPT),
            "source_replay": file_record(SOURCE_REPLAY),
            "source_replay_verification": file_record(SOURCE_REPLAY_VERIFICATION),
            "mechanical_qa": file_record(MECHANICAL),
        },
        "render_evidence": {
            "page_count": EXPECTED_PAGES,
            "dpi": 100,
            "page_sequence": "page-0001.png through page-5546.png",
            "dimensions_px": render["dimensions_px"],
            "total_bytes": render["total_bytes"],
            "ordered_page_hash_binding_sha256": render[
                "ordered_page_hash_binding_sha256"
            ],
            "manifest": file_record(RENDER_MANIFEST),
            "summary": file_record(RENDER_SUMMARY),
        },
        "contact_sheet_evidence": {
            "count": EXPECTED_CONTACT_SHEETS,
            "pages_per_sheet_maximum": 20,
            "page_coverage": "1-5546 without gaps",
            "manifest": file_record(CONTACT_MANIFEST),
        },
        "full_resolution_evidence": {
            "dpi": 200,
            "target_count": EXPECTED_FULL_RES_TARGETS,
            "selected_pages": static["selected_pages"],
            "dimensions_px": full_res["dimensions_px"],
            "ordered_page_hash_binding_sha256": full_res[
                "ordered_page_hash_binding_sha256"
            ],
            "manifest": file_record(FULL_RES_MANIFEST),
            "summary": file_record(FULL_RES_SUMMARY),
            "targets": file_record(TARGETS),
            "warning_page_map": {
                **file_record(WARNING_MAP),
                "mapped_warning_records": int(warning_map["record_count"]),
                "unique_warning_pages": int(
                    warning_map["unique_mapped_box_warning_pdf_page_count"]
                ),
                "unmapped_warnings": int(warning_map["unmapped_count"]),
            },
            "new_chapters": [int(chapter) for chapter in targets["new_chapters"]],
            "new_chapter_physical_page_ranges": new_chapter_ranges,
        },
        "inspection_evidence": {
            "receipt": file_record(INSPECTION_RECEIPT),
            "inspection_id": inspection["inspection_id"],
            "inspector": inspection["inspector"],
            "inspected_at": inspection["inspected_at"],
            "contact_sheet_ranges": inspection["contact_sheet_ranges"],
            "full_resolution_target_ranges": inspection[
                "full_resolution_target_ranges"
            ],
            "blocker_count": 0,
            "blockers": [],
            "findings": findings,
            "delta_receipt": file_record(dynamic["delta_path"]),
            "delta_inheritance": inspection["delta_inheritance"],
            "prior_failed_visual_pages": delta["full_resolution_delta"][
                "old_blocked_pages"
            ],
        },
        "mechanical_cross_check": {
            "named_destinations": int(mechanical["named_destinations"]),
            "link_annotations": int(mechanical["annotations"]["total"]),
            "malformed_link_rectangles": 0,
            "zero_area_link_rectangles": 0,
            "out_of_page_link_rectangles": 0,
            "fonts_total": int(mechanical["fonts"]["total"]),
            "fonts_embedded": int(mechanical["fonts"]["embedded"]),
            "fonts_with_to_unicode": int(mechanical["fonts"]["with_to_unicode"]),
            "extracted_characters": int(mechanical["text_extraction"]["characters"]),
            "extracted_cjk_unified_ideographs": int(
                mechanical["text_extraction"]["cjk_unified_ideographs"]
            ),
            "replacement_characters": int(
                mechanical["text_extraction"]["replacement_characters"]
            ),
            "literal_double_question_pairs": int(
                mechanical["text_extraction"]["literal_double_question_pairs"]
            ),
        },
        "build_log_cross_check": {
            **file_record(LOG),
            "blocking_condition_counts": build["diagnostics"][
                "blocking_condition_counts"
            ],
            "nonblocking_counts": build["diagnostics"]["nonblocking_counts"],
        },
        "stderr_evidence": dynamic["stderr_records"],
        "adverse_evidence": [
            "The PDF is untagged: it has no StructTreeRoot or MarkInfo.",
            (
                f"{int(mechanical['fonts']['total']) - int(mechanical['fonts']['with_to_unicode'])} "
                "embedded legacy math/Xy-pic font subsets lack ToUnicode."
            ),
            (
                f"Extracted text contains {int(mechanical['text_extraction']['literal_double_question_pairs'])} "
                "literal double-question-mark pairs; independently verified source replay reports "
                "zero unresolved reference targets."
            ),
            (
                "The final log retains "
                f"{int(build['diagnostics']['nonblocking_counts']['overfull_hbox_warnings'])} "
                "overfull hbox, "
                f"{int(build['diagnostics']['nonblocking_counts']['underfull_hbox_warnings'])} "
                "underfull hbox, "
                f"{int(build['diagnostics']['nonblocking_counts']['overfull_vbox_warnings'])} "
                "overfull vbox, and "
                f"{int(build['diagnostics']['nonblocking_counts']['underfull_vbox_warnings'])} "
                "underfull vbox warnings. The separate "
                f"inspection receipt covers all {EXPECTED_CONTACT_SHEETS} contact sheets and "
                f"all {EXPECTED_FULL_RES_TARGETS} selected 200-dpi targets with zero blockers."
            ),
            (
                "This visual receipt attests layout inspection only and does not claim "
                "independent Chinese-language certification."
            ),
            (
                "The prior high-resolution inspection failed on PDF page 4909. Its exact "
                "receipt remains bound through the render-delta evidence as adverse history; "
                "the repaired page visibly changed and passed explicit new inspection."
            ),
        ],
        "passed_visual": True,
    }


def write_outputs(result: dict[str, Any]) -> None:
    OUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    inspection = result["inspection_evidence"]
    contact_ranges = ", ".join(
        (
            f"sheets {item['first_sheet']}-{item['last_sheet']} "
            f"(pages {item['first_page']}-{item['last_page']})"
        )
        for item in inspection["contact_sheet_ranges"]
    )
    target_ranges = ", ".join(
        (
            f"targets {item['first_target_index']}-{item['last_target_index']} "
            f"(page envelope {item['first_page']}-{item['last_page']})"
        )
        for item in inspection["full_resolution_target_ranges"]
    )
    mechanical = result["mechanical_cross_check"]
    counts = result["build_log_cross_check"]["nonblocking_counts"]
    report = f"""# Visual QA - R14 cumulative 112-chapter reader

- PDF SHA-256: {result['pdf']['sha256']}
- Pages: {EXPECTED_PAGES:,} A4
- Complete render: {EXPECTED_PAGES:,} pages at 100 dpi
- Contact sheets: {EXPECTED_CONTACT_SHEETS}, 20 pages maximum per sheet
- Full-resolution targets: {EXPECTED_FULL_RES_TARGETS} at 200 dpi

## Evidence disposition

This builder did not perform visual inspection. It validated the separately supplied
explicit inspection receipt {inspection['inspection_id']} from an
{inspection['inspector']['kind']} inspector, including its exact manifest bindings,
range coverage, pass results, and zero blockers.

- Contact-sheet ranges: {contact_ranges}
- Full-resolution target ranges: {target_ranges}
- Blockers: 0

All required defect counts in the inspection receipt are zero. Mechanical QA,
source replay, the R14 build receipt, complete-render evidence, contact-sheet
coverage, selected 200-dpi target evidence, and the warning-page map all bind the
same PDF bytes.

## Adverse evidence retained

The PDF is untagged. {mechanical['fonts_total'] - mechanical['fonts_with_to_unicode']} embedded
legacy math/Xy-pic font subsets lack ToUnicode. Extracted text contains
{mechanical['literal_double_question_pairs']} literal double-question-mark pairs, while
independently verified source replay reports zero unresolved reference targets.
The final log retains {counts['overfull_hbox_warnings']} overfull hbox,
{counts['underfull_hbox_warnings']} underfull hbox,
{counts['overfull_vbox_warnings']} overfull vbox, and
{counts['underfull_vbox_warnings']} underfull vbox warnings. The prior failed
page-4909 inspection remains bound as adverse history and the repaired page was
explicitly reinspected. This receipt attests layout inspection only and does
not claim independent Chinese-language certification.
"""
    REPORT.write_text(report, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "path": relative(OUT),
                "bytes": OUT.stat().st_size,
                "sha256": sha256(OUT),
                "inspection_receipt": file_record(INSPECTION_RECEIPT),
                "passed_visual": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def inspection_contract() -> dict[str, Any]:
    target_count = (
        str(EXPECTED_FULL_RES_TARGETS)
        if EXPECTED_FULL_RES_TARGETS is not None
        else "<FINAL_TARGET_COUNT>"
    )
    return {
        "path": relative(INSPECTION_RECEIPT),
        "schema": "stacks-zh-hans-cn-explicit-visual-inspection/v1",
        "required_top_level": {
            "performed": True,
            "passed": True,
            "pdf_sha256": EXPECTED_PDF_SHA256,
            "page_count": EXPECTED_PAGES,
            "contact_sheet_count": EXPECTED_CONTACT_SHEETS,
            "full_resolution_target_count": EXPECTED_FULL_RES_TARGETS,
            "blocker_count": 0,
            "blockers": [],
        },
        "required_identity_fields": {
            "inspection_id": "non-empty string",
            "inspector": {"kind": "human or agent", "id": "non-empty opaque identifier"},
            "inspected_at": "ISO-8601 timestamp with timezone",
        },
        "required_bindings": [
            relative(CONTACT_MANIFEST),
            relative(FULL_RES_MANIFEST),
            "delta_inheritance.receipt: exact render-delta receipt",
        ],
        "contact_sheet_range_fields": [
            "first_sheet",
            "last_sheet",
            "first_page",
            "last_page",
            "result=pass",
            "blockers=[]",
            "evidence_mode=inherited_byte_identical or reinspected_changed",
        ],
        "contact_sheet_range_coverage": "exact contiguous coverage of sheets 1-278 and pages 1-5546",
        "full_resolution_target_range_fields": [
            "first_target_index",
            "last_target_index",
            "first_page",
            "last_page",
            "result=pass",
            "blockers=[]",
            "evidence_mode=inherited_byte_identical or reinspected_changed",
        ],
        "full_resolution_target_range_coverage": (
            f"exact contiguous coverage of target indices 1-{target_count}; page envelopes "
            "must match the selected-page sequence"
        ),
        "required_zero_findings": list(REQUIRED_ZERO_FINDINGS),
        "required_adverse_history": (
            "The old failed page-4909 high-resolution receipt remains bound through "
            "delta_inheritance; page 4909 must visibly change and be explicitly reinspected."
        ),
    }


def builder_contract() -> dict[str, Any]:
    return {
        "schema": "stacks-zh-hans-cn-r14-visual-builder-contract/v1",
        "binding_state": (
            "bound_to_final_build"
            if EXPECTED_PDF_SHA256 is not None
            else "unbound_fail_closed_pending_replacement_build"
        ),
        "rejected_build_policy": (
            "A rejected PDF identity is adverse evidence only and must never remain in "
            "the current identity patch block."
        ),
        "post_repair_identity_patch_point": {
            "file": relative(Path(__file__).resolve()),
            "line_block_marker": "POST-REPAIR IDENTITY PATCH POINT",
            "update_after_final_build": [
                "EXPECTED_PDF_SHA256 and EXPECTED_PDF_BYTES",
                "EXPECTED_FULL_RES_TARGETS, EXPECTED_WARNING_RECORDS, EXPECTED_WARNING_PAGES",
                "EXPECTED_STATIC_HASHES",
                "EXPECTED_NONBLOCKING_COUNTS",
            ],
            "derived_without_manual_path_edits": [
                "OUTPUT_STEM and every hash-keyed visual evidence path",
                "PDF identity in generated visual and final-QA receipts",
            ],
        },
        "inspection_receipt": inspection_contract(),
        "delta_fail_closed_rules": [
            "inherit a contact sheet only when its bytes and every underlying 100-dpi page are identical and its old inspection passed",
            "inherit a 200-dpi target only when both 100-dpi and 200-dpi bytes are identical and its old inspection passed",
            "every changed 100-dpi page and every old blocker page must be selected at 200 dpi and explicitly reinspected",
            "page 4909 must remain bound as old adverse evidence, visibly change, and pass explicit new inspection",
            "coverage omissions, extras, overlaps, duplicate entries, blockers, or nonzero findings fail",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create the R14 visual-QA receipt only after deterministic evidence and a "
            "separate explicit inspection receipt pass."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate available inputs and print missing evidence without writing",
    )
    parser.add_argument(
        "--contract",
        action="store_true",
        help="print the post-repair configuration and delta-evidence contract without reading the PDF",
    )
    args = parser.parse_args()

    if args.contract:
        print(json.dumps(builder_contract(), ensure_ascii=False, indent=2))
        return 0

    static = validate_static_inputs()
    missing = missing_dynamic_requirements()
    if args.dry_run and missing:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "static_inputs_valid": True,
                    "dynamic_evidence_ready": False,
                    "writes_performed": False,
                    "missing": missing,
                    "inspection_receipt_contract": inspection_contract(),
                    "would_write": [relative(OUT), relative(REPORT)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    dynamic = validate_dynamic_inputs(static)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "static_inputs_valid": True,
                    "dynamic_evidence_ready": True,
                    "inspection_receipt_valid": True,
                    "writes_performed": False,
                    "would_write": [relative(OUT), relative(REPORT)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    result = create_result(static, dynamic)
    write_outputs(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
