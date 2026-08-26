from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import create_visual_qa_112 as visual_tool


QA = Path(__file__).resolve().parent
ROOT = QA.parent
VISUAL_QA = QA / "visual-qa-112.json"
OUT = QA / "R14_FINAL_QA.json"


def require_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} drift")


def validate_visual_receipt(
    static: dict[str, Any],
    dynamic: dict[str, Any],
) -> dict[str, Any]:
    visual = visual_tool.load_json(VISUAL_QA)
    if visual.get("schema") != "stacks-zh-hans-cn-visual-qa/v8":
        raise RuntimeError("unexpected R14 visual-QA schema")
    if visual.get("release_candidate") != "2026.08.26-r14":
        raise RuntimeError("visual-QA release-candidate drift")
    if visual.get("locale") != "zh-Hans-CN":
        raise RuntimeError("visual-QA locale drift")
    if visual.get("passed_visual") is not True:
        raise RuntimeError("R14 visual QA did not pass")

    visual_tool.assert_record(visual.get("pdf"), visual_tool.PDF, "visual-QA PDF")
    if int(visual.get("pdf", {}).get("pages", -1)) != visual_tool.EXPECTED_PAGES:
        raise RuntimeError("visual-QA PDF page-count drift")
    if visual.get("pdf", {}).get("page_size") != "A4":
        raise RuntimeError("visual-QA page-size drift")

    input_receipts = visual.get("input_receipts", {})
    visual_tool.assert_record(
        input_receipts.get("r14_build"),
        visual_tool.BUILD_RECEIPT,
        "visual-bound R14 build receipt",
    )
    visual_tool.assert_record(
        input_receipts.get("source_replay"),
        visual_tool.SOURCE_REPLAY,
        "visual-bound source replay",
    )
    visual_tool.assert_record(
        input_receipts.get("source_replay_verification"),
        visual_tool.SOURCE_REPLAY_VERIFICATION,
        "visual-bound source-replay verification",
    )
    visual_tool.assert_record(
        input_receipts.get("mechanical_qa"),
        visual_tool.MECHANICAL,
        "visual-bound mechanical QA",
    )

    render_evidence = visual.get("render_evidence", {})
    if (
        int(render_evidence.get("page_count", -1)) != visual_tool.EXPECTED_PAGES
        or int(render_evidence.get("dpi", -1)) != 100
    ):
        raise RuntimeError("visual complete-render summary drift")
    require_equal(
        render_evidence.get("ordered_page_hash_binding_sha256"),
        dynamic["render"].get("ordered_page_hash_binding_sha256"),
        "visual complete-render ordered binding",
    )
    visual_tool.assert_record(
        render_evidence.get("manifest"),
        visual_tool.RENDER_MANIFEST,
        "visual-bound complete-render manifest",
    )
    visual_tool.assert_record(
        render_evidence.get("summary"),
        visual_tool.RENDER_SUMMARY,
        "visual-bound complete-render summary",
    )

    contact_evidence = visual.get("contact_sheet_evidence", {})
    if int(contact_evidence.get("count", -1)) != visual_tool.EXPECTED_CONTACT_SHEETS:
        raise RuntimeError("visual contact-sheet count drift")
    if contact_evidence.get("page_coverage") != "1-5546 without gaps":
        raise RuntimeError("visual contact-sheet coverage drift")
    visual_tool.assert_record(
        contact_evidence.get("manifest"),
        visual_tool.CONTACT_MANIFEST,
        "visual-bound contact-sheet manifest",
    )

    full_res_evidence = visual.get("full_resolution_evidence", {})
    if (
        int(full_res_evidence.get("dpi", -1)) != 200
        or int(full_res_evidence.get("target_count", -1))
        != visual_tool.EXPECTED_FULL_RES_TARGETS
    ):
        raise RuntimeError("visual full-resolution summary drift")
    require_equal(
        [int(page) for page in full_res_evidence.get("selected_pages", [])],
        static["selected_pages"],
        "visual full-resolution target sequence",
    )
    require_equal(
        full_res_evidence.get("ordered_page_hash_binding_sha256"),
        dynamic["full_res"].get("ordered_page_hash_binding_sha256"),
        "visual full-resolution ordered binding",
    )
    visual_tool.assert_record(
        full_res_evidence.get("manifest"),
        visual_tool.FULL_RES_MANIFEST,
        "visual-bound full-resolution manifest",
    )
    visual_tool.assert_record(
        full_res_evidence.get("summary"),
        visual_tool.FULL_RES_SUMMARY,
        "visual-bound full-resolution summary",
    )
    visual_tool.assert_record(
        full_res_evidence.get("targets"),
        visual_tool.TARGETS,
        "visual-bound target receipt",
    )
    warning_binding = full_res_evidence.get("warning_page_map", {})
    visual_tool.assert_record(
        warning_binding,
        visual_tool.WARNING_MAP,
        "visual-bound warning-page map",
    )
    if (
        int(warning_binding.get("mapped_warning_records", -1))
        != visual_tool.EXPECTED_WARNING_RECORDS
        or int(warning_binding.get("unique_warning_pages", -1))
        != visual_tool.EXPECTED_WARNING_PAGES
        or int(warning_binding.get("unmapped_warnings", -1)) != 0
    ):
        raise RuntimeError("visual warning-page disposition drift")

    inspection = dynamic["inspection"]
    inspection_evidence = visual.get("inspection_evidence", {})
    visual_tool.assert_record(
        inspection_evidence.get("receipt"),
        visual_tool.INSPECTION_RECEIPT,
        "visual-bound explicit inspection receipt",
    )
    for key in ("inspection_id", "inspector", "inspected_at"):
        require_equal(
            inspection_evidence.get(key),
            inspection.get(key),
            f"visual inspection {key}",
        )
    require_equal(
        inspection_evidence.get("contact_sheet_ranges"),
        inspection.get("contact_sheet_ranges"),
        "visual contact-sheet inspection ranges",
    )
    require_equal(
        inspection_evidence.get("full_resolution_target_ranges"),
        inspection.get("full_resolution_target_ranges"),
        "visual full-resolution inspection ranges",
    )
    if (
        int(inspection_evidence.get("blocker_count", -1)) != 0
        or inspection_evidence.get("blockers") != []
    ):
        raise RuntimeError("visual receipt contains inspection blockers")
    expected_findings = {
        key: 0 for key in visual_tool.REQUIRED_ZERO_FINDINGS
    }
    require_equal(
        inspection_evidence.get("findings"),
        expected_findings,
        "visual zero-finding disposition",
    )
    visual_tool.assert_record(
        inspection_evidence.get("delta_receipt"),
        dynamic["delta_path"],
        "visual-bound render delta",
    )
    require_equal(
        inspection_evidence.get("delta_inheritance"),
        inspection.get("delta_inheritance"),
        "visual delta-inheritance disposition",
    )
    prior_failed_pages = [
        int(page) for page in inspection_evidence.get("prior_failed_visual_pages", [])
    ]
    if 4909 not in prior_failed_pages:
        raise RuntimeError("visual receipt drops the prior page-4909 failure history")

    mechanical = static["mechanical"]
    mechanical_cross_check = visual.get("mechanical_cross_check", {})
    expected_mechanical = {
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
    }
    require_equal(
        mechanical_cross_check,
        expected_mechanical,
        "visual mechanical cross-check",
    )

    build_cross_check = visual.get("build_log_cross_check", {})
    visual_tool.assert_record(
        build_cross_check,
        visual_tool.LOG,
        "visual-bound final log",
    )
    require_equal(
        build_cross_check.get("blocking_condition_counts"),
        visual_tool.EXPECTED_BLOCKING_COUNTS,
        "visual blocking diagnostic counts",
    )
    require_equal(
        build_cross_check.get("nonblocking_counts"),
        visual_tool.EXPECTED_NONBLOCKING_COUNTS,
        "visual nonblocking diagnostic counts",
    )

    stderr_evidence = visual.get("stderr_evidence", {})
    for path in (
        visual_tool.RENDER_STDERR,
        visual_tool.CONTACT_STDERR,
        visual_tool.FULL_RES_STDERR,
    ):
        visual_tool.assert_record(
            stderr_evidence.get(path.name),
            path,
            f"visual-bound {path.name}",
        )
        if path.stat().st_size != 0:
            raise RuntimeError(f"non-empty renderer stderr: {visual_tool.relative(path)}")

    adverse = visual.get("adverse_evidence")
    if not isinstance(adverse, list) or not adverse:
        raise RuntimeError("visual adverse-evidence disclosure is missing")
    if not any("4909" in str(item) for item in adverse):
        raise RuntimeError("visual adverse evidence does not disclose the old page-4909 failure")
    return visual


def create_result(
    static: dict[str, Any],
    dynamic: dict[str, Any],
    visual: dict[str, Any],
) -> dict[str, Any]:
    replay_check = static["replay_check"]
    mechanical = static["mechanical"]
    build = static["build"]
    return {
        "schema": "stacks-zh-hans-cn-r14-final-qa/v1",
        "release_candidate": "2026.08.26-r14",
        "locale": "zh-Hans-CN",
        "publication_performed": False,
        "authority_commit": visual_tool.EXPECTED_AUTHORITY_COMMIT,
        "chapter_count": visual_tool.EXPECTED_CHAPTERS,
        "pdf": {
            **visual_tool.file_record(visual_tool.PDF),
            "pages": visual_tool.EXPECTED_PAGES,
            "page_size": "A4",
            "encrypted": bool(mechanical["encrypted"]),
        },
        "source": {
            "manifest": visual_tool.file_record(visual_tool.SOURCE_MANIFEST),
            "reader": visual_tool.file_record(visual_tool.READER),
            "source_replay": visual_tool.file_record(visual_tool.SOURCE_REPLAY),
        },
        "source_replay_verification": {
            **visual_tool.file_record(visual_tool.SOURCE_REPLAY_VERIFICATION),
            "verified_input_bindings": int(replay_check["verified_input_bindings"]),
            "verified_generated_outputs": int(
                replay_check["verified_generated_outputs"]
            ),
            "unique_reference_targets": int(replay_check["unique_reference_targets"]),
            "unresolved_reference_targets": int(
                replay_check["unresolved_reference_targets"]
            ),
            "ordered_input_binding_sha256": replay_check[
                "ordered_input_binding_sha256"
            ],
            "ordered_output_binding_sha256": replay_check[
                "ordered_output_binding_sha256"
            ],
            "passed": True,
        },
        "build_qa": {
            **visual_tool.file_record(visual_tool.BUILD_RECEIPT),
            "status": build["status"],
            "passed": True,
            "final_log": visual_tool.file_record(visual_tool.LOG),
            "final_fls": visual_tool.file_record(visual_tool.FLS),
            "blocking_condition_counts": build["diagnostics"][
                "blocking_condition_counts"
            ],
            "nonblocking_counts": build["diagnostics"]["nonblocking_counts"],
        },
        "mechanical_qa": {
            **visual_tool.file_record(visual_tool.MECHANICAL),
            "passed": True,
            "named_destinations": int(mechanical["named_destinations"]),
            "link_annotations": int(mechanical["annotations"]["total"]),
            "fonts_total": int(mechanical["fonts"]["total"]),
            "fonts_embedded": int(mechanical["fonts"]["embedded"]),
            "fonts_with_to_unicode": int(mechanical["fonts"]["with_to_unicode"]),
            "extracted_characters": int(
                mechanical["text_extraction"]["characters"]
            ),
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
        "visual_qa": {
            **visual_tool.file_record(VISUAL_QA),
            "passed": True,
            "all_page_render_count": int(dynamic["render"]["page_count"]),
            "contact_sheet_count": visual_tool.EXPECTED_CONTACT_SHEETS,
            "contact_sheet_page_coverage": "1-5546 without gaps",
            "full_resolution_target_count": int(
                dynamic["full_res"]["selected_page_count"]
            ),
            "full_resolution_target_binding_sha256": dynamic["full_res"][
                "ordered_page_hash_binding_sha256"
            ],
            "inspection_receipt": visual_tool.file_record(
                visual_tool.INSPECTION_RECEIPT
            ),
            "render_delta_receipt": visual_tool.file_record(dynamic["delta_path"]),
            "inspection_id": dynamic["inspection"]["inspection_id"],
            "blocker_count": 0,
            "findings": visual["inspection_evidence"]["findings"],
        },
        "receipt_bindings": {
            "r14_build": visual_tool.file_record(visual_tool.BUILD_RECEIPT),
            "source_replay": visual_tool.file_record(visual_tool.SOURCE_REPLAY),
            "source_replay_verification": visual_tool.file_record(
                visual_tool.SOURCE_REPLAY_VERIFICATION
            ),
            "mechanical": visual_tool.file_record(visual_tool.MECHANICAL),
            "render_summary": visual_tool.file_record(visual_tool.RENDER_SUMMARY),
            "full_resolution_summary": visual_tool.file_record(
                visual_tool.FULL_RES_SUMMARY
            ),
            "explicit_visual_inspection": visual_tool.file_record(
                visual_tool.INSPECTION_RECEIPT
            ),
            "render_delta": visual_tool.file_record(dynamic["delta_path"]),
            "visual_qa": visual_tool.file_record(VISUAL_QA),
        },
        "evidence": {
            "render_manifest": visual_tool.file_record(
                visual_tool.RENDER_MANIFEST
            ),
            "contact_sheet_manifest": visual_tool.file_record(
                visual_tool.CONTACT_MANIFEST
            ),
            "full_resolution_manifest": visual_tool.file_record(
                visual_tool.FULL_RES_MANIFEST
            ),
            "visual_targets": visual_tool.file_record(visual_tool.TARGETS),
            "warning_page_map": visual_tool.file_record(visual_tool.WARNING_MAP),
            "render_delta": visual_tool.file_record(dynamic["delta_path"]),
            "renderer_stderr": dynamic["stderr_records"],
        },
        "tooling": {
            "full_resolution_auditor": visual_tool.file_record(
                QA / "audit_full_res_targets_r14.py"
            ),
            "visual_qa_builder": visual_tool.file_record(
                QA / "create_visual_qa_112.py"
            ),
            "delta_inspection_builder": visual_tool.file_record(
                QA / "create_visual_inspection_delta_r14.py"
            ),
            "final_qa_builder": visual_tool.file_record(__file_path()),
        },
        "adverse_evidence": visual["adverse_evidence"],
        "passed": True,
    }


def __file_path() -> Path:
    return Path(__file__).resolve()


def missing_final_requirements() -> list[str]:
    missing = visual_tool.missing_dynamic_requirements()
    if not VISUAL_QA.is_file():
        missing.append(visual_tool.relative(VISUAL_QA))
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create the R14 final-QA receipt only after every static and dynamic "
            "receipt binding, including explicit visual inspection, validates."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate available inputs and print missing receipts without writing",
    )
    parser.add_argument(
        "--contract",
        action="store_true",
        help="print the bound visual/delta contract without reading the live PDF",
    )
    args = parser.parse_args()

    if args.contract:
        print(
            json.dumps(
                {
                    "schema": "stacks-zh-hans-cn-r14-final-qa-contract/v1",
                    "visual_builder": visual_tool.builder_contract(),
                    "required_additional_final_binding": (
                        "The visual-QA receipt and final-QA receipt must both bind the exact "
                        "render-delta receipt, including the preserved old page-4909 failure."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    static = visual_tool.validate_static_inputs()
    missing = missing_final_requirements()
    if args.dry_run and missing:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "static_inputs_valid": True,
                    "final_evidence_ready": False,
                    "writes_performed": False,
                    "missing": missing,
                    "inspection_receipt_contract": visual_tool.inspection_contract(),
                    "would_write": [visual_tool.relative(OUT)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    dynamic = visual_tool.validate_dynamic_inputs(static)
    if not VISUAL_QA.is_file():
        raise FileNotFoundError(VISUAL_QA)
    visual = validate_visual_receipt(static, dynamic)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "static_inputs_valid": True,
                    "final_evidence_ready": True,
                    "all_receipt_bindings_valid": True,
                    "writes_performed": False,
                    "would_write": [visual_tool.relative(OUT)],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    result = create_result(static, dynamic, visual)
    OUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "path": visual_tool.relative(OUT),
                "bytes": OUT.stat().st_size,
                "sha256": visual_tool.sha256(OUT),
                "passed": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
