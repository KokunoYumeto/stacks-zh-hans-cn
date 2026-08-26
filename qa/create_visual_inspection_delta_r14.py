from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


QA = Path(__file__).resolve().parent
ROOT = QA.parent

ZERO_FINDINGS = (
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

CONTACT_RECEIPT_SCHEMA = "stacks-zh-hans-cn-contact-inspection/v1"
HIGH_RES_RECEIPT_SCHEMA = "stacks-zh-hans-cn-high-res-inspection/v1"
AGGREGATE_RECEIPT_SCHEMA = "stacks-zh-hans-cn-explicit-visual-inspection/v1"
REINSPECTION_SCHEMA = "stacks-zh-hans-cn-delta-reinspection/v1"
DELTA_SCHEMA = "stacks-zh-hans-cn-render-delta/v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def root_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def file_record(path: Path) -> dict[str, object]:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": root_relative(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def planned_file_record(path: Path, payload: bytes) -> dict[str, object]:
    return {
        "path": root_relative(path),
        "bytes": len(payload),
        "sha256": hash_bytes(payload),
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def resolve_bound_path(value: object) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def binding_path_matches(value: object, expected: Path) -> bool:
    """Accept the two historical receipt bases without weakening byte/hash checks."""
    path = Path(str(value))
    expected = expected.resolve()
    if path.is_absolute():
        return path.resolve() == expected
    candidates = ((ROOT / path).resolve(), (Path.cwd() / path).resolve())
    if expected in candidates:
        return True
    expected_parts = tuple(part.casefold() for part in expected.parts)
    value_parts = tuple(part.casefold() for part in path.parts)
    return bool(value_parts) and expected_parts[-len(value_parts) :] == value_parts


def require_hex_hash(value: object, label: str) -> str:
    result = str(value).upper()
    if len(result) != 64 or any(char not in "0123456789ABCDEF" for char in result):
        raise RuntimeError(f"{label} is not a SHA-256 value")
    return result


def assert_binding(binding: object, path: Path, label: str) -> None:
    if not isinstance(binding, dict):
        raise RuntimeError(f"{label} is not a file binding")
    actual = file_record(path)
    if not binding_path_matches(binding.get("path", ""), path):
        raise RuntimeError(f"{label} path drift")
    if int(binding.get("bytes", -1)) != int(actual["bytes"]):
        raise RuntimeError(f"{label} byte-count drift")
    if str(binding.get("sha256", "")).upper() != actual["sha256"]:
        raise RuntimeError(f"{label} hash drift")


def parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label} is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RuntimeError(f"{label} must include a timezone")
    return parsed


def validate_inspector(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} is not an inspector object")
    kind = value.get("kind")
    opaque_id = value.get("id", value.get("opaque_id"))
    if kind not in {"human", "agent"}:
        raise RuntimeError(f"{label}.kind must be human or agent")
    if not isinstance(opaque_id, str) or not opaque_id.strip():
        raise RuntimeError(f"{label} needs a non-empty opaque identifier")
    return {"kind": str(kind), "id": opaque_id.strip()}


def verify_image(path: Path, row: dict[str, str], label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    if int(row.get("bytes", -1)) != path.stat().st_size:
        raise RuntimeError(f"{label} byte-count drift")
    if str(row.get("sha256", "")).upper() != sha256(path):
        raise RuntimeError(f"{label} hash drift")


def load_page_manifest(
    manifest: Path,
    image_dir: Path | None,
    *,
    expected_pages: int | None,
    require_contiguous: bool,
    verify_files: bool = True,
    label: str,
) -> tuple[list[int], dict[int, dict[str, Any]]]:
    rows = read_csv(manifest)
    if not rows:
        raise RuntimeError(f"{label} is empty")
    order: list[int] = []
    result: dict[int, dict[str, Any]] = {}
    for position, row in enumerate(rows, start=1):
        page = int(row.get("page", -1))
        if page <= 0 or page in result:
            raise RuntimeError(f"{label} page sequence is invalid at row {position}")
        if require_contiguous and page != position:
            raise RuntimeError(f"{label} is not contiguous at row {position}")
        filename = row.get("filename", "")
        expected_name = f"page-{page:04d}.png"
        if filename != expected_name:
            raise RuntimeError(f"{label} filename drift at page {page}")
        if verify_files:
            if image_dir is None:
                raise RuntimeError(f"{label} requires an image directory")
            path = (image_dir / filename).resolve()
            verify_image(path, row, f"{label} page {page}")
        else:
            path = None
        width = int(row.get("width_px", -1))
        height = int(row.get("height_px", -1))
        mode = row.get("mode", "")
        if width <= 0 or height <= 0 or not mode:
            raise RuntimeError(f"{label} image metadata is invalid at page {page}")
        order.append(page)
        result[page] = {
            "page": page,
            "filename": filename,
            "bytes": int(row["bytes"]),
            "sha256": require_hex_hash(row.get("sha256"), f"{label} page {page}"),
            "width_px": width,
            "height_px": height,
            "mode": mode,
            "path": path,
        }
    if order != sorted(order):
        raise RuntimeError(f"{label} pages are not strictly increasing")
    if expected_pages is not None and len(order) != expected_pages:
        raise RuntimeError(f"{label} row-count drift")
    return order, result


def load_contact_manifest(
    manifest: Path,
    *,
    page_count: int,
    label: str,
) -> tuple[list[int], dict[int, dict[str, Any]]]:
    rows = read_csv(manifest)
    if not rows:
        raise RuntimeError(f"{label} is empty")
    order: list[int] = []
    result: dict[int, dict[str, Any]] = {}
    expected_first_page = 1
    for position, row in enumerate(rows, start=1):
        sheet = int(row.get("sheet", -1))
        first_page = int(row.get("first_page", -1))
        last_page = int(row.get("last_page", -1))
        if sheet != position or sheet in result:
            raise RuntimeError(f"{label} sheet sequence drift at row {position}")
        if first_page != expected_first_page or last_page < first_page:
            raise RuntimeError(f"{label} page coverage drift at sheet {sheet}")
        path = resolve_bound_path(row.get("path", ""))
        verify_image(path, row, f"{label} sheet {sheet}")
        order.append(sheet)
        result[sheet] = {
            "sheet": sheet,
            "first_page": first_page,
            "last_page": last_page,
            "bytes": int(row["bytes"]),
            "sha256": require_hex_hash(row.get("sha256"), f"{label} sheet {sheet}"),
            "path": path,
        }
        expected_first_page = last_page + 1
    if expected_first_page != page_count + 1:
        raise RuntimeError(f"{label} does not cover pages 1-{page_count}")
    return order, result


def page_record_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(
        left[key] == right[key]
        for key in ("bytes", "sha256", "width_px", "height_px", "mode")
    )


def ordered_page_binding(order: list[int], records: dict[int, dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for page in order:
        digest.update(f"{page}\t{records[page]['sha256']}\n".encode("ascii"))
    return digest.hexdigest().upper()


def validate_render_summary(
    summary_path: Path,
    manifest: Path,
    *,
    pdf_hash: str,
    page_count: int,
    order: list[int],
    records: dict[int, dict[str, Any]],
    label: str,
) -> tuple[dict[str, Any], bool]:
    summary = load_json(summary_path)
    if summary.get("schema") != "stacks-zh-hans-cn-render-audit/v1":
        raise RuntimeError(f"unexpected {label} schema")
    if summary.get("passed") is not True:
        raise RuntimeError(f"{label} did not pass")
    if int(summary.get("page_count", -1)) != page_count or int(
        summary.get("expected_page_count", -1)
    ) != page_count:
        raise RuntimeError(f"{label} page-count drift")
    if int(summary.get("render_dpi", -1)) != 100:
        raise RuntimeError(f"{label} DPI drift")
    assert_binding(summary.get("manifest"), manifest, f"{label} manifest")
    if str(summary.get("ordered_page_hash_binding_sha256", "")).upper() != ordered_page_binding(
        order, records
    ):
        raise RuntimeError(f"{label} ordered page binding drift")
    declared_pdf_hash = summary.get("pdf_sha256")
    if declared_pdf_hash is not None and str(declared_pdf_hash).upper() != pdf_hash:
        raise RuntimeError(f"{label} binds another PDF")
    return summary, declared_pdf_hash is not None


def validate_full_res_summary(
    summary_path: Path,
    manifest: Path,
    *,
    pdf_hash: str,
    page_count: int,
    order: list[int],
    records: dict[int, dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    summary = load_json(summary_path)
    if summary.get("schema") != "stacks-zh-hans-cn-full-resolution-target-audit/v2":
        raise RuntimeError(f"unexpected {label} schema")
    if summary.get("passed") is not True:
        raise RuntimeError(f"{label} did not pass")
    if int(summary.get("page_count", -1)) != page_count:
        raise RuntimeError(f"{label} page-count drift")
    if str(summary.get("pdf_sha256", "")).upper() != pdf_hash:
        raise RuntimeError(f"{label} binds another PDF")
    if int(summary.get("render_dpi", -1)) != 200:
        raise RuntimeError(f"{label} DPI drift")
    if [int(page) for page in summary.get("selected_pages", [])] != order:
        raise RuntimeError(f"{label} selected-page sequence drift")
    if int(summary.get("selected_page_count", -1)) != len(order):
        raise RuntimeError(f"{label} selected-page count drift")
    assert_binding(summary.get("manifest"), manifest, f"{label} manifest")
    if str(summary.get("ordered_page_hash_binding_sha256", "")).upper() != ordered_page_binding(
        order, records
    ):
        raise RuntimeError(f"{label} ordered page binding drift")
    return summary


def sheet_record_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(
        left[key] == right[key]
        for key in ("first_page", "last_page", "bytes", "sha256")
    )


def passed_old_contact_sheets(
    receipt_paths: list[Path],
    old_manifest: Path,
    old_sheets: dict[int, dict[str, Any]],
) -> tuple[set[int], list[dict[str, object]]]:
    passed: set[int] = set()
    bindings: list[dict[str, object]] = []
    for path in receipt_paths:
        receipt = load_json(path)
        schema = receipt.get("schema")
        if schema == CONTACT_RECEIPT_SCHEMA:
            if receipt.get("result") != "PASS":
                raise RuntimeError(f"old contact receipt did not pass: {path}")
            parse_time(receipt.get("inspected_at"), f"{path.name}.inspected_at")
            validate_inspector(receipt.get("inspector"), f"{path.name}.inspector")
            assert_binding(receipt.get("contact_manifest"), old_manifest, path.name)
            inspection = receipt.get("inspection")
            if not isinstance(inspection, dict):
                raise RuntimeError(f"old contact receipt lacks inspection data: {path}")
            if inspection.get("blockers") != [] or int(inspection.get("blocker_count", -1)) != 0:
                raise RuntimeError(f"old contact receipt has blockers: {path}")
            findings = inspection.get("findings")
            if not isinstance(findings, dict) or any(int(value) != 0 for value in findings.values()):
                raise RuntimeError(f"old contact receipt has nonzero findings: {path}")
            scope = receipt.get("scope", {}).get("sheets", {})
            first = int(scope.get("first", -1))
            last = int(scope.get("last", -1))
            count = int(scope.get("count", -1))
            if first < 1 or last < first or count != last - first + 1:
                raise RuntimeError(f"old contact receipt scope is invalid: {path}")
            candidate = set(range(first, last + 1))
        elif schema == AGGREGATE_RECEIPT_SCHEMA:
            if receipt.get("performed") is not True or receipt.get("passed") is not True:
                raise RuntimeError(f"old aggregate receipt did not pass: {path}")
            assert_binding(receipt.get("contact_sheet_manifest"), old_manifest, path.name)
            candidate = set()
            for item in receipt.get("contact_sheet_ranges", []):
                if item.get("result") != "pass" or item.get("blockers") != []:
                    raise RuntimeError(f"old aggregate contact range did not pass: {path}")
                candidate.update(range(int(item["first_sheet"]), int(item["last_sheet"]) + 1))
        else:
            raise RuntimeError(f"unsupported old contact receipt schema in {path}: {schema}")
        if not candidate or not candidate.issubset(old_sheets):
            raise RuntimeError(f"old contact receipt references unknown sheets: {path}")
        overlap = passed.intersection(candidate)
        if overlap:
            raise RuntimeError(f"old contact receipts overlap at sheets {sorted(overlap)}")
        passed.update(candidate)
        bindings.append(file_record(path))
    return passed, bindings


def passed_old_high_res_pages(
    receipt_paths: list[Path],
    old_manifest: Path,
    old_page_order: list[int],
    old_pdf_hash: str,
) -> tuple[set[int], set[int], list[dict[str, object]]]:
    passed: set[int] = set()
    blocked: set[int] = set()
    bindings: list[dict[str, object]] = []
    known = set(old_page_order)
    for path in receipt_paths:
        receipt = load_json(path)
        schema = receipt.get("schema")
        if schema == HIGH_RES_RECEIPT_SCHEMA:
            if receipt.get("performed") is not True:
                raise RuntimeError(f"old high-res inspection was not performed: {path}")
            if str(receipt.get("pdf", {}).get("sha256", "")).upper() != old_pdf_hash:
                raise RuntimeError(f"old high-res inspection binds another PDF: {path}")
            parse_time(receipt.get("inspected_at"), f"{path.name}.inspected_at")
            assert_binding(receipt.get("render_manifest"), old_manifest, path.name)
            coverage = receipt.get("coverage")
            if not isinstance(coverage, dict):
                raise RuntimeError(f"old high-res receipt lacks coverage: {path}")
            if coverage.get("missing_targets") != [] or coverage.get("uninspected_targets") != []:
                raise RuntimeError(f"old high-res receipt has incomplete coverage: {path}")
            blockers = receipt.get("blockers")
            if not isinstance(blockers, list):
                raise RuntimeError(f"old high-res receipt blockers are invalid: {path}")
            receipt_blocked = {int(item.get("pdf_page", -1)) for item in blockers}
            if -1 in receipt_blocked or not receipt_blocked.issubset(known):
                raise RuntimeError(f"old high-res receipt blocker page is invalid: {path}")
            if int(receipt.get("blocker_count", -1)) != len(blockers):
                raise RuntimeError(f"old high-res receipt blocker-count drift: {path}")
            findings = receipt.get("finding_counts")
            if not isinstance(findings, dict):
                raise RuntimeError(f"old high-res receipt findings are invalid: {path}")
            if sum(int(value) for value in findings.values()) != len(blockers):
                raise RuntimeError(
                    f"old high-res receipt has findings not represented by blockers: {path}"
                )
            if receipt.get("passed") is True and receipt_blocked:
                raise RuntimeError(f"old high-res receipt passes despite blockers: {path}")
            candidate = known - receipt_blocked
        elif schema == AGGREGATE_RECEIPT_SCHEMA:
            if receipt.get("performed") is not True or receipt.get("passed") is not True:
                raise RuntimeError(f"old aggregate receipt did not pass: {path}")
            assert_binding(receipt.get("full_resolution_manifest"), old_manifest, path.name)
            candidate = set()
            for item in receipt.get("full_resolution_target_ranges", []):
                if item.get("result") != "pass" or item.get("blockers") != []:
                    raise RuntimeError(f"old aggregate high-res range did not pass: {path}")
                first = int(item["first_target_index"])
                last = int(item["last_target_index"])
                candidate.update(old_page_order[first - 1 : last])
            receipt_blocked = set()
        else:
            raise RuntimeError(f"unsupported old high-res receipt schema in {path}: {schema}")
        overlap = passed.intersection(candidate)
        if overlap:
            raise RuntimeError(f"old high-res receipts overlap at pages {sorted(overlap)}")
        passed.update(candidate)
        blocked.update(receipt_blocked)
        bindings.append(file_record(path))
    return passed, blocked, bindings


def validate_reinspection_receipts(
    receipt_paths: list[Path],
    *,
    new_pdf_hash: str,
    new_contact_manifest: Path,
    new_full_res_manifest: Path,
    changed_sheets: set[int],
    changed_pages: set[int],
    new_sheets: dict[int, dict[str, Any]],
    new_full_order: list[int],
) -> tuple[set[int], set[int], list[dict[str, object]], list[dict[str, str]], list[datetime]]:
    inspected_sheets: set[int] = set()
    inspected_pages: set[int] = set()
    bindings: list[dict[str, object]] = []
    inspectors: list[dict[str, str]] = []
    times: list[datetime] = []
    page_to_index = {page: index for index, page in enumerate(new_full_order, start=1)}
    for path in receipt_paths:
        receipt = load_json(path)
        if receipt.get("schema") != REINSPECTION_SCHEMA:
            raise RuntimeError(f"unexpected reinspection schema in {path}")
        if receipt.get("performed") is not True or receipt.get("passed") is not True:
            raise RuntimeError(f"reinspection did not pass: {path}")
        if str(receipt.get("pdf_sha256", "")).upper() != new_pdf_hash:
            raise RuntimeError(f"reinspection binds another PDF: {path}")
        assert_binding(receipt.get("contact_sheet_manifest"), new_contact_manifest, path.name)
        assert_binding(receipt.get("full_resolution_manifest"), new_full_res_manifest, path.name)
        if receipt.get("blockers") != [] or int(receipt.get("blocker_count", -1)) != 0:
            raise RuntimeError(f"reinspection contains blockers: {path}")
        findings = receipt.get("findings")
        if not isinstance(findings, dict):
            raise RuntimeError(f"reinspection findings are missing: {path}")
        if set(ZERO_FINDINGS) - set(findings):
            raise RuntimeError(f"reinspection findings are incomplete: {path}")
        if any(int(findings[key]) != 0 for key in ZERO_FINDINGS):
            raise RuntimeError(f"reinspection has nonzero findings: {path}")
        inspector = validate_inspector(receipt.get("inspector"), f"{path.name}.inspector")
        inspected_at = parse_time(receipt.get("inspected_at"), f"{path.name}.inspected_at")

        local_sheets: set[int] = set()
        for item in receipt.get("contact_sheets", []):
            if not isinstance(item, dict):
                raise RuntimeError(f"reinspection contact-sheet entry is invalid: {path}")
            sheet = int(item.get("sheet", -1))
            record = new_sheets.get(sheet)
            if record is None:
                raise RuntimeError(f"reinspection references unknown sheet {sheet}: {path}")
            if int(item.get("first_page", -1)) != record["first_page"] or int(
                item.get("last_page", -1)
            ) != record["last_page"]:
                raise RuntimeError(f"reinspection sheet envelope drift at {sheet}: {path}")
            if item.get("result") != "pass" or item.get("blockers") != []:
                raise RuntimeError(f"reinspection sheet did not pass at {sheet}: {path}")
            if sheet in local_sheets:
                raise RuntimeError(
                    f"reinspection repeats contact sheet {sheet} within one receipt: {path}"
                )
            local_sheets.add(sheet)

        local_pages: set[int] = set()
        for item in receipt.get("full_resolution_pages", []):
            if not isinstance(item, dict):
                raise RuntimeError(f"reinspection full-resolution entry is invalid: {path}")
            page = int(item.get("page", -1))
            if page not in page_to_index:
                raise RuntimeError(f"reinspection references unknown target page {page}: {path}")
            if int(item.get("target_index", -1)) != page_to_index[page]:
                raise RuntimeError(f"reinspection target-index drift at page {page}: {path}")
            if item.get("result") != "pass" or item.get("blockers") != []:
                raise RuntimeError(f"reinspection target did not pass at page {page}: {path}")
            if page in local_pages:
                raise RuntimeError(
                    f"reinspection repeats full-resolution page {page} within one receipt: {path}"
                )
            local_pages.add(page)

        if inspected_sheets.intersection(local_sheets):
            raise RuntimeError(f"reinspection receipts overlap in contact sheets: {path}")
        if inspected_pages.intersection(local_pages):
            raise RuntimeError(f"reinspection receipts overlap in full-resolution pages: {path}")
        inspected_sheets.update(local_sheets)
        inspected_pages.update(local_pages)
        bindings.append(file_record(path))
        inspectors.append(inspector)
        times.append(inspected_at)

    if inspected_sheets != changed_sheets:
        raise RuntimeError(
            "changed contact-sheet reinspection mismatch: "
            f"missing={sorted(changed_sheets - inspected_sheets)}, "
            f"extra={sorted(inspected_sheets - changed_sheets)}"
        )
    if inspected_pages != changed_pages:
        raise RuntimeError(
            "changed full-resolution reinspection mismatch: "
            f"missing={sorted(changed_pages - inspected_pages)}, "
            f"extra={sorted(inspected_pages - changed_pages)}"
        )
    return inspected_sheets, inspected_pages, bindings, inspectors, times


def coalesce_ranges(
    order: list[int],
    status: dict[int, str],
    envelope: dict[int, tuple[int, int]],
    *,
    first_key: str,
    last_key: str,
) -> list[dict[str, object]]:
    if not order:
        raise RuntimeError("cannot coalesce an empty inspection sequence")
    result: list[dict[str, object]] = []
    first = order[0]
    last = first
    mode = status[first]
    for value in order[1:]:
        if value == last + 1 and status[value] == mode:
            last = value
            continue
        result.append(
            {
                first_key: first,
                last_key: last,
                "first_page": envelope[first][0],
                "last_page": envelope[last][1],
                "evidence_mode": mode,
                "result": "pass",
                "blockers": [],
            }
        )
        first = value
        last = value
        mode = status[value]
    result.append(
        {
            first_key: first,
            last_key: last,
            "first_page": envelope[first][0],
            "last_page": envelope[last][1],
            "evidence_mode": mode,
            "result": "pass",
            "blockers": [],
        }
    )
    return result


def json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def contract() -> dict[str, object]:
    return {
        "schema": REINSPECTION_SCHEMA,
        "helper_required_inputs": [
            "old PDF SHA-256 and exact new PDF path",
            "old/new 100-dpi render summaries and manifests; the new image directory is mandatory, while the old directory is optional only when the exact old passing summary remains",
            "old/new contact-sheet manifests (whose rows bind the actual JPEGs)",
            "old/new 200-dpi full-resolution summaries, manifests, and image directories",
            "one or more passing old contact-inspection receipts",
            "one or more old high-resolution inspection receipts (failed receipts are allowed only when every finding is an exact page blocker)",
            "one or more new delta-reinspection receipts covering exactly every computed changed/new sheet and selected page",
            "every changed 100-dpi page and every preserved old blocker page must also be present in the new 200-dpi target manifest",
            "distinct new delta-receipt and aggregate-inspection output paths",
        ],
        "purpose": (
            "Explicitly reinspect every changed/new contact sheet and every changed/new "
            "selected 200-dpi page identified by the deterministic delta helper."
        ),
        "required_top_level": {
            "performed": True,
            "passed": True,
            "pdf_sha256": "new PDF SHA-256",
            "inspector": {"kind": "human or agent", "id": "opaque non-empty id"},
            "inspected_at": "ISO-8601 timestamp with timezone",
            "contact_sheet_manifest": "exact new manifest file binding",
            "full_resolution_manifest": "exact new manifest file binding",
            "blocker_count": 0,
            "blockers": [],
            "findings": {key: 0 for key in ZERO_FINDINGS},
        },
        "contact_sheets": [
            {
                "sheet": "changed sheet index",
                "first_page": "manifest first page",
                "last_page": "manifest last page",
                "result": "pass",
                "blockers": [],
            }
        ],
        "full_resolution_pages": [
            {
                "target_index": "one-based index in new full-res manifest",
                "page": "changed/new selected PDF page",
                "result": "pass",
                "blockers": [],
            }
        ],
        "coverage_rule": (
            "Across all supplied reinspection receipts, the two lists must equal the exact "
            "changed sets computed by this helper. Every changed 100-dpi page and every "
            "preserved old blocker page is forced into the full-resolution set; omissions, "
            "extras, repetitions, and overlaps fail."
        ),
        "required_old_blocked_pages": [4909],
    }


def required_path(value: str | None, label: str) -> Path:
    if not value:
        raise RuntimeError(f"missing required argument: {label}")
    return Path(value).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a fail-closed old-to-new render delta and a builder-compatible "
            "aggregate visual-inspection receipt. This tool never renders or builds PDFs."
        )
    )
    parser.add_argument("--contract", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--page-count", type=int)
    parser.add_argument("--old-pdf-sha256")
    parser.add_argument("--new-pdf")
    parser.add_argument("--old-render-manifest")
    parser.add_argument("--old-render-summary")
    parser.add_argument("--old-render-dir")
    parser.add_argument("--new-render-manifest")
    parser.add_argument("--new-render-summary")
    parser.add_argument("--new-render-dir")
    parser.add_argument("--old-contact-manifest")
    parser.add_argument("--new-contact-manifest")
    parser.add_argument("--old-full-res-manifest")
    parser.add_argument("--old-full-res-summary")
    parser.add_argument("--old-full-res-dir")
    parser.add_argument("--new-full-res-manifest")
    parser.add_argument("--new-full-res-summary")
    parser.add_argument("--new-full-res-dir")
    parser.add_argument("--old-contact-receipt", action="append", default=[])
    parser.add_argument("--old-high-res-receipt", action="append", default=[])
    parser.add_argument("--new-reinspection-receipt", action="append", default=[])
    parser.add_argument(
        "--required-old-blocked-page",
        action="append",
        type=int,
        default=[4909],
        help=(
            "old failed full-resolution page that must remain bound as adverse history, "
            "must visibly change, and must be explicitly reinspected (repeatable)"
        ),
    )
    parser.add_argument("--delta-output")
    parser.add_argument("--inspection-output")
    parser.add_argument("--inspection-id")
    parser.add_argument("--aggregate-inspector-id", default="render-delta-inheritance-gate")
    args = parser.parse_args()

    if args.contract:
        print(json.dumps(contract(), ensure_ascii=False, indent=2))
        return 0

    page_count = int(args.page_count or 0)
    if page_count <= 0:
        raise RuntimeError("--page-count must be positive")
    old_pdf_hash = require_hex_hash(args.old_pdf_sha256, "old PDF hash")
    new_pdf = required_path(args.new_pdf, "--new-pdf")
    new_pdf_record = file_record(new_pdf)
    new_pdf_hash = str(new_pdf_record["sha256"])
    if new_pdf_hash == old_pdf_hash:
        raise RuntimeError("old and new PDF hashes are identical; delta inheritance is unnecessary")

    old_render_manifest = required_path(args.old_render_manifest, "--old-render-manifest")
    old_render_summary = required_path(args.old_render_summary, "--old-render-summary")
    old_render_dir = Path(args.old_render_dir).resolve() if args.old_render_dir else None
    if old_render_dir is not None and not old_render_dir.is_dir():
        raise FileNotFoundError(old_render_dir)
    old_render_files_reverified = old_render_dir is not None
    new_render_manifest = required_path(args.new_render_manifest, "--new-render-manifest")
    new_render_summary = required_path(args.new_render_summary, "--new-render-summary")
    new_render_dir = required_path(args.new_render_dir, "--new-render-dir")
    old_contact_manifest = required_path(args.old_contact_manifest, "--old-contact-manifest")
    new_contact_manifest = required_path(args.new_contact_manifest, "--new-contact-manifest")
    old_full_manifest = required_path(args.old_full_res_manifest, "--old-full-res-manifest")
    old_full_summary = required_path(args.old_full_res_summary, "--old-full-res-summary")
    old_full_dir = required_path(args.old_full_res_dir, "--old-full-res-dir")
    new_full_manifest = required_path(args.new_full_res_manifest, "--new-full-res-manifest")
    new_full_summary = required_path(args.new_full_res_summary, "--new-full-res-summary")
    new_full_dir = required_path(args.new_full_res_dir, "--new-full-res-dir")
    delta_output = required_path(args.delta_output, "--delta-output")
    inspection_output = required_path(args.inspection_output, "--inspection-output")
    if delta_output == inspection_output:
        raise RuntimeError("delta and inspection outputs must be distinct")
    for output in (delta_output, inspection_output):
        if output.exists():
            raise FileExistsError(
                f"refusing to overwrite an existing receipt; choose a new output path: {output}"
            )
    inspection_id = args.inspection_id or f"render-delta-{old_pdf_hash[:8]}-{new_pdf_hash[:8]}"

    old_render_order, old_render = load_page_manifest(
        old_render_manifest,
        old_render_dir,
        expected_pages=page_count,
        require_contiguous=True,
        verify_files=old_render_files_reverified,
        label="old complete render",
    )
    new_render_order, new_render = load_page_manifest(
        new_render_manifest,
        new_render_dir,
        expected_pages=page_count,
        require_contiguous=True,
        label="new complete render",
    )
    if old_render_order != new_render_order:
        raise RuntimeError("old/new complete-render page sequences differ")
    _, old_render_has_pdf_binding = validate_render_summary(
        old_render_summary,
        old_render_manifest,
        pdf_hash=old_pdf_hash,
        page_count=page_count,
        order=old_render_order,
        records=old_render,
        label="old complete-render summary",
    )
    _, new_render_has_pdf_binding = validate_render_summary(
        new_render_summary,
        new_render_manifest,
        pdf_hash=new_pdf_hash,
        page_count=page_count,
        order=new_render_order,
        records=new_render,
        label="new complete-render summary",
    )
    identical_render_pages = {
        page for page in new_render_order if page_record_equal(old_render[page], new_render[page])
    }
    changed_render_pages = set(new_render_order) - identical_render_pages

    old_sheet_order, old_sheets = load_contact_manifest(
        old_contact_manifest, page_count=page_count, label="old contact manifest"
    )
    new_sheet_order, new_sheets = load_contact_manifest(
        new_contact_manifest, page_count=page_count, label="new contact manifest"
    )
    old_contact_receipts = [Path(value).resolve() for value in args.old_contact_receipt]
    if not old_contact_receipts:
        raise RuntimeError("at least one --old-contact-receipt is required")
    old_passed_sheets, old_contact_bindings = passed_old_contact_sheets(
        old_contact_receipts, old_contact_manifest, old_sheets
    )

    inherited_sheets: set[int] = set()
    for sheet in new_sheet_order:
        new_record = new_sheets[sheet]
        old_record = old_sheets.get(sheet)
        if old_record is None or sheet not in old_passed_sheets:
            continue
        if not sheet_record_equal(old_record, new_record):
            continue
        underlying_pages = set(range(new_record["first_page"], new_record["last_page"] + 1))
        if underlying_pages.issubset(identical_render_pages):
            inherited_sheets.add(sheet)
    changed_sheets = set(new_sheet_order) - inherited_sheets
    affected_sheets = {
        (page - 1) // 20 + 1 for page in changed_render_pages
    }
    if not affected_sheets.issubset(changed_sheets):
        raise RuntimeError(
            "a contact sheet containing a changed page was incorrectly inherited: "
            f"{sorted(affected_sheets - changed_sheets)}"
        )

    old_full_order, old_full = load_page_manifest(
        old_full_manifest,
        old_full_dir,
        expected_pages=None,
        require_contiguous=False,
        label="old full-resolution render",
    )
    new_full_order, new_full = load_page_manifest(
        new_full_manifest,
        new_full_dir,
        expected_pages=None,
        require_contiguous=False,
        label="new full-resolution render",
    )
    validate_full_res_summary(
        old_full_summary,
        old_full_manifest,
        pdf_hash=old_pdf_hash,
        page_count=page_count,
        order=old_full_order,
        records=old_full,
        label="old full-resolution summary",
    )
    validate_full_res_summary(
        new_full_summary,
        new_full_manifest,
        pdf_hash=new_pdf_hash,
        page_count=page_count,
        order=new_full_order,
        records=new_full,
        label="new full-resolution summary",
    )
    old_high_receipts = [Path(value).resolve() for value in args.old_high_res_receipt]
    if not old_high_receipts:
        raise RuntimeError("at least one --old-high-res-receipt is required")
    old_passed_pages, old_blocked_pages, old_high_bindings = passed_old_high_res_pages(
        old_high_receipts, old_full_manifest, old_full_order, old_pdf_hash
    )
    required_old_blocked_pages = set(args.required_old_blocked_page)
    if any(page < 1 or page > page_count for page in required_old_blocked_pages):
        raise RuntimeError("a required old blocker page lies outside the PDF")
    if not required_old_blocked_pages.issubset(old_blocked_pages):
        raise RuntimeError(
            "required old blocker evidence is missing: "
            f"{sorted(required_old_blocked_pages - old_blocked_pages)}"
        )
    if not required_old_blocked_pages.issubset(changed_render_pages):
        raise RuntimeError(
            "the repaired old blocker page did not visibly change in the new 100-dpi render: "
            f"{sorted(required_old_blocked_pages - changed_render_pages)}"
        )

    inherited_full_pages: set[int] = set()
    for page in new_full_order:
        if page not in old_passed_pages or page not in identical_render_pages:
            continue
        old_record = old_full.get(page)
        if old_record is not None and page_record_equal(old_record, new_full[page]):
            inherited_full_pages.add(page)
    changed_full_pages = set(new_full_order) - inherited_full_pages
    required_full_resolution_reinspection_pages = (
        changed_render_pages | old_blocked_pages
    )
    missing_full_resolution_pages = (
        required_full_resolution_reinspection_pages - set(new_full_order)
    )
    if missing_full_resolution_pages:
        raise RuntimeError(
            "changed/previously blocked pages are absent from the new 200-dpi target set: "
            f"{sorted(missing_full_resolution_pages)}"
        )
    if not required_full_resolution_reinspection_pages.issubset(changed_full_pages):
        raise RuntimeError(
            "a changed/previously blocked page was incorrectly inherited at 200 dpi: "
            f"{sorted(required_full_resolution_reinspection_pages - changed_full_pages)}"
        )

    reinspection_paths = [Path(value).resolve() for value in args.new_reinspection_receipt]
    if (changed_sheets or changed_full_pages) and not reinspection_paths:
        raise RuntimeError(
            "changed images exist but no --new-reinspection-receipt was supplied: "
            f"sheets={sorted(changed_sheets)}, pages={sorted(changed_full_pages)}"
        )
    _, _, reinspection_bindings, reinspection_inspectors, reinspection_times = (
        validate_reinspection_receipts(
            reinspection_paths,
            new_pdf_hash=new_pdf_hash,
            new_contact_manifest=new_contact_manifest,
            new_full_res_manifest=new_full_manifest,
            changed_sheets=changed_sheets,
            changed_pages=changed_full_pages,
            new_sheets=new_sheets,
            new_full_order=new_full_order,
        )
    )

    contact_status = {
        sheet: (
            "inherited_byte_identical" if sheet in inherited_sheets else "reinspected_changed"
        )
        for sheet in new_sheet_order
    }
    contact_envelope = {
        sheet: (new_sheets[sheet]["first_page"], new_sheets[sheet]["last_page"])
        for sheet in new_sheet_order
    }
    full_index_order = list(range(1, len(new_full_order) + 1))
    full_status = {
        index: (
            "inherited_byte_identical"
            if new_full_order[index - 1] in inherited_full_pages
            else "reinspected_changed"
        )
        for index in full_index_order
    }
    full_envelope = {
        index: (new_full_order[index - 1], new_full_order[index - 1])
        for index in full_index_order
    }

    delta = {
        "schema": DELTA_SCHEMA,
        "status": "PASS",
        "passed": True,
        "old_pdf_sha256": old_pdf_hash,
        "new_pdf": {**new_pdf_record, "pages": page_count},
        "comparison_rule": {
            "contact_sheet_inheritance": (
                "The old and new sheet image records must be byte-identical, every underlying "
                "100-dpi page image must be byte-identical, and the old sheet must have a "
                "passing bound inspection receipt."
            ),
            "full_resolution_inheritance": (
                "The old and new 200-dpi target image records and their underlying 100-dpi page "
                "images must be byte-identical, and the old page must have passed inspection "
                "without appearing in an old blocker."
            ),
            "changed_unit_rule": (
                "Every non-inheritable new contact sheet and selected 200-dpi page must appear "
                "exactly once in an explicit passing reinspection receipt. Every changed "
                "100-dpi page and every old blocked page must be selected at 200 dpi."
            ),
        },
        "complete_render_delta": {
            "old_manifest": file_record(old_render_manifest),
            "old_summary": file_record(old_render_summary),
            "old_image_directory": (
                root_relative(old_render_dir) if old_render_dir is not None else None
            ),
            "old_image_files_reverified": old_render_files_reverified,
            "old_summary_has_pdf_sha256_binding": old_render_has_pdf_binding,
            "new_manifest": file_record(new_render_manifest),
            "new_summary": file_record(new_render_summary),
            "new_image_directory": root_relative(new_render_dir),
            "new_summary_has_pdf_sha256_binding": new_render_has_pdf_binding,
            "page_count": page_count,
            "identical_page_count": len(identical_render_pages),
            "changed_page_count": len(changed_render_pages),
            "changed_pages": sorted(changed_render_pages),
        },
        "contact_sheet_delta": {
            "old_manifest": file_record(old_contact_manifest),
            "new_manifest": file_record(new_contact_manifest),
            "new_sheet_count": len(new_sheet_order),
            "inherited_sheet_count": len(inherited_sheets),
            "inherited_sheets": sorted(inherited_sheets),
            "changed_sheet_count": len(changed_sheets),
            "changed_sheets": sorted(changed_sheets),
        },
        "full_resolution_delta": {
            "old_manifest": file_record(old_full_manifest),
            "old_summary": file_record(old_full_summary),
            "old_image_directory": root_relative(old_full_dir),
            "new_manifest": file_record(new_full_manifest),
            "new_summary": file_record(new_full_summary),
            "new_image_directory": root_relative(new_full_dir),
            "old_target_count": len(old_full_order),
            "new_target_count": len(new_full_order),
            "old_blocked_pages": sorted(old_blocked_pages),
            "required_old_blocked_pages": sorted(required_old_blocked_pages),
            "required_full_resolution_reinspection_pages": sorted(
                required_full_resolution_reinspection_pages
            ),
            "inherited_page_count": len(inherited_full_pages),
            "inherited_pages": sorted(inherited_full_pages),
            "changed_or_new_page_count": len(changed_full_pages),
            "changed_or_new_pages": sorted(changed_full_pages),
        },
        "inspection_evidence": {
            "old_contact_receipts": old_contact_bindings,
            "old_high_resolution_receipts": old_high_bindings,
            "new_reinspection_receipts": reinspection_bindings,
        },
        "adverse_evidence": [
            (
                "The prior high-resolution inspection failed on PDF page(s) "
                f"{sorted(old_blocked_pages)}. Those exact failed receipts remain bound as "
                "adverse history; the pages are not inherited and require explicit passing "
                "reinspection against the new PDF."
            )
        ]
        + [
            message
            for present, message in (
                (
                    old_render_has_pdf_binding,
                    "The legacy old complete-render summary predates an explicit pdf_sha256 "
                    "field; its exact manifest/image bytes are instead tied to the old PDF by "
                    "the bound full-resolution summary and visual-inspection evidence.",
                ),
                (
                    old_render_files_reverified,
                    "The legacy old complete-render PNG directory is unavailable; old-side "
                    "page hashes are inherited from the exact passing render summary and its "
                    "bound manifest, while every new PNG is rehashed directly.",
                ),
                (
                    new_render_has_pdf_binding,
                    "The new complete-render summary has no explicit pdf_sha256 field; its exact "
                    "manifest/image bytes are instead tied to the new PDF by the bound "
                    "full-resolution summary and changed-image reinspection evidence.",
                ),
            )
            if not present
        ],
    }
    delta_payload = json_bytes(delta)
    delta_binding = planned_file_record(delta_output, delta_payload)

    aggregate_time = max(reinspection_times, default=datetime.now(timezone.utc))
    unique_reinspectors = []
    seen_inspectors: set[tuple[str, str]] = set()
    for inspector in reinspection_inspectors:
        key = (inspector["kind"], inspector["id"])
        if key not in seen_inspectors:
            seen_inspectors.add(key)
            unique_reinspectors.append(inspector)
    aggregate = {
        "schema": AGGREGATE_RECEIPT_SCHEMA,
        "performed": True,
        "passed": True,
        "pdf_sha256": new_pdf_hash,
        "page_count": page_count,
        "contact_sheet_count": len(new_sheet_order),
        "full_resolution_target_count": len(new_full_order),
        "inspection_id": inspection_id,
        "inspector": {
            "kind": "agent",
            "id": args.aggregate_inspector_id,
        },
        "inspected_at": aggregate_time.isoformat(),
        "contact_sheet_manifest": file_record(new_contact_manifest),
        "full_resolution_manifest": file_record(new_full_manifest),
        "contact_sheet_ranges": coalesce_ranges(
            new_sheet_order,
            contact_status,
            contact_envelope,
            first_key="first_sheet",
            last_key="last_sheet",
        ),
        "full_resolution_target_ranges": coalesce_ranges(
            full_index_order,
            full_status,
            full_envelope,
            first_key="first_target_index",
            last_key="last_target_index",
        ),
        "findings": {key: 0 for key in ZERO_FINDINGS},
        "blocker_count": 0,
        "blockers": [],
        "delta_inheritance": {
            "receipt": delta_binding,
            "old_pdf_sha256": old_pdf_hash,
            "inherited_contact_sheet_count": len(inherited_sheets),
            "reinspected_contact_sheet_count": len(changed_sheets),
            "inherited_full_resolution_target_count": len(inherited_full_pages),
            "reinspected_full_resolution_target_count": len(changed_full_pages),
            "reinspection_inspectors": unique_reinspectors,
            "old_failed_full_resolution_pages": sorted(old_blocked_pages),
            "required_old_failed_full_resolution_pages": sorted(
                required_old_blocked_pages
            ),
        },
        "adverse_evidence": [
            (
                "The bound prior high-resolution inspection failed on PDF page(s) "
                f"{sorted(old_blocked_pages)}. The failure is preserved as adverse history; "
                "those pages visibly changed and were explicitly reinspected in the new PDF."
            )
        ],
    }
    aggregate_payload = json_bytes(aggregate)

    report = {
        "dry_run": bool(args.dry_run),
        "passed": True,
        "old_pdf_sha256": old_pdf_hash,
        "new_pdf_sha256": new_pdf_hash,
        "changed_render_pages": sorted(changed_render_pages),
        "changed_contact_sheets": sorted(changed_sheets),
        "changed_full_resolution_pages": sorted(changed_full_pages),
        "delta_output": planned_file_record(delta_output, delta_payload),
        "inspection_output": planned_file_record(inspection_output, aggregate_payload),
        "writes_performed": not args.dry_run,
    }
    if not args.dry_run:
        atomic_write(delta_output, delta_payload)
        atomic_write(inspection_output, aggregate_payload)
        if file_record(delta_output) != report["delta_output"]:
            raise RuntimeError("delta output identity changed during write")
        if file_record(inspection_output) != report["inspection_output"]:
            raise RuntimeError("inspection output identity changed during write")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
