from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject


QA = Path(__file__).resolve().parent
ROOT = QA.parent
BUILD = ROOT / "build"
JOB = "stacks-zh-hans-cn-partial"

PDF = BUILD / f"{JOB}.pdf"
LOG = BUILD / f"{JOB}.log"
FLS = BUILD / f"{JOB}.fls"
SIDECARS = {
    extension: BUILD / f"{JOB}.{extension}"
    for extension in ("aux", "bbl", "blg", "out", "toc")
}

MANIFEST = ROOT / "manifest.json"
READER = ROOT / "src" / "reader.tex"
SOURCE_REPLAY = QA / "source-replay.json"
SOURCE_REPLAY_VERIFICATION = QA / "source-replay-verification-r14.json"
SOURCE_REPLAY_VERIFIER = QA / "verify_source_replay_r14.py"
BUILD_SCRIPT = ROOT / "build.ps1"
COMPOSE_SCRIPT = ROOT / "compose.py"

MECHANICAL_OUT = QA / "pdf-mechanical-112.json"
BUILD_RECEIPT_OUT = QA / "R14_BUILD_RECEIPT.json"

EXPECTED_AUTHORITY_COMMIT = "a04446e57ec1fbc252a871afcec7752fb2807b14"
EXPECTED_RELEASE = "2026.08.26-r14"
EXPECTED_CHAPTERS = 112
EXPECTED_PAGES = 5_546
EXPECTED_FRONTMATTER_PAGES = 75
EXPECTED_BODY_PAGES = EXPECTED_PAGES - EXPECTED_FRONTMATTER_PAGES
EXPECTED_A4 = (595.28, 841.89)
EXPECTED_INPUT_BINDINGS = 345
EXPECTED_GENERATED_OUTPUTS = 119
EXPECTED_REFERENCE_TARGETS = 16_047


class ReceiptError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def file_record(path: Path, *, absolute: bool = False) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.resolve()) if absolute else relative(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def bytes_record(path: Path, data: bytes) -> dict[str, object]:
    return {
        "path": relative(path),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReceiptError(f"expected a JSON object: {path}")
    return value


def resolve_record_path(value: object) -> Path:
    candidate = Path(str(value))
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def assert_record(binding: object, path: Path, label: str) -> None:
    if not isinstance(binding, dict):
        raise ReceiptError(f"{label} is not a file binding")
    if resolve_record_path(binding.get("path")) != path.resolve():
        raise ReceiptError(f"{label} path drift")
    if int(binding.get("bytes", -1)) != path.stat().st_size:
        raise ReceiptError(f"{label} byte-count drift")
    if str(binding.get("sha256", "")).upper() != sha256(path):
        raise ReceiptError(f"{label} hash drift")


def require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReceiptError(f"{label} is not an object")
    return value


def validate_static_inputs(*, shallow: bool) -> dict[str, Any]:
    required = (
        MANIFEST,
        READER,
        SOURCE_REPLAY,
        SOURCE_REPLAY_VERIFICATION,
        SOURCE_REPLAY_VERIFIER,
        BUILD_SCRIPT,
        COMPOSE_SCRIPT,
    )
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise ReceiptError("missing static input(s): " + ", ".join(map(str, missing)))

    manifest = load_json(MANIFEST)
    chapters = manifest.get("chapters")
    if not isinstance(chapters, list) or len(chapters) != EXPECTED_CHAPTERS:
        raise ReceiptError("manifest does not contain exactly 112 chapters")
    authority = require_object(manifest.get("authority"), "manifest.authority")
    if authority.get("commit") != EXPECTED_AUTHORITY_COMMIT:
        raise ReceiptError("manifest authority commit drift")

    replay = load_json(SOURCE_REPLAY)
    replay_check = load_json(SOURCE_REPLAY_VERIFICATION)
    if replay.get("schema") != "stacks-zh-hans-cn-source-replay/v1":
        raise ReceiptError("unexpected source-replay schema")
    if replay_check.get("schema") != "stacks-zh-hans-cn-source-replay-verification/v1":
        raise ReceiptError("unexpected source-replay-verification schema")

    if shallow:
        return {"manifest": manifest, "replay": replay, "replay_check": replay_check}

    if replay.get("passed") is not True:
        raise ReceiptError("source replay is not passing")
    if int(replay.get("chapter_count", -1)) != EXPECTED_CHAPTERS:
        raise ReceiptError("source-replay chapter-count drift")
    if replay.get("authority_commit") != EXPECTED_AUTHORITY_COMMIT:
        raise ReceiptError("source-replay authority drift")
    assert_record(replay.get("manifest"), MANIFEST, "source replay manifest")
    reference_resolution = require_object(
        replay.get("reference_resolution"), "source replay reference_resolution"
    )
    if list(reference_resolution.get("unresolved_targets") or []):
        raise ReceiptError("source replay has unresolved reference targets")

    verified_inputs = replay.get("verified_inputs")
    generated_outputs = replay.get("generated_outputs")
    if not isinstance(verified_inputs, list) or len(verified_inputs) != EXPECTED_INPUT_BINDINGS:
        raise ReceiptError("source replay verified-input count drift")
    if not isinstance(generated_outputs, list) or len(generated_outputs) != EXPECTED_GENERATED_OUTPUTS:
        raise ReceiptError("source replay generated-output count drift")
    for index, record in enumerate(verified_inputs):
        if not isinstance(record, dict):
            raise ReceiptError(f"source replay input {index} is not a binding")
        path = Path(str(record.get("path"))).resolve()
        assert_record(record, path, f"source replay input {index}")
    for index, record in enumerate(generated_outputs):
        if not isinstance(record, dict):
            raise ReceiptError(f"source replay output {index} is not a binding")
        path = Path(str(record.get("path"))).resolve()
        assert_record(record, path, f"source replay output {index}")

    if replay_check.get("passed") is not True:
        raise ReceiptError("source-replay verification is not passing")
    expected_numbers = {
        "chapter_count": EXPECTED_CHAPTERS,
        "verified_input_bindings": EXPECTED_INPUT_BINDINGS,
        "verified_generated_outputs": EXPECTED_GENERATED_OUTPUTS,
        "unique_reference_targets": EXPECTED_REFERENCE_TARGETS,
        "unresolved_reference_targets": 0,
    }
    for key, expected in expected_numbers.items():
        if int(replay_check.get(key, -1)) != expected:
            raise ReceiptError(
                f"source-replay verification {key} drift: "
                f"{replay_check.get(key)!r} != {expected}"
            )
    assert_record(
        replay_check.get("source_replay"), SOURCE_REPLAY, "verified source replay"
    )
    assert_record(replay_check.get("manifest"), MANIFEST, "verified manifest")
    stacks_forward = require_object(
        replay_check.get("stacks_sheaves_forward_replay"),
        "source replay verification stacks_sheaves_forward_replay",
    )
    if stacks_forward.get("equals_generated_output") is not True:
        raise ReceiptError("stacks-sheaves forward replay is not passing")
    return {"manifest": manifest, "replay": replay, "replay_check": replay_check}


def dereference(value: object) -> object:
    return value.get_object() if isinstance(value, IndirectObject) else value


def object_key(value: object) -> str:
    if isinstance(value, IndirectObject):
        return f"{value.idnum}:{value.generation}"
    return f"direct:{id(value)}"


def rectangle_values(value: object) -> list[float] | None:
    value = dereference(value)
    if not isinstance(value, ArrayObject) or len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def make_mechanical_audit() -> dict[str, Any]:
    reader = PdfReader(str(PDF), strict=False)
    if reader.is_encrypted:
        raise ReceiptError("release PDF is encrypted")

    page_sizes: Counter[tuple[float, float]] = Counter()
    rotations: Counter[int] = Counter()
    annotation_subtypes: Counter[str] = Counter()
    annotations = 0
    malformed_rectangles: list[dict[str, object]] = []
    zero_area_rectangles: list[dict[str, object]] = []
    out_of_page_rectangles: list[dict[str, object]] = []
    content_stream_bytes: list[int] = []
    text_chars_by_page: list[int] = []
    cjk_by_page: list[int] = []
    extracted_text_parts: list[str] = []
    extraction_errors: list[dict[str, object]] = []
    font_records: dict[str, dict[str, Any]] = {}

    for page_number, page in enumerate(reader.pages, start=1):
        media = page.mediabox
        width = float(media.right) - float(media.left)
        height = float(media.top) - float(media.bottom)
        page_sizes[(round(width, 4), round(height, 4))] += 1
        rotations[int(page.get("/Rotate", 0) or 0)] += 1

        contents = page.get_contents()
        if contents is None:
            content_stream_bytes.append(0)
        else:
            try:
                content_stream_bytes.append(len(contents.get_data()))
            except Exception:
                content_stream_bytes.append(-1)

        try:
            text = page.extract_text() or ""
        except Exception as error:
            text = ""
            extraction_errors.append({"page": page_number, "error": repr(error)})
        extracted_text_parts.append(text)
        text_chars_by_page.append(len(text))
        cjk_by_page.append(sum("\u4e00" <= char <= "\u9fff" for char in text))

        resources = dereference(page.get("/Resources", {}))
        fonts = (
            dereference(resources.get("/Font", {}))
            if isinstance(resources, DictionaryObject)
            else {}
        )
        if isinstance(fonts, DictionaryObject):
            for resource_name, font_ref in fonts.items():
                key = object_key(font_ref)
                font = dereference(font_ref)
                descriptor = (
                    dereference(font.get("/FontDescriptor", {}))
                    if isinstance(font, DictionaryObject)
                    else {}
                )
                descendants = (
                    dereference(font.get("/DescendantFonts", []))
                    if isinstance(font, DictionaryObject)
                    else []
                )
                if isinstance(descendants, ArrayObject) and descendants:
                    descendant = dereference(descendants[0])
                    if isinstance(descendant, DictionaryObject):
                        descendant_descriptor = dereference(
                            descendant.get("/FontDescriptor", {})
                        )
                        if isinstance(descendant_descriptor, DictionaryObject):
                            descriptor = descendant_descriptor
                embedded = bool(
                    isinstance(descriptor, DictionaryObject)
                    and any(
                        name in descriptor
                        for name in ("/FontFile", "/FontFile2", "/FontFile3")
                    )
                )
                record = font_records.setdefault(
                    key,
                    {
                        "resource_names": set(),
                        "base_font": str(font.get("/BaseFont", ""))
                        if isinstance(font, DictionaryObject)
                        else "",
                        "subtype": str(font.get("/Subtype", ""))
                        if isinstance(font, DictionaryObject)
                        else "",
                        "embedded": embedded,
                        "to_unicode": bool(
                            isinstance(font, DictionaryObject)
                            and font.get("/ToUnicode")
                        ),
                        "pages": set(),
                    },
                )
                record["resource_names"].add(str(resource_name))
                record["pages"].add(page_number)

        annots = dereference(page.get("/Annots", []))
        if isinstance(annots, ArrayObject):
            for annot_ref in annots:
                annot = dereference(annot_ref)
                if not isinstance(annot, DictionaryObject):
                    continue
                annotations += 1
                subtype = str(annot.get("/Subtype", ""))
                annotation_subtypes[subtype] += 1
                rect = rectangle_values(annot.get("/Rect"))
                if rect is None:
                    malformed_rectangles.append(
                        {"page": page_number, "subtype": subtype}
                    )
                    continue
                x0, y0, x1, y1 = rect
                if x1 <= x0 or y1 <= y0:
                    zero_area_rectangles.append(
                        {"page": page_number, "rect": rect, "subtype": subtype}
                    )
                epsilon = 0.01
                if (
                    x0 < float(media.left) - epsilon
                    or y0 < float(media.bottom) - epsilon
                    or x1 > float(media.right) + epsilon
                    or y1 > float(media.top) + epsilon
                ):
                    out_of_page_rectangles.append(
                        {"page": page_number, "rect": rect, "subtype": subtype}
                    )

    extracted_text = "\n".join(extracted_text_parts)
    root_object = dereference(reader.trailer["/Root"])
    serializable_fonts = []
    for key, record in sorted(font_records.items()):
        serializable_fonts.append(
            {
                "object": key,
                "resource_names": sorted(record["resource_names"]),
                "base_font": record["base_font"],
                "subtype": record["subtype"],
                "embedded": record["embedded"],
                "to_unicode": record["to_unicode"],
                "first_page": min(record["pages"]),
                "last_page": max(record["pages"]),
            }
        )

    page_labels = getattr(reader, "page_labels", None)
    a4_only = page_sizes == Counter({EXPECTED_A4: EXPECTED_PAGES})
    all_unrotated = rotations == Counter({0: EXPECTED_PAGES})
    all_fonts_embedded = bool(serializable_fonts) and all(
        record["embedded"] for record in serializable_fonts
    )
    links = int(annotation_subtypes.get("/Link", 0))
    passed = bool(
        len(reader.pages) == EXPECTED_PAGES
        and a4_only
        and all_unrotated
        and not reader.is_encrypted
        and len(reader.named_destinations) > 0
        and links > 0
        and links == annotations
        and not malformed_rectangles
        and not zero_area_rectangles
        and not out_of_page_rectangles
        and all_fonts_embedded
        and not extraction_errors
        and all(value > 0 for value in text_chars_by_page)
        and all(value > 0 for value in content_stream_bytes)
        and extracted_text.count("\ufffd") == 0
        and sum("\u4e00" <= char <= "\u9fff" for char in extracted_text) > 0
        and isinstance(page_labels, list)
        and len(page_labels) == EXPECTED_PAGES
    )

    result: dict[str, Any] = {
        "schema": "stacks-zh-hans-cn-pdf-audit/v1",
        "pdf": file_record(PDF),
        "pages": len(reader.pages),
        "expected_pages": EXPECTED_PAGES,
        "page_sizes_points": [
            {"width": width, "height": height, "count": count}
            for (width, height), count in sorted(page_sizes.items())
        ],
        "rotations": {
            str(rotation): count for rotation, count in sorted(rotations.items())
        },
        "page_labels": page_labels,
        "metadata": {
            str(key): str(value) for key, value in (reader.metadata or {}).items()
        },
        "encrypted": reader.is_encrypted,
        "named_destinations": len(reader.named_destinations),
        "annotations": {
            "total": annotations,
            "subtypes": dict(annotation_subtypes),
            "malformed_rectangles": malformed_rectangles,
            "zero_area_rectangles": zero_area_rectangles,
            "out_of_page_rectangles": out_of_page_rectangles,
        },
        "fonts": {
            "total": len(serializable_fonts),
            "embedded": sum(record["embedded"] for record in serializable_fonts),
            "with_to_unicode": sum(
                record["to_unicode"] for record in serializable_fonts
            ),
            "records": serializable_fonts,
        },
        "accessibility": {
            "struct_tree_root": bool(
                isinstance(root_object, DictionaryObject)
                and root_object.get("/StructTreeRoot")
            ),
            "mark_info": bool(
                isinstance(root_object, DictionaryObject)
                and root_object.get("/MarkInfo")
            ),
        },
        "text_extraction": {
            "characters": len(extracted_text),
            "cjk_unified_ideographs": sum(
                "\u4e00" <= char <= "\u9fff" for char in extracted_text
            ),
            "replacement_characters": extracted_text.count("\ufffd"),
            "literal_double_question_pairs": extracted_text.count("??"),
            "errors": extraction_errors,
            "characters_by_page": text_chars_by_page,
            "cjk_by_page": cjk_by_page,
        },
        "content_stream_bytes": content_stream_bytes,
        "validation": {
            "a4_only": a4_only,
            "all_pages_unrotated": all_unrotated,
            "all_annotations_are_links": links == annotations and annotations > 0,
            "all_fonts_embedded": all_fonts_embedded,
            "all_pages_have_extractable_text": all(
                value > 0 for value in text_chars_by_page
            ),
            "all_pages_have_content_stream_bytes": all(
                value > 0 for value in content_stream_bytes
            ),
        },
        "passed_mechanical": passed,
    }
    if not passed:
        raise ReceiptError("mechanical PDF audit did not pass")
    return result


def portable_text(text: str) -> str:
    private = Path.home().name
    if not private:
        return text
    return re.sub(re.escape(private), "<USER>", text, flags=re.IGNORECASE)


def line_number(line_starts: list[int], offset: int) -> int:
    return bisect.bisect_right(line_starts, offset)


SHIPOUT_CANDIDATE = re.compile(
    r"\[(?P<head>\d+)(?:\r?\n(?P<tail>\d+))?[ \t\r\n]*\]"
)


def box_diagnostic_lines(text: str) -> set[int]:
    result: set[int] = set()
    active = False
    for number, value in enumerate(text.splitlines(), start=1):
        if re.match(r"^(?:Over|Under)full \\[hv]box\b", value):
            active = True
        elif not value.strip():
            active = False
        if active:
            result.add(number)
    return result


def shipout_records(text: str, line_starts: list[int]) -> list[dict[str, int]]:
    expected_tex_pages = [
        *range(EXPECTED_FRONTMATTER_PAGES),
        *range(1, EXPECTED_BODY_PAGES + 1),
    ]
    if len(expected_tex_pages) != EXPECTED_PAGES:
        raise ReceiptError("internal expected shipout sequence drift")

    candidates: list[dict[str, int]] = []
    for match in SHIPOUT_CANDIDATE.finditer(text):
        candidates.append(
            {
                "tex_page": int(match.group("head") + (match.group("tail") or "")),
                "offset": match.start(),
                "log_line": line_number(line_starts, match.start()),
            }
        )

    # Select the expected sequence twice: greedily from the front and greedily
    # from the back.  Equality of the two selections proves that the embedding
    # is unique.  This accepts a genuinely wrapped marker such as ``[534\n5]``
    # while failing closed if a bracketed number in diagnostic output could be
    # mistaken for the next shipout.
    earliest: list[int] = []
    candidate_index = 0
    for expected in expected_tex_pages:
        while (
            candidate_index < len(candidates)
            and candidates[candidate_index]["tex_page"] != expected
        ):
            candidate_index += 1
        if candidate_index == len(candidates):
            raise ReceiptError(
                "shipout sequence is incomplete in the forward replay: "
                f"next expected TeX page {expected}"
            )
        earliest.append(candidate_index)
        candidate_index += 1

    latest = [-1] * EXPECTED_PAGES
    candidate_index = len(candidates) - 1
    for expected_index in range(EXPECTED_PAGES - 1, -1, -1):
        expected = expected_tex_pages[expected_index]
        while (
            candidate_index >= 0
            and candidates[candidate_index]["tex_page"] != expected
        ):
            candidate_index -= 1
        if candidate_index < 0:
            raise ReceiptError(
                "shipout sequence is incomplete in the backward replay: "
                f"next expected TeX page {expected}"
            )
        latest[expected_index] = candidate_index
        candidate_index -= 1

    if earliest != latest:
        first = next(
            index
            for index, (front, back) in enumerate(zip(earliest, latest))
            if front != back
        )
        raise ReceiptError(
            "ambiguous shipout sequence: expected physical page "
            f"{first + 1} (TeX page {expected_tex_pages[first]}) can bind to "
            f"candidate {earliest[first] + 1} or {latest[first] + 1}"
        )

    selected = set(earliest)
    diagnostic_lines = box_diagnostic_lines(text)
    unexplained = [
        candidates[index]
        for index in range(len(candidates))
        if index not in selected and candidates[index]["log_line"] not in diagnostic_lines
    ]
    if unexplained:
        first = unexplained[0]
        raise ReceiptError(
            "unexplained numeric bracket token outside a box diagnostic at log "
            f"line {first['log_line']}: [{first['tex_page']}]"
        )

    return [
        {
            "physical_page": physical_page,
            **candidates[index],
        }
        for physical_page, index in enumerate(earliest, start=1)
    ]


def neighboring_shipouts(
    offset: int, shipouts: list[dict[str, int]]
) -> tuple[int | None, int | None, int | None]:
    offsets = [record["offset"] for record in shipouts]
    index = bisect.bisect_right(offsets, offset)
    preceding = shipouts[index - 1]["tex_page"] if index else None
    if index >= len(shipouts):
        return preceding, None, None
    following = shipouts[index]["tex_page"]
    return preceding, following, shipouts[index]["physical_page"]


def warning_block(lines: list[str], start: int) -> list[str]:
    block = [lines[start]]
    index = start + 1
    while index < len(lines) and len(block) < 12:
        value = lines[index]
        if not value.strip():
            break
        if re.match(
            r"^(?:(?:LaTeX(?: Font)?|Package \S+) Warning:|(?:Over|Under)full \\[hv]box|! )",
            value,
        ):
            break
        if value.startswith((" ", "(", "[")):
            block.append(value)
            index += 1
            continue
        break
    return [portable_text(value) for value in block]


def classify_warning(text: str) -> str:
    if "requested release" in text:
        return "latex_release_request_newer_than_available"
    if "Foreign command" in text:
        return "amsmath_foreign_command"
    if "Token not allowed in a PDF string" in text:
        return "hyperref_pdf_string_token_removed"
    if "invalid in math mode" in text:
        return "font_command_small_invalid_in_math_mode"
    if re.search(r"Reference .* undefined|undefined references?", text, re.IGNORECASE):
        return "undefined_reference_warning"
    if re.search(r"Citation .* undefined|undefined citations?", text, re.IGNORECASE):
        return "undefined_citation_warning"
    return "other_latex_or_package_warning"


def find_line_records(
    lines: list[str], pattern: re.Pattern[str]
) -> list[dict[str, object]]:
    return [
        {"log_line": index, "text": portable_text(value)}
        for index, value in enumerate(lines, start=1)
        if pattern.search(value)
    ]


def parse_log() -> dict[str, Any]:
    text = LOG.read_text(encoding="utf-8", errors="replace")
    if "\ufffd" in text:
        raise ReceiptError("final log is not valid UTF-8/ASCII-decodable text")
    lines = text.splitlines()
    line_starts = []
    offset = 0
    for value in text.splitlines(keepends=True):
        line_starts.append(offset)
        offset += len(value)
    shipouts = shipout_records(text, line_starts)

    box_pattern = re.compile(
        r"^(Over|Under)full \\([hv])box \(([^)]*)\)"
        r"(?: has occurred)?(?: in paragraph at lines ([0-9]+--[0-9]+))?"
    )
    box_records: list[dict[str, object]] = []
    box_line_indices: list[int] = []
    for index, value in enumerate(lines):
        match = box_pattern.match(value)
        if not match:
            continue
        start_offset = line_starts[index]
        preceding, following, physical = neighboring_shipouts(start_offset, shipouts)
        kind = f"{match.group(1).lower()}_{match.group(2)}box"
        box_records.append(
            {
                "log_line": index + 1,
                "kind": kind,
                "measure": match.group(3),
                "source_line_locator": match.group(4),
                "preceding_shipout_tex_page": preceding,
                "following_shipout_tex_page": following,
                "pdf_page": physical,
                "text": portable_text(value),
            }
        )
        box_line_indices.append(index)
    if any(record["pdf_page"] is None for record in box_records):
        raise ReceiptError("one or more box warnings could not be mapped to a PDF page")

    warning_start = re.compile(r"^(?:LaTeX(?: Font)?|Package \S+) Warning:")
    warning_records: list[dict[str, object]] = []
    warning_categories: Counter[str] = Counter()
    for index, value in enumerate(lines):
        if not warning_start.match(value):
            continue
        block = warning_block(lines, index)
        joined = "\n".join(block)
        category = classify_warning(joined)
        warning_categories[category] += 1
        preceding, following, physical = neighboring_shipouts(
            line_starts[index], shipouts
        )
        warning_records.append(
            {
                "log_line": index + 1,
                "category": category,
                "preceding_shipout_tex_page": preceding,
                "following_shipout_tex_page": following,
                "pdf_page": physical,
                "text_block": block,
            }
        )

    line_bangs = [
        {"log_line": index + 1, "text": portable_text(value)}
        for index, value in enumerate(lines)
        if value.startswith("! ")
    ]
    benign_bang_lines: set[int] = set()
    for record in line_bangs:
        zero_index = int(record["log_line"]) - 1
        if (
            re.match(r"^! \\(?:OML|OMS|OT1|TU|U)/", str(record["text"]))
            and any(0 < zero_index - box_index <= 12 for box_index in box_line_indices)
        ):
            benign_bang_lines.add(int(record["log_line"]))
    true_bangs = [
        record
        for record in line_bangs
        if int(record["log_line"]) not in benign_bang_lines
    ]

    fatal_pattern = re.compile(
        r"Fatal error occurred|Emergency stop|No pages of output|"
        r"TeX capacity exceeded|Runaway argument|File ended while scanning|"
        r"LaTeX Error:|Package \S+ Error:",
        re.IGNORECASE,
    )
    undefined_reference_pattern = re.compile(
        r"Reference .* undefined|undefined references?", re.IGNORECASE
    )
    undefined_citation_pattern = re.compile(
        r"Citation .* undefined|undefined citations?", re.IGNORECASE
    )
    missing_character_pattern = re.compile(
        r"Missing character:|There is no .* in font", re.IGNORECASE
    )
    invalid_character_pattern = re.compile(
        r"Invalid UTF-?8|Invalid character|Unicode character .* not set up",
        re.IGNORECASE,
    )
    rerun_pattern = re.compile(
        r"Rerun to get cross-references right|Label\(s\) may have changed|"
        r"Please (?:re)?run|rerun LaTeX|rerun BibTeX",
        re.IGNORECASE,
    )

    fatal = find_line_records(lines, fatal_pattern)
    undefined_references = find_line_records(lines, undefined_reference_pattern)
    undefined_citations = find_line_records(lines, undefined_citation_pattern)
    missing_characters = find_line_records(lines, missing_character_pattern)
    invalid_characters = find_line_records(lines, invalid_character_pattern)
    rerun_requests = find_line_records(lines, rerun_pattern)

    # Package-name/path/info occurrences are evidence, not rerun requests.
    rerunfilecheck = [
        {"log_line": index + 1, "text": portable_text(value)}
        for index, value in enumerate(lines)
        if "rerunfilecheck" in value
    ]
    rerun_requests = [
        record
        for record in rerun_requests
        if "rerunfilecheck" not in str(record["text"]).lower()
    ]

    output_pattern = re.compile(
        r"Output written on\s+(.*?)\s+\((\d+) pages?\)\.", re.DOTALL
    )
    output_matches = list(output_pattern.finditer(text))
    if len(output_matches) != 1:
        raise ReceiptError(
            f"expected one final Output written declaration, found {len(output_matches)}"
        )
    output_match = output_matches[0]
    declared_path_text = re.sub(r"\r?\n", "", output_match.group(1)).strip()
    declared_path = Path(declared_path_text).resolve()
    if declared_path != PDF.resolve():
        raise ReceiptError(
            "final log Output written path does not match PDF: "
            f"{declared_path} != {PDF.resolve()}"
        )
    declared_pages = int(output_match.group(2))
    if declared_pages != EXPECTED_PAGES:
        raise ReceiptError("final log Output written page count does not match PDF")

    blocking_records = {
        "true_tex_error_banners": true_bangs,
        "fatal_errors": fatal,
        "undefined_references": undefined_references,
        "undefined_citations": undefined_citations,
        "missing_characters": missing_characters,
        "invalid_characters": invalid_characters,
        "rerun_requests": rerun_requests,
    }
    blocking_counts = {
        "true_tex_error_banners": len(true_bangs),
        "fatal_errors": len(fatal),
        "undefined_reference_warnings": len(undefined_references),
        "undefined_citation_warnings": len(undefined_citations),
        "missing_character_warnings": len(missing_characters),
        "invalid_character_warnings": len(invalid_characters),
        "rerun_requests": len(rerun_requests),
    }
    if any(blocking_counts.values()):
        raise ReceiptError(f"blocking final-log diagnostic(s): {blocking_counts}")

    box_counts = Counter(str(record["kind"]) for record in box_records)
    warning_pages = sorted({int(record["pdf_page"]) for record in box_records})
    nonblocking_counts = {
        "overfull_hbox_warnings": box_counts["overfull_hbox"],
        "underfull_hbox_warnings": box_counts["underfull_hbox"],
        "overfull_vbox_warnings": box_counts["overfull_vbox"],
        "underfull_vbox_warnings": box_counts["underfull_vbox"],
        "all_box_warnings": len(box_records),
        "unique_mapped_box_warning_pdf_pages": len(warning_pages),
        "latex_or_package_warning_blocks": len(warning_records),
        **dict(sorted(warning_categories.items())),
        "line_start_bang_lines": len(line_bangs),
        "rerunfilecheck_text_occurrences": len(rerunfilecheck),
    }
    return {
        "blocking_condition_counts": blocking_counts,
        "blocking_condition_records": blocking_records,
        "nonblocking_counts": nonblocking_counts,
        "classification_notes": {
            "line_start_bang": {
                "records": line_bangs,
                "benign_box_context_log_lines": sorted(benign_bang_lines),
                "classification": "no_true_tex_error_banner",
                "reason": (
                    "Any line-start exclamation mark retained here occurs within "
                    "twelve log lines after a mapped box-warning header. All other "
                    "line-start exclamation marks are blocking."
                ),
            },
            "rerunfilecheck": {
                "records": rerunfilecheck,
                "classification": "stable_no_rerun_request",
                "reason": (
                    "Package path/version/info occurrences are separated from explicit "
                    "rerun-request patterns; the latter are required to be absent."
                ),
            },
            "page_mapping": {
                "shipout_record_count": len(shipouts),
                "first_shipout": shipouts[0],
                "last_shipout": shipouts[-1],
                "method": (
                    "Every bracketed TeX shipout marker was parsed from the complete "
                    "log, including whitespace-wrapped markers. Physical PDF pages are "
                    "their ordinal positions; each warning maps to the following shipout."
                ),
                "unmapped_box_warning_count": 0,
            },
        },
        "latex_and_package_warning_records": warning_records,
        "box_warning_records": box_records,
        "unique_mapped_box_warning_pdf_pages": warning_pages,
        "output_written": {
            "log_line": line_number(line_starts, output_match.start()),
            "declared_pdf": portable_text(str(declared_path)),
            "declared_pages": declared_pages,
        },
    }


def validate_fls() -> dict[str, Any]:
    lines = FLS.read_text(encoding="utf-8", errors="strict").splitlines()
    pwd_values = [value[4:] for value in lines if value.startswith("PWD ")]
    inputs = [value[6:] for value in lines if value.startswith("INPUT ")]
    outputs = [value[7:] for value in lines if value.startswith("OUTPUT ")]
    if len(pwd_values) != 1:
        raise ReceiptError("final FLS does not contain exactly one PWD record")
    pwd = Path(pwd_values[0]).resolve()

    def resolve_fls(value: str) -> Path:
        candidate = Path(value)
        return candidate.resolve() if candidate.is_absolute() else (pwd / candidate).resolve()

    input_paths = {resolve_fls(value) for value in inputs}
    output_paths = {resolve_fls(value) for value in outputs}
    expected_recorder_outputs = {
        LOG.resolve(),
        SIDECARS["aux"].resolve(),
        SIDECARS["out"].resolve(),
        SIDECARS["toc"].resolve(),
    }
    missing_outputs = sorted(
        str(path) for path in expected_recorder_outputs - output_paths
    )
    if missing_outputs:
        raise ReceiptError(
            "FLS is missing expected recorder output(s): "
            + ", ".join(missing_outputs)
        )
    if READER.resolve() not in input_paths:
        raise ReceiptError("FLS does not bind src/reader.tex as an input")
    if SIDECARS["bbl"].resolve() not in input_paths:
        raise ReceiptError("FLS does not bind the final BBL as an input")
    return {
        "pwd": relative(pwd),
        "input_record_count": len(inputs),
        "unique_input_count": len(input_paths),
        "output_record_count": len(outputs),
        "unique_output_count": len(output_paths),
        "reader_input_recorded": True,
        "bbl_input_recorded": True,
        "expected_recorder_outputs_recorded": True,
        "pdf_output_recorded_by_fls": PDF.resolve() in output_paths,
        "pdf_binding": (
            "MiKTeX XeLaTeX does not record the dvipdfmx-produced PDF as an "
            "FLS OUTPUT in this build. The PDF is independently bound by the "
            "final log's exact Output written path/page declaration, its "
            "byte count and SHA-256, and the stable build snapshot."
        ),
    }


def snapshot_build_files() -> dict[str, tuple[int, int]]:
    paths = [PDF, LOG, FLS, *SIDECARS.values()]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise ReceiptError("missing final build artifact(s): " + ", ".join(map(str, missing)))
    empty = [path for path in paths if path.stat().st_size <= 0]
    if empty:
        raise ReceiptError(
            "empty/incomplete final build artifact(s): " + ", ".join(map(str, empty))
        )
    return {
        relative(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in paths
    }


def make_build_receipt(
    static: dict[str, Any],
    mechanical: dict[str, Any],
    mechanical_bytes: bytes,
    diagnostics: dict[str, Any],
    fls_validation: dict[str, Any],
) -> dict[str, Any]:
    replay_check = static["replay_check"]
    pdf_record = file_record(PDF)
    header = PDF.read_bytes()[:8].decode("ascii", errors="strict")
    if not header.startswith("%PDF-"):
        raise ReceiptError("current PDF has no valid PDF header")
    pdf_record.update(
        {
            "pages": EXPECTED_PAGES,
            "page_size": "595.28 x 841.89 pts (A4)",
            "encrypted": "no",
            "tagged": "yes"
            if mechanical["accessibility"]["struct_tree_root"]
            else "no",
            "pdf_version": header.removeprefix("%PDF-").strip(),
        }
    )
    output_written = diagnostics.pop("output_written")
    return {
        "schema": "stacks-zh-hans-cn-r14-build-receipt/v1",
        "release_candidate": EXPECTED_RELEASE,
        "locale": "zh-Hans-CN",
        "scope": (
            "Completed 112-chapter cumulative reader: current manifest and source "
            "replay bindings, final PDF/log/FLS/sidecar identities, complete mechanical "
            "PDF audit, and final-log diagnostic classification. Visual QA is separate."
        ),
        "authority_commit": EXPECTED_AUTHORITY_COMMIT,
        "status": "PASS",
        "source_bindings": {
            "chapter_count": EXPECTED_CHAPTERS,
            "manifest": file_record(MANIFEST),
            "reader": file_record(READER),
            "source_replay": file_record(SOURCE_REPLAY),
            "source_replay_verification": {
                **file_record(SOURCE_REPLAY_VERIFICATION),
                "verified_input_bindings": replay_check["verified_input_bindings"],
                "verified_generated_outputs": replay_check["verified_generated_outputs"],
                "unique_reference_targets": replay_check["unique_reference_targets"],
                "unresolved_reference_targets": replay_check[
                    "unresolved_reference_targets"
                ],
                "ordered_input_binding_sha256": replay_check[
                    "ordered_input_binding_sha256"
                ],
                "ordered_output_binding_sha256": replay_check[
                    "ordered_output_binding_sha256"
                ],
                "passed": replay_check["passed"],
            },
        },
        "tool_bindings": {
            "compose": file_record(COMPOSE_SCRIPT),
            "build": file_record(BUILD_SCRIPT),
            "source_replay_verifier": file_record(SOURCE_REPLAY_VERIFIER),
            "receipt_refresher": file_record(Path(__file__).resolve()),
        },
        "build_bindings": {
            "pdf": pdf_record,
            "final_log": file_record(LOG),
            "final_fls": file_record(FLS),
            "sidecars": {
                extension: file_record(path)
                for extension, path in SIDECARS.items()
            },
            "mechanical_audit": bytes_record(MECHANICAL_OUT, mechanical_bytes),
            "fls_validation": fls_validation,
            "output_written_declaration": {
                **output_written,
                "cross_check": (
                    "Matches the 5,546-page current PDF byte identity and the complete "
                    "physical shipout sequence."
                ),
            },
        },
        "diagnostics": diagnostics,
        "build_stability": {
            "method": (
                "PDF, log, FLS, AUX, BBL, BLG, OUT, and TOC size/mtime snapshots "
                "were identical before and after full receipt generation."
            ),
            "stable": True,
        },
        "pass_basis": [
            "The current PDF contains exactly 5,546 unrotated A4 pages.",
            "The final log names the exact final PDF path and declares exactly 5,546 pages.",
            "The final log contains zero true TeX error, fatal, undefined-reference, undefined-citation, missing-character, invalid-character, or rerun-request diagnostics.",
            "Every remaining box and LaTeX/package warning is retained and physically page-mapped.",
            "The mechanical audit validates named destinations, link geometry, font embedding, page labels, content streams, and page-complete text extraction.",
            "The current source replay independently passes all 112 chapters with 16,047 unique reference targets and zero unresolved targets.",
            "The final recorder binds reader.tex, the final BBL, and every recorder-native XeLaTeX output (LOG, AUX, OUT, and TOC); the dvipdfmx-produced PDF is independently hash-, path-, page-, and stability-bound.",
        ],
        "passed": True,
    }


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_replace_pair(outputs: dict[Path, bytes]) -> None:
    temporary: dict[Path, Path] = {}
    originals = {
        target: target.read_bytes() if target.is_file() else None for target in outputs
    }
    replaced: list[Path] = []
    try:
        for target, data in outputs.items():
            temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            with temp.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            parsed = json.loads(temp.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                raise ReceiptError(f"temporary receipt is not a JSON object: {temp}")
            if temp.read_bytes() != data:
                raise ReceiptError(f"temporary receipt readback mismatch: {temp}")
            temporary[target] = temp

        # The build receipt binds the new mechanical receipt, so install mechanical first.
        for target in (MECHANICAL_OUT, BUILD_RECEIPT_OUT):
            os.replace(temporary[target], target)
            replaced.append(target)
        for target, data in outputs.items():
            if target.read_bytes() != data:
                raise ReceiptError(f"post-replacement readback mismatch: {target}")
    except Exception:
        for target in reversed(replaced):
            original = originals[target]
            if original is None:
                target.unlink(missing_ok=True)
                continue
            rollback = target.with_name(f".{target.name}.{os.getpid()}.rollback")
            rollback.write_bytes(original)
            os.replace(rollback, target)
        raise
    finally:
        for temp in temporary.values():
            temp.unlink(missing_ok=True)


def preflight_only() -> dict[str, object]:
    validate_static_inputs(shallow=True)
    if MECHANICAL_OUT.parent != QA or BUILD_RECEIPT_OUT.parent != QA:
        raise ReceiptError("receipt outputs escape the bounded QA directory")
    if MECHANICAL_OUT == BUILD_RECEIPT_OUT:
        raise ReceiptError("receipt outputs collide")
    return {
        "status": "PASS",
        "mode": "read_only_preflight",
        "root": str(ROOT),
        "expected_chapters": EXPECTED_CHAPTERS,
        "expected_pages": EXPECTED_PAGES,
        "outputs": [relative(MECHANICAL_OUT), relative(BUILD_RECEIPT_OUT)],
        "write_command": (
            "python qa/refresh_build_receipts_r14.py --write"
        ),
        "note": (
            "The active/incomplete build was not opened. Full PDF/log/FLS/sidecar "
            "validation and atomic replacement occur only with --write."
        ),
    }


def run_write() -> dict[str, object]:
    static = validate_static_inputs(shallow=False)
    before = snapshot_build_files()
    mechanical = make_mechanical_audit()
    diagnostics = parse_log()
    fls_validation = validate_fls()
    after = snapshot_build_files()
    if before != after:
        raise ReceiptError(
            "build artifacts changed while receipts were generated; nothing was written"
        )

    mechanical_bytes = json_bytes(mechanical)
    build_receipt = make_build_receipt(
        static, mechanical, mechanical_bytes, diagnostics, fls_validation
    )
    build_bytes = json_bytes(build_receipt)
    atomic_replace_pair(
        {MECHANICAL_OUT: mechanical_bytes, BUILD_RECEIPT_OUT: build_bytes}
    )
    return {
        "status": "PASS",
        "mode": "write",
        "pdf": file_record(PDF),
        "mechanical_receipt": file_record(MECHANICAL_OUT),
        "build_receipt": file_record(BUILD_RECEIPT_OUT),
        "pages": mechanical["pages"],
        "named_destinations": mechanical["named_destinations"],
        "links": mechanical["annotations"]["subtypes"].get("/Link", 0),
        "fonts": {
            "total": mechanical["fonts"]["total"],
            "embedded": mechanical["fonts"]["embedded"],
            "with_to_unicode": mechanical["fonts"]["with_to_unicode"],
        },
        "box_warnings": build_receipt["diagnostics"]["nonblocking_counts"][
            "all_box_warnings"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed R14 cumulative-PDF mechanical/build receipt regeneration. "
            "No receipt is replaced unless --write is explicitly supplied."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight-only",
        action="store_true",
        help="read-only configuration/schema preflight; does not open active build outputs",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="fully audit the completed build and atomically replace exactly two receipts",
    )
    args = parser.parse_args()
    try:
        result = preflight_only() if args.preflight_only else run_write()
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(error).__name__,
                    "error": portable_text(str(error)),
                    "receipts_replaced": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
