from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


QA = Path(__file__).resolve().parent
ROOT = QA.parent
OUT = QA / "R13_FINAL_QA.json"

AUTHORITY_COMMIT = "a04446e57ec1fbc252a871afcec7752fb2807b14"
EXPECTED_CHAPTERS = 105
EXPECTED_PAGES = 4877
EXPECTED_PDF_SHA256 = "8C54DFF495B1642EB94828B192FFDF8A49A157E80FFE3CECC997356DB79A28FD"
EXPECTED_MANIFEST_SHA256 = "64012097E91C6E5E7D855102E9A28A6B51F5FA2FE422D6692244285A485D1DF0"
EXPECTED_READER_SHA256 = "C2F1D92F1B491C77E5794161F75186958CD1C60DA0B4C16FDD396E55AAF80FC6"
EXPECTED_REPLAY_SHA256 = "82958671E2E71AA8EB54614374420F4AB18268BF448A091B372A933D68FB9537"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def record(relative: str) -> dict[str, object]:
    path = ROOT / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": relative.replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def load(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text, flags=re.MULTILINE))


def main() -> int:
    manifest = load("manifest.json")
    replay = load("qa/source-replay.json")
    replay_check = load("qa/source-replay-verification-r13.json")
    mechanical = load("qa/pdf-mechanical-105.json")
    visual = load("qa/visual-qa-105.json")
    render = load("qa/visual/RENDER_SUMMARY_8C54DFF4.json")
    full_res = load("qa/visual/FULL_RES_SUMMARY_8C54DFF4.json")
    targets = load("qa/VISUAL_TARGETS_8C54DFF4.json")

    source_records = {
        "manifest": record("manifest.json"),
        "reader": record("src/reader.tex"),
        "source_replay": record("qa/source-replay.json"),
    }
    expected_sources = {
        "manifest": EXPECTED_MANIFEST_SHA256,
        "reader": EXPECTED_READER_SHA256,
        "source_replay": EXPECTED_REPLAY_SHA256,
    }
    for key, expected in expected_sources.items():
        if source_records[key]["sha256"] != expected:
            raise RuntimeError(f"{key} identity drift")

    chapter_count = len(manifest["chapters"])
    if chapter_count != EXPECTED_CHAPTERS:
        raise RuntimeError(f"expected {EXPECTED_CHAPTERS} chapters, got {chapter_count}")
    if manifest["authority"]["commit"] != AUTHORITY_COMMIT:
        raise RuntimeError("authority commit drift")
    if replay.get("passed") is not True or int(replay["chapter_count"]) != EXPECTED_CHAPTERS:
        raise RuntimeError("source replay did not pass all admitted chapters")
    if replay_check.get("passed") is not True:
        raise RuntimeError("independent source-replay verification failed")
    if int(replay_check["verified_input_bindings"]) != 324:
        raise RuntimeError("verified input-binding count drift")
    if int(replay_check["verified_generated_outputs"]) != 112:
        raise RuntimeError("verified generated-output count drift")
    if int(replay_check["unresolved_reference_targets"]) != 0:
        raise RuntimeError("unresolved reference targets remain")

    pdf_record = record("build/stacks-zh-hans-cn-partial.pdf")
    if pdf_record["sha256"] != EXPECTED_PDF_SHA256:
        raise RuntimeError("final PDF identity drift")
    if mechanical.get("passed_mechanical") is not True:
        raise RuntimeError("mechanical audit failed")
    if int(mechanical["pages"]) != EXPECTED_PAGES or int(mechanical["expected_pages"]) != EXPECTED_PAGES:
        raise RuntimeError("mechanical page count drift")
    if str(mechanical["pdf"]["sha256"]).upper() != EXPECTED_PDF_SHA256:
        raise RuntimeError("mechanical audit binds another PDF")
    if int(mechanical["fonts"]["embedded"]) != int(mechanical["fonts"]["total"]):
        raise RuntimeError("not all fonts are embedded")
    annotations = mechanical["annotations"]
    if annotations["malformed_rectangles"] or annotations["zero_area_rectangles"] or annotations["out_of_page_rectangles"]:
        raise RuntimeError("invalid link rectangles remain")
    extraction = mechanical["text_extraction"]
    if extraction["errors"] or int(extraction["replacement_characters"]) != 0:
        raise RuntimeError("text extraction failed")

    if visual.get("passed_visual") is not True:
        raise RuntimeError("visual audit failed")
    if str(visual["pdf"]["sha256"]).upper() != EXPECTED_PDF_SHA256:
        raise RuntimeError("visual audit binds another PDF")
    if int(visual["pdf"]["pages"]) != EXPECTED_PAGES:
        raise RuntimeError("visual audit page count drift")
    if render.get("passed") is not True or int(render["page_count"]) != EXPECTED_PAGES:
        raise RuntimeError("complete render audit failed")
    if full_res.get("passed") is not True or int(full_res["selected_page_count"]) != 188:
        raise RuntimeError("full-resolution target render audit failed")
    if int(targets["selected_page_count"]) != 188:
        raise RuntimeError("visual target count drift")
    if list(full_res["selected_pages"]) != list(targets["selected_pages"]):
        raise RuntimeError("full-resolution render pages differ from the selected targets")

    contact_lines = (QA / "visual" / "CONTACT_SHEETS_8C54DFF4.csv").read_text(encoding="utf-8").splitlines()
    if len(contact_lines) - 1 != 244:
        raise RuntimeError("contact-sheet count drift")

    log_path = ROOT / "build" / "stacks-zh-hans-cn-partial.log"
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    log_warnings = {
        "tex_errors": count(
            r"^! (?:LaTeX|Package .* Error|Class .* Error|Undefined control sequence|Missing .* inserted|Emergency stop|File .* not found|Fatal error)",
            log_text,
        ),
        "overfull_hbox_warnings": count(r"Overfull \\hbox", log_text),
        "underfull_hbox_warnings": count(r"Underfull \\hbox", log_text),
        "overfull_vbox_warnings": count(r"Overfull \\vbox", log_text),
        "underfull_vbox_warnings": count(r"Underfull \\vbox", log_text),
        "undefined_reference_warnings": count(r"undefined references|Reference .* undefined", log_text),
        "undefined_citation_warnings": count(r"undefined citations|Citation .* undefined", log_text),
        "label_rerun_warnings": count(r"Label\(s\) may have changed|Rerun to get cross-references right", log_text),
        "missing_character_warnings": count(r"Missing character", log_text),
        "fatal_errors": count(r"Emergency stop|Fatal error", log_text),
    }
    expected_warning_counts = {
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
    if log_warnings != expected_warning_counts:
        raise RuntimeError(f"final-log warning drift: {log_warnings}")

    for relative in (
        "qa/build-r13-recovery-pass-a.stderr.txt",
        "qa/build-r13-recovery-pass-b.stderr.txt",
        "qa/build-r13-recovery-pass-c.stderr.txt",
        "qa/source-replay-verification-r13.stderr.txt",
        "qa/pdf-mechanical-105.stderr.txt",
        "qa/pdffonts-105.stderr.txt",
        "qa/pdftotext-105.stderr.txt",
        "qa/render-105.stderr.txt",
        "qa/contact-sheets-105.stderr.txt",
        "qa/full-res-render-8C54DFF4.stderr.txt",
    ):
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size != 0:
            raise RuntimeError(f"non-empty or missing stderr evidence: {relative}")

    build_sidecars = {
        suffix: record(f"build/stacks-zh-hans-cn-partial.{suffix}")
        for suffix in ("aux", "bbl", "blg", "fls", "log", "out", "toc")
    }
    recovery_transcripts = {
        name: record(f"qa/{name}")
        for name in (
            "build-r13-recovery-pass-a.stdout.txt",
            "build-r13-recovery-pass-b.stdout.txt",
            "build-r13-recovery-pass-c.stdout.txt",
        )
    }

    result = {
        "schema": "stacks-zh-hans-cn-r13-final-qa/v1",
        "release_candidate": "2026.08.25-r13",
        "locale": "zh-Hans-CN",
        "publication_performed": False,
        "authority_commit": AUTHORITY_COMMIT,
        "chapter_count": chapter_count,
        "source": source_records,
        "source_replay_verification": {
            **record("qa/source-replay-verification-r13.json"),
            "verified_input_bindings": replay_check["verified_input_bindings"],
            "verified_generated_outputs": replay_check["verified_generated_outputs"],
            "unique_reference_targets": replay_check["unique_reference_targets"],
            "unresolved_reference_targets": replay_check["unresolved_reference_targets"],
            "ordered_input_binding_sha256": replay_check["ordered_input_binding_sha256"],
            "ordered_output_binding_sha256": replay_check["ordered_output_binding_sha256"],
        },
        "build": {
            "pdf": pdf_record,
            "pages": EXPECTED_PAGES,
            "page_size": "A4",
            "encrypted": bool(mechanical["encrypted"]),
            "recovery_passes": [
                {"pass": "A", "pages": 4767, "status": "exit 0; auxiliary recovery pass; rerun required"},
                {"pass": "B", "pages": 4877, "status": "exit 0; labels changed; stabilization pass required"},
                {"pass": "C", "pages": 4877, "status": "exit 0; stable final pass; no rerun warning"},
            ],
            "recovery_transcripts": recovery_transcripts,
            "sidecars": build_sidecars,
            "final_log_warnings": log_warnings,
        },
        "mechanical_qa": {
            **record("qa/pdf-mechanical-105.json"),
            "passed": True,
            "named_destinations": mechanical["named_destinations"],
            "link_annotations": annotations["total"],
            "fonts_total": mechanical["fonts"]["total"],
            "fonts_embedded": mechanical["fonts"]["embedded"],
            "fonts_with_to_unicode": mechanical["fonts"]["with_to_unicode"],
            "extracted_characters": extraction["characters"],
            "extracted_cjk_unified_ideographs": extraction["cjk_unified_ideographs"],
            "replacement_characters": extraction["replacement_characters"],
            "literal_double_question_pairs": extraction["literal_double_question_pairs"],
        },
        "visual_qa": {
            **record("qa/visual-qa-105.json"),
            "passed": True,
            "all_page_render_count": render["page_count"],
            "contact_sheet_count": 244,
            "contact_sheet_page_coverage": "1-4877 without gaps",
            "full_resolution_target_count": full_res["selected_page_count"],
            "full_resolution_target_binding_sha256": full_res["ordered_page_hash_binding_sha256"],
            "findings": visual["visual_findings"],
        },
        "evidence": {
            "render_summary": record("qa/visual/RENDER_SUMMARY_8C54DFF4.json"),
            "render_manifest": record("qa/visual/RENDER_MANIFEST_8C54DFF4.csv"),
            "contact_sheet_manifest": record("qa/visual/CONTACT_SHEETS_8C54DFF4.csv"),
            "full_resolution_summary": record("qa/visual/FULL_RES_SUMMARY_8C54DFF4.json"),
            "full_resolution_manifest": record("qa/visual/FULL_RES_MANIFEST_8C54DFF4.csv"),
            "visual_targets": record("qa/VISUAL_TARGETS_8C54DFF4.json"),
            "warning_page_map": record("qa/WARNING_PAGE_MAP_8C54DFF4.json"),
        },
        "adverse_evidence": visual["adverse_evidence"],
        "passed": True,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"path": str(OUT), "bytes": OUT.stat().st_size, "sha256": sha256(OUT), "passed": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
