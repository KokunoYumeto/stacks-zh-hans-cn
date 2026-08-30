from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


QA = Path(__file__).resolve().parent
ROOT = QA.parent
CONFIG_PATH = QA / "R15_QA_CONFIG.json"


class GateError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def root_relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def file_record(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": root_relative(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GateError(f"expected a JSON object: {path}")
    return value


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write_many(outputs: dict[Path, bytes]) -> None:
    temporary: dict[Path, Path] = {}
    try:
        for path, payload in outputs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            temp = Path(raw)
            temporary[path] = temp
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        for path, temp in temporary.items():
            os.replace(temp, path)
    finally:
        for temp in temporary.values():
            if temp.exists():
                temp.unlink()


def resolve_root_path(value: object) -> Path:
    candidate = Path(str(value))
    return candidate.resolve() if candidate.is_absolute() else (ROOT / candidate).resolve()


def require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GateError(f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise GateError(f"{label} must be an array")
    return value


def assert_binding(binding: object, expected_path: Path, label: str) -> dict[str, Any]:
    record = require_object(binding, label)
    path = resolve_root_path(record.get("path"))
    if path != expected_path.resolve():
        raise GateError(f"{label} path drift: {path} != {expected_path.resolve()}")
    if not path.is_file():
        raise GateError(f"{label} is missing: {path}")
    if "bytes" in record and int(record["bytes"]) != path.stat().st_size:
        raise GateError(f"{label} byte-count drift")
    if "sha256" in record and str(record["sha256"]).upper() != sha256(path):
        raise GateError(f"{label} SHA-256 drift")
    return record


def load_config() -> dict[str, Any]:
    config = load_json(CONFIG_PATH)
    if config.get("schema") != "stacks-zh-hans-cn-r15-qa-config/v1":
        raise GateError("unexpected R15 QA config schema")
    if config.get("authority_commit") != "a04446e57ec1fbc252a871afcec7752fb2807b14":
        raise GateError("R15 QA config authority drift")
    expected = require_object(config.get("expected"), "config.expected")
    chapters = [int(value) for value in require_list(expected.get("chapter_numbers"), "expected.chapter_numbers")]
    if chapters != list(range(1, 117)):
        raise GateError("R15 QA config does not bind the exact ordered Chapter 1-116 sequence")
    if int(expected.get("chapter_count", -1)) != len(chapters):
        raise GateError("R15 QA config chapter count drift")
    if int(expected.get("page_count", -1)) != 5906:
        raise GateError("R15 QA config page count drift")
    return config


def validate_static_inputs(config: dict[str, Any], *, full_replay: bool) -> dict[str, Any]:
    expected = require_object(config["expected"], "config.expected")
    static = require_object(config.get("static_bindings"), "config.static_bindings")
    manifest_path = resolve_root_path(require_object(static["manifest"], "manifest")["path"])
    replay_path = resolve_root_path(require_object(static["source_replay"], "source_replay")["path"])
    assert_binding(static["manifest"], manifest_path, "configured manifest")
    assert_binding(static["source_replay"], replay_path, "configured source replay")
    reader_path = resolve_root_path(require_object(static["reader"], "reader")["path"])
    compose_path = resolve_root_path(require_object(static["compose_script"], "compose_script")["path"])
    build_path = resolve_root_path(require_object(static["build_script"], "build_script")["path"])
    launch_path = resolve_root_path(require_object(static["build_launch_receipt"], "build_launch_receipt")["path"])
    for path, label in (
        (reader_path, "reader"),
        (compose_path, "compose script"),
        (build_path, "build script"),
        (launch_path, "build launch receipt"),
    ):
        if not path.is_file():
            raise GateError(f"missing {label}: {path}")

    manifest = load_json(manifest_path)
    if manifest.get("schema") != "stacks-zh-hans-cn-cumulative/v1":
        raise GateError("unexpected cumulative manifest schema")
    authority = require_object(manifest.get("authority"), "manifest.authority")
    if authority.get("commit") != config["authority_commit"]:
        raise GateError("manifest authority commit drift")
    manifest_chapters = [
        int(require_object(record, f"manifest chapter {index}").get("chapter", -1))
        for index, record in enumerate(require_list(manifest.get("chapters"), "manifest.chapters"), start=1)
    ]
    if manifest_chapters != [int(value) for value in expected["chapter_numbers"]]:
        raise GateError("manifest chapter sequence is not exactly 1 through 116")

    replay = load_json(replay_path)
    if replay.get("schema") != "stacks-zh-hans-cn-source-replay/v1" or replay.get("passed") is not True:
        raise GateError("source replay is not a passing v1 receipt")
    if replay.get("authority_commit") != config["authority_commit"]:
        raise GateError("source replay authority commit drift")
    if int(replay.get("chapter_count", -1)) != int(expected["chapter_count"]):
        raise GateError("source replay chapter count drift")
    assert_binding(replay.get("manifest"), manifest_path, "source replay manifest")
    inputs = require_list(replay.get("verified_inputs"), "source replay verified_inputs")
    outputs = require_list(replay.get("generated_outputs"), "source replay generated_outputs")
    if len(inputs) != int(expected["verified_input_bindings"]):
        raise GateError("source replay input-binding count drift")
    if len(outputs) != int(expected["generated_outputs"]):
        raise GateError("source replay output-binding count drift")
    refs = require_object(replay.get("reference_resolution"), "source replay reference_resolution")
    if int(refs.get("unique_targets", -1)) != int(expected["unique_reference_targets"]):
        raise GateError("source replay unique-reference-target count drift")
    if require_list(refs.get("unresolved_targets"), "unresolved_targets"):
        raise GateError("source replay retains unresolved reference targets")

    ordered_inputs = hashlib.sha256()
    ordered_outputs = hashlib.sha256()
    if full_replay:
        for index, record in enumerate(inputs, start=1):
            item = require_object(record, f"source replay input {index}")
            path = resolve_root_path(item.get("path"))
            assert_binding(item, path, f"source replay input {index}")
            ordered_inputs.update(f"{index}\t{path}\t{item['sha256']}\n".encode("utf-8"))
        for index, record in enumerate(outputs, start=1):
            item = require_object(record, f"source replay output {index}")
            path = resolve_root_path(item.get("path"))
            assert_binding(item, path, f"source replay output {index}")
            ordered_outputs.update(f"{index}\t{path}\t{item['sha256']}\n".encode("utf-8"))

    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "replay": replay,
        "replay_path": replay_path,
        "reader_path": reader_path,
        "compose_path": compose_path,
        "build_path": build_path,
        "launch_path": launch_path,
        "ordered_input_binding_sha256": ordered_inputs.hexdigest().upper() if full_replay else None,
        "ordered_output_binding_sha256": ordered_outputs.hexdigest().upper() if full_replay else None,
    }


def build_paths(config: dict[str, Any]) -> dict[str, Path]:
    build = require_object(config.get("build"), "config.build")
    result = {
        "pdf": resolve_root_path(build["pdf"]),
        "log": resolve_root_path(build["log"]),
        "fls": resolve_root_path(build["fls"]),
        "receipt": resolve_root_path(build["terminal_receipt"]),
        "mechanical": resolve_root_path(build["mechanical_receipt"]),
    }
    for extension, value in require_object(build.get("sidecars"), "build.sidecars").items():
        result[str(extension)] = resolve_root_path(value)
    return result


def active_build_processes(config: dict[str, Any]) -> list[dict[str, object]]:
    if os.name != "nt":
        raise GateError("R15 build-process terminal gate currently requires Windows")
    job = str(require_object(config["build"], "config.build")["job_name"])
    root = str(ROOT.resolve())
    launch_binding = require_object(
        require_object(config["static_bindings"], "config.static_bindings").get(
            "build_launch_receipt"
        ),
        "build_launch_receipt",
    )
    launch = load_json(resolve_root_path(launch_binding["path"]))
    active_attempt = require_object(launch.get("active_attempt"), "build launch active_attempt")
    launcher_pid = int(active_attempt.get("launcher_pid", -1))
    if launcher_pid <= 0:
        raise GateError("build launch receipt has no valid launcher PID")
    script = rf"""
$ErrorActionPreference = 'Stop'
$self = $PID
$rootNeedle = {json.dumps(root)}
$jobNeedle = {json.dumps(job)}
$launcherPid = {launcher_pid}
$names = @('xelatex.exe','miktex-xetex.exe','bibtex.exe','miktex-bibtex.exe','pwsh.exe','powershell.exe')
$all = @(Get-CimInstance Win32_Process)
$tree = @{{}}
$tree[$launcherPid] = $true
$changed = $true
while ($changed) {{
  $changed = $false
  foreach ($process in $all) {{
    if (-not $tree.ContainsKey([int]$process.ProcessId) -and $tree.ContainsKey([int]$process.ParentProcessId)) {{
      $tree[[int]$process.ProcessId] = $true
      $changed = $true
    }}
  }}
}}
$rows = $all | Where-Object {{
  $_.ProcessId -ne $self -and
  (
    $tree.ContainsKey([int]$_.ProcessId) -or
    (
      $names -contains $_.Name.ToLowerInvariant() -and
      $_.CommandLine -and
      ($_.CommandLine.IndexOf($rootNeedle, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
       $_.CommandLine.IndexOf($jobNeedle, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    )
  )
}} | Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine
@($rows) | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        text=True,
        capture_output=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise GateError(f"build-process query failed: {completed.stderr.strip()}")
    raw = completed.stdout.strip() or "[]"
    value = json.loads(raw)
    rows = value if isinstance(value, list) else [value]
    sanitized = []
    for row in rows:
        if isinstance(row, dict):
            sanitized.append(
                {
                    "pid": int(row.get("ProcessId", -1)),
                    "parent_pid": int(row.get("ParentProcessId", -1)),
                    "name": str(row.get("Name", "")),
                    "creation_date": str(row.get("CreationDate", "")),
                }
            )
    return sanitized


def snapshot(paths: Iterable[Path]) -> dict[str, tuple[int, int, str]]:
    result: dict[str, tuple[int, int, str]] = {}
    for path in paths:
        if not path.is_file() or path.stat().st_size <= 0:
            raise GateError(f"missing or empty final build artifact: {path}")
        result[root_relative(path)] = (path.stat().st_size, path.stat().st_mtime_ns, sha256(path))
    return result


SHIPOUT_CANDIDATE = re.compile(r"\[(?P<head>\d+)(?:\r?\n(?P<tail>\d+))?[ \t\r\n]*\]")
BOX_RE = re.compile(r"^(?P<fill>Over|Under)full \\(?P<axis>[hv])box\b(?P<tail>.*)$")


def line_number(line_starts: list[int], offset: int) -> int:
    return bisect.bisect_right(line_starts, offset)


def box_diagnostic_lines(text: str) -> set[int]:
    result: set[int] = set()
    active = False
    for number, value in enumerate(text.splitlines(), start=1):
        if BOX_RE.match(value):
            active = True
        elif not value.strip():
            active = False
        if active:
            result.add(number)
    return result


def shipout_records(text: str, expected_pages: int, frontmatter_pages: int) -> list[dict[str, int]]:
    body_pages = expected_pages - frontmatter_pages
    expected_tex_pages = [*range(frontmatter_pages), *range(1, body_pages + 1)]
    line_starts: list[int] = []
    offset = 0
    for value in text.splitlines(keepends=True):
        line_starts.append(offset)
        offset += len(value)
    candidates = [
        {
            "tex_page": int(match.group("head") + (match.group("tail") or "")),
            "offset": match.start(),
            "log_line": line_number(line_starts, match.start()),
        }
        for match in SHIPOUT_CANDIDATE.finditer(text)
    ]
    earliest: list[int] = []
    cursor = 0
    for expected in expected_tex_pages:
        while cursor < len(candidates) and candidates[cursor]["tex_page"] != expected:
            cursor += 1
        if cursor == len(candidates):
            raise GateError(f"incomplete forward shipout replay at TeX page {expected}")
        earliest.append(cursor)
        cursor += 1
    latest = [-1] * expected_pages
    cursor = len(candidates) - 1
    for expected_index in range(expected_pages - 1, -1, -1):
        expected = expected_tex_pages[expected_index]
        while cursor >= 0 and candidates[cursor]["tex_page"] != expected:
            cursor -= 1
        if cursor < 0:
            raise GateError(f"incomplete backward shipout replay at TeX page {expected}")
        latest[expected_index] = cursor
        cursor -= 1
    if earliest != latest:
        raise GateError("ambiguous ordered shipout sequence in final log")
    selected = set(earliest)
    diagnostic_lines = box_diagnostic_lines(text)
    unexplained = [
        candidates[index]
        for index in range(len(candidates))
        if index not in selected and candidates[index]["log_line"] not in diagnostic_lines
    ]
    if unexplained:
        raise GateError(
            f"unexplained bracketed numeric token at log line {unexplained[0]['log_line']}"
        )
    return [
        {"physical_page": page, **candidates[index]}
        for page, index in enumerate(earliest, start=1)
    ]


def parse_final_log(config: dict[str, Any], path: Path, pdf_path: Path) -> dict[str, Any]:
    expected = require_object(config["expected"], "config.expected")
    page_count = int(expected["page_count"])
    frontmatter = int(expected["frontmatter_pages"])
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    line_starts: list[int] = []
    offset = 0
    for value in text.splitlines(keepends=True):
        line_starts.append(offset)
        offset += len(value)

    blocking_patterns = {
        "true_tex_errors": re.compile(
            r"(?m)^!(?: LaTeX Error:| Package .+ Error:| Emergency stop\.| Undefined control sequence\.| File ended while scanning| TeX capacity exceeded| Missing \\begin\{document\})"
        ),
        "fatal_errors": re.compile(
            r"(?im)(?:Fatal error occurred|Emergency stop|No pages of output|Runaway argument\?|TeX capacity exceeded)"
        ),
        "undefined_references": re.compile(
            r"(?im)(?:LaTeX Warning: Reference .+ undefined|There were undefined references|undefined references? on input line)"
        ),
        "undefined_citations": re.compile(
            r"(?im)(?:LaTeX Warning: Citation .+ undefined|There were undefined citations|undefined citations? on input line)"
        ),
        "missing_glyphs": re.compile(
            r"(?im)(?:Missing character:|missing glyph|does not contain requested Script|Invalid UTF-?8|Unicode character .+ not set up)"
        ),
        "rerun_requests": re.compile(
            r"(?im)(?:Rerun to get cross-references right|Label\(s\) may have changed|Please \(re\)run BibTeX|rerunfilecheck Warning: File .+ has changed)"
        ),
    }
    blocking_records: dict[str, list[dict[str, object]]] = {}
    for label, pattern in blocking_patterns.items():
        records = []
        for match in pattern.finditer(text):
            records.append(
                {
                    "log_line": line_number(line_starts, match.start()),
                    "text": match.group(0).replace("\r", " ").replace("\n", " ")[:500],
                }
            )
        blocking_records[label] = records
    if any(blocking_records.values()):
        counts = {key: len(value) for key, value in blocking_records.items()}
        raise GateError(f"final log contains blocking diagnostics: {counts}")

    output_pattern = re.compile(
        r"Output written on\s+(?P<path>.+?)\s+\((?P<pages>\d+)\s+pages?"
        r"(?:,\s*(?P<bytes>\d+)\s+bytes)?\)\.",
        re.IGNORECASE | re.DOTALL,
    )
    outputs = list(output_pattern.finditer(text))
    if len(outputs) != 1:
        raise GateError(f"final log must contain exactly one Output written declaration, found {len(outputs)}")
    output = outputs[0]
    declared_pages = int(output.group("pages"))
    declared_bytes = int(output.group("bytes")) if output.group("bytes") else None
    if declared_pages != page_count:
        raise GateError("final log Output written declaration does not match the current PDF")
    if declared_bytes is not None and declared_bytes != pdf_path.stat().st_size:
        raise GateError("final log Output written byte count does not match the current PDF")

    shipouts = shipout_records(text, page_count, frontmatter)
    offsets = [int(record["offset"]) for record in shipouts]
    box_records: list[dict[str, object]] = []
    for index, line in enumerate(lines, start=1):
        match = BOX_RE.match(line)
        if not match:
            continue
        start = line_starts[index - 1]
        insertion = bisect.bisect_right(offsets, start)
        preceding = shipouts[insertion - 1] if insertion else None
        following = shipouts[insertion] if insertion < len(shipouts) else None
        mapped_page = (
            int(following["physical_page"])
            if following is not None
            else int(preceding["physical_page"]) if preceding is not None else None
        )
        if mapped_page is None:
            raise GateError(f"box warning at log line {index} could not be page-mapped")
        box_records.append(
            {
                "log_line": index,
                "kind": f"{match.group('fill').lower()}_{match.group('axis')}box",
                "text": line.strip(),
                "preceding_shipout_tex_page": int(preceding["tex_page"]) if preceding else None,
                "following_shipout_tex_page": int(following["tex_page"]) if following else None,
                "pdf_page": mapped_page,
                "mapping_method": "following_unique_ordered_shipout_or_terminal_previous",
            }
        )
    box_kinds = Counter(str(record["kind"]) for record in box_records)
    return {
        "final_pass_convergence": {
            "output_written_declaration_count": 1,
            "declared_pages": declared_pages,
            "declared_bytes": declared_bytes,
            "byte_count_source": "final_log" if declared_bytes is not None else "stable_file_snapshot_and_sha256",
            "rerun_requests": 0,
            "undefined_references": 0,
            "undefined_citations": 0,
            "converged": True,
        },
        "blocking_condition_counts": {key: 0 for key in blocking_patterns},
        "blocking_condition_records": blocking_records,
        "shipout_replay": {
            "count": len(shipouts),
            "first": shipouts[0],
            "last": shipouts[-1],
            "unique_forward_backward_embedding": True,
        },
        "box_warning_counts": {
            **dict(sorted(box_kinds.items())),
            "all": len(box_records),
            "unique_pdf_pages": len({int(record["pdf_page"]) for record in box_records}),
        },
        "box_warning_records": box_records,
        "unique_box_warning_pdf_pages": sorted({int(record["pdf_page"]) for record in box_records}),
    }


def dereference(value: object) -> object:
    try:
        from pypdf.generic import IndirectObject
    except ImportError as error:
        raise GateError("pypdf is required for R15 PDF QA") from error
    return value.get_object() if isinstance(value, IndirectObject) else value


def indirect_key(value: object) -> str | None:
    try:
        from pypdf.generic import IndirectObject
    except ImportError as error:
        raise GateError("pypdf is required for R15 PDF QA") from error
    return f"{value.idnum}:{value.generation}" if isinstance(value, IndirectObject) else None


def rectangle_values(value: object) -> list[float] | None:
    try:
        from pypdf.generic import ArrayObject
    except ImportError as error:
        raise GateError("pypdf is required for R15 PDF QA") from error
    value = dereference(value)
    if not isinstance(value, ArrayObject) or len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def audit_pdf(config: dict[str, Any], pdf_path: Path) -> dict[str, Any]:
    try:
        from pypdf import PdfReader
        from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject
    except ImportError as error:
        raise GateError("pypdf is required for R15 PDF QA") from error

    expected = require_object(config["expected"], "config.expected")
    expected_pages = int(expected["page_count"])
    a4 = tuple(float(value) for value in expected["a4_points"])
    reader = PdfReader(str(pdf_path), strict=False)
    if reader.is_encrypted:
        raise GateError("release PDF is encrypted")
    if len(reader.pages) != expected_pages:
        raise GateError(f"PDF page-count drift: {len(reader.pages)} != {expected_pages}")

    page_ref_to_number: dict[str, int] = {}
    for page_number, page in enumerate(reader.pages, start=1):
        reference = getattr(page, "indirect_reference", None)
        key = indirect_key(reference)
        if key:
            page_ref_to_number[key] = page_number

    named = reader.named_destinations
    invalid_named: list[dict[str, object]] = []
    for name, destination in named.items():
        try:
            page_number = reader.get_destination_page_number(destination) + 1
        except Exception as error:
            invalid_named.append({"name": name, "error": repr(error)})
            continue
        if not 1 <= page_number <= expected_pages:
            invalid_named.append({"name": name, "page": page_number})

    page_sizes: Counter[tuple[float, float]] = Counter()
    rotations: Counter[int] = Counter()
    annotation_subtypes: Counter[str] = Counter()
    content_stream_bytes: list[int] = []
    text_chars: list[int] = []
    cjk_chars: list[int] = []
    extraction_errors: list[dict[str, object]] = []
    replacement_characters = 0
    literal_double_questions = 0
    font_records: dict[str, dict[str, Any]] = {}
    malformed_rectangles: list[dict[str, object]] = []
    zero_rectangles: list[dict[str, object]] = []
    out_of_page_rectangles: list[dict[str, object]] = []
    link_counts: Counter[str] = Counter()
    unresolved_links: list[dict[str, object]] = []

    def destination_resolves(value: object) -> bool:
        raw = value
        value = dereference(value)
        if isinstance(value, str):
            name = value[1:] if value.startswith("/") and value[1:] in named else value
            return name in named
        if isinstance(value, ArrayObject) and value:
            first_raw = value[0]
            key = indirect_key(first_raw)
            if key:
                return key in page_ref_to_number
            first = dereference(first_raw)
            if isinstance(first, int):
                return 0 <= first < expected_pages
            if isinstance(first, DictionaryObject):
                reference = getattr(first, "indirect_reference", None)
                key = indirect_key(reference)
                return bool(key and key in page_ref_to_number)
        if isinstance(value, DictionaryObject):
            page = value.get("/Page")
            if page is not None:
                return destination_resolves(ArrayObject([page]))
        key = indirect_key(raw)
        return bool(key and key in page_ref_to_number)

    for page_number, page in enumerate(reader.pages, start=1):
        media = page.mediabox
        width = float(media.right) - float(media.left)
        height = float(media.top) - float(media.bottom)
        page_sizes[(round(width, 2), round(height, 2))] += 1
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
        text_chars.append(len(text))
        cjk_chars.append(sum("\u4e00" <= char <= "\u9fff" for char in text))
        replacement_characters += text.count("\ufffd")
        literal_double_questions += text.count("??")

        resources = dereference(page.get("/Resources", {}))
        fonts = dereference(resources.get("/Font", {})) if isinstance(resources, DictionaryObject) else {}
        if isinstance(fonts, DictionaryObject):
            for resource_name, font_ref in fonts.items():
                key = indirect_key(font_ref) or f"direct:{id(font_ref)}"
                font = dereference(font_ref)
                descriptor = dereference(font.get("/FontDescriptor", {})) if isinstance(font, DictionaryObject) else {}
                descendants = dereference(font.get("/DescendantFonts", [])) if isinstance(font, DictionaryObject) else []
                if isinstance(descendants, ArrayObject) and descendants:
                    descendant = dereference(descendants[0])
                    if isinstance(descendant, DictionaryObject):
                        child_descriptor = dereference(descendant.get("/FontDescriptor", {}))
                        if isinstance(child_descriptor, DictionaryObject):
                            descriptor = child_descriptor
                embedded = bool(
                    isinstance(descriptor, DictionaryObject)
                    and any(name in descriptor for name in ("/FontFile", "/FontFile2", "/FontFile3"))
                )
                subtype = str(font.get("/Subtype", "")) if isinstance(font, DictionaryObject) else ""
                record = font_records.setdefault(
                    key,
                    {
                        "resource_names": set(),
                        "base_font": str(font.get("/BaseFont", "")) if isinstance(font, DictionaryObject) else "",
                        "subtype": subtype,
                        "embedded": embedded,
                        "to_unicode": bool(isinstance(font, DictionaryObject) and font.get("/ToUnicode")),
                        "pages": set(),
                    },
                )
                record["resource_names"].add(str(resource_name))
                record["pages"].add(page_number)

        annots = dereference(page.get("/Annots", []))
        if isinstance(annots, ArrayObject):
            for annotation_ref in annots:
                annotation = dereference(annotation_ref)
                if not isinstance(annotation, DictionaryObject):
                    continue
                subtype = str(annotation.get("/Subtype", ""))
                annotation_subtypes[subtype] += 1
                rect = rectangle_values(annotation.get("/Rect"))
                if rect is None:
                    malformed_rectangles.append({"page": page_number, "subtype": subtype})
                else:
                    x0, y0, x1, y1 = rect
                    if x1 <= x0 or y1 <= y0:
                        zero_rectangles.append({"page": page_number, "rect": rect})
                    epsilon = 0.01
                    if (
                        x0 < float(media.left) - epsilon
                        or y0 < float(media.bottom) - epsilon
                        or x1 > float(media.right) + epsilon
                        or y1 > float(media.top) + epsilon
                    ):
                        out_of_page_rectangles.append({"page": page_number, "rect": rect})
                if subtype != "/Link":
                    continue
                if annotation.get("/Dest") is not None:
                    link_counts["internal"] += 1
                    if destination_resolves(annotation.get("/Dest")):
                        link_counts["resolved"] += 1
                    else:
                        unresolved_links.append({"page": page_number, "kind": "Dest"})
                    continue
                action = dereference(annotation.get("/A", {}))
                action_type = str(action.get("/S", "")) if isinstance(action, DictionaryObject) else ""
                if action_type == "/GoTo":
                    link_counts["internal"] += 1
                    if destination_resolves(action.get("/D")):
                        link_counts["resolved"] += 1
                    else:
                        unresolved_links.append({"page": page_number, "kind": "GoTo"})
                elif action_type == "/URI" and str(action.get("/URI", "")):
                    link_counts["external_uri"] += 1
                else:
                    unresolved_links.append({"page": page_number, "kind": action_type or "missing_action"})

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
    page_labels = reader.page_labels
    root_object = dereference(reader.trailer["/Root"])
    a4_only = page_sizes == Counter({(round(a4[0], 2), round(a4[1], 2)): expected_pages})
    all_unrotated = rotations == Counter({0: expected_pages})
    all_fonts_embedded = bool(serializable_fonts) and all(record["embedded"] for record in serializable_fonts)
    type0_without_unicode = [record for record in serializable_fonts if record["subtype"] == "/Type0" and not record["to_unicode"]]
    all_annotations_are_links = sum(annotation_subtypes.values()) > 0 and set(annotation_subtypes) == {"/Link"}
    passed = bool(
        a4_only
        and all_unrotated
        and not invalid_named
        and all_annotations_are_links
        and not malformed_rectangles
        and not zero_rectangles
        and not out_of_page_rectangles
        and not unresolved_links
        and all_fonts_embedded
        and not type0_without_unicode
        and not extraction_errors
        and all(value > 0 for value in text_chars)
        and all(value > 0 for value in content_stream_bytes)
        and replacement_characters == 0
        and sum(cjk_chars) > 0
        and isinstance(page_labels, list)
        and len(page_labels) == expected_pages
    )
    result = {
        "schema": "stacks-zh-hans-cn-r15-pdf-mechanical/v1",
        "pdf": file_record(pdf_path),
        "pages": len(reader.pages),
        "expected_pages": expected_pages,
        "page_sizes_points": [
            {"width": width, "height": height, "count": count}
            for (width, height), count in sorted(page_sizes.items())
        ],
        "rotations": {str(key): value for key, value in sorted(rotations.items())},
        "page_labels": page_labels,
        "metadata": {str(key): str(value) for key, value in (reader.metadata or {}).items()},
        "encrypted": reader.is_encrypted,
        "named_destinations": {
            "total": len(named),
            "invalid": invalid_named,
        },
        "annotations": {
            "total": sum(annotation_subtypes.values()),
            "subtypes": dict(annotation_subtypes),
            "malformed_rectangles": malformed_rectangles,
            "zero_area_rectangles": zero_rectangles,
            "out_of_page_rectangles": out_of_page_rectangles,
        },
        "link_targets": {
            "internal": int(link_counts["internal"]),
            "external_uri": int(link_counts["external_uri"]),
            "resolved_internal": int(link_counts["resolved"]),
            "unresolved": unresolved_links,
        },
        "fonts": {
            "total": len(serializable_fonts),
            "embedded": sum(bool(record["embedded"]) for record in serializable_fonts),
            "with_to_unicode": sum(bool(record["to_unicode"]) for record in serializable_fonts),
            "type0_without_to_unicode": type0_without_unicode,
            "records": serializable_fonts,
        },
        "accessibility": {
            "struct_tree_root": bool(isinstance(root_object, DictionaryObject) and root_object.get("/StructTreeRoot")),
            "mark_info": bool(isinstance(root_object, DictionaryObject) and root_object.get("/MarkInfo")),
        },
        "text_extraction": {
            "characters": sum(text_chars),
            "cjk_unified_ideographs": sum(cjk_chars),
            "replacement_characters": replacement_characters,
            "literal_double_question_pairs": literal_double_questions,
            "errors": extraction_errors,
            "characters_by_page": text_chars,
            "cjk_by_page": cjk_chars,
        },
        "content_stream_bytes": content_stream_bytes,
        "validation": {
            "a4_only": a4_only,
            "all_pages_unrotated": all_unrotated,
            "all_named_destinations_resolve": not invalid_named,
            "all_annotations_are_links": all_annotations_are_links,
            "all_internal_link_targets_resolve": not unresolved_links,
            "all_fonts_embedded": all_fonts_embedded,
            "all_type0_fonts_have_to_unicode": not type0_without_unicode,
            "all_pages_have_extractable_text": all(value > 0 for value in text_chars),
            "all_pages_have_content_stream_bytes": all(value > 0 for value in content_stream_bytes),
        },
        "passed": passed,
    }
    if not passed:
        raise GateError("mechanical PDF audit did not pass")
    return result


def validate_fls(paths: dict[str, Path], static: dict[str, Any]) -> dict[str, Any]:
    lines = paths["fls"].read_text(encoding="utf-8", errors="strict").splitlines()
    pwd_values = [value[4:] for value in lines if value.startswith("PWD ")]
    inputs = [value[6:] for value in lines if value.startswith("INPUT ")]
    outputs = [value[7:] for value in lines if value.startswith("OUTPUT ")]
    if len(pwd_values) != 1:
        raise GateError("final FLS must contain exactly one PWD record")
    pwd = Path(pwd_values[0]).resolve()

    def resolve(value: str) -> Path:
        candidate = Path(value)
        return candidate.resolve() if candidate.is_absolute() else (pwd / candidate).resolve()

    input_paths = {resolve(value) for value in inputs}
    output_paths = {resolve(value) for value in outputs}
    if static["reader_path"].resolve() not in input_paths:
        raise GateError("final FLS does not bind src/reader.tex")
    if paths["bbl"].resolve() not in input_paths:
        raise GateError("final FLS does not bind the final BBL")
    expected_outputs = {paths[name].resolve() for name in ("log", "aux", "out", "toc")}
    missing_outputs = expected_outputs - output_paths
    if missing_outputs:
        raise GateError(f"final FLS misses recorder outputs: {sorted(map(str, missing_outputs))}")
    generated_tex = []
    generated_bib = []
    for record in static["replay"]["generated_outputs"]:
        path = resolve_root_path(record["path"])
        if path.suffix.lower() == ".tex":
            generated_tex.append(path)
        elif path.suffix.lower() == ".bib":
            generated_bib.append(path)
    missing_generated = [path for path in generated_tex if path.resolve() not in input_paths]
    if missing_generated:
        raise GateError(
            f"final FLS does not bind {len(missing_generated)} generated TeX inputs; first={missing_generated[0]}"
        )
    blg_text = paths["blg"].read_text(encoding="utf-8", errors="replace")
    bib_database_names = {
        match.group("name").strip().replace("\\", "/").rsplit("/", 1)[-1].lower()
        for match in re.finditer(r"(?im)^Database file #\d+:\s*(?P<name>.+?)\s*$", blg_text)
    }
    missing_bib = [path for path in generated_bib if path.name.lower() not in bib_database_names]
    if missing_bib:
        raise GateError(
            f"BibTeX BLG does not bind {len(missing_bib)} generated bibliography inputs; first={missing_bib[0]}"
        )
    return {
        "pwd": root_relative(pwd),
        "input_record_count": len(inputs),
        "unique_input_count": len(input_paths),
        "output_record_count": len(outputs),
        "unique_output_count": len(output_paths),
        "reader_input_recorded": True,
        "bbl_input_recorded": True,
        "generated_tex_inputs_expected": len(generated_tex),
        "generated_tex_inputs_recorded_by_fls": len(generated_tex),
        "generated_bib_inputs_expected": len(generated_bib),
        "generated_bib_inputs_recorded_by_blg": len(generated_bib),
        "bibtex_database_names": sorted(bib_database_names),
        "expected_recorder_outputs_recorded": True,
        "pdf_output_recorded_by_fls": paths["pdf"].resolve() in output_paths,
        "pdf_binding_note": "The PDF is independently bound by the final log declaration, mechanical audit, SHA-256, and stable build snapshot even if the XeLaTeX recorder omits the dvipdfmx PDF output.",
    }


def validate_bound_receipt(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    paths = build_paths(config)
    receipt = load_json(paths["receipt"])
    mechanical = load_json(paths["mechanical"])
    if receipt.get("schema") != "stacks-zh-hans-cn-r15-build-receipt/v1" or receipt.get("passed") is not True:
        raise GateError("R15 build receipt is absent or not passing")
    if mechanical.get("schema") != "stacks-zh-hans-cn-r15-pdf-mechanical/v1" or mechanical.get("passed") is not True:
        raise GateError("R15 mechanical receipt is absent or not passing")
    static = require_object(config.get("static_bindings"), "config.static_bindings")
    assert_binding(
        receipt["source_bindings"]["manifest"],
        resolve_root_path(require_object(static["manifest"], "manifest")["path"]),
        "bound cumulative manifest",
    )
    assert_binding(
        receipt["source_bindings"]["source_replay"],
        resolve_root_path(require_object(static["source_replay"], "source_replay")["path"]),
        "bound source replay",
    )
    assert_binding(receipt["tool_bindings"]["qa_pipeline"], Path(__file__).resolve(), "bound QA pipeline")
    assert_binding(receipt["tool_bindings"]["qa_config"], CONFIG_PATH, "bound QA config")
    assert_binding(receipt["build_bindings"]["pdf"], paths["pdf"], "bound PDF")
    assert_binding(receipt["build_bindings"]["final_log"], paths["log"], "bound final log")
    assert_binding(receipt["build_bindings"]["final_fls"], paths["fls"], "bound final FLS")
    assert_binding(receipt["build_bindings"]["mechanical_audit"], paths["mechanical"], "bound mechanical receipt")
    if mechanical["pdf"]["sha256"] != receipt["build_bindings"]["pdf"]["sha256"]:
        raise GateError("mechanical/build PDF binding mismatch")
    return receipt, mechanical, paths


def command_preflight(args: argparse.Namespace) -> int:
    config = load_config()
    static = validate_static_inputs(config, full_replay=not args.shallow)
    active = active_build_processes(config)
    print(
        json.dumps(
            {
                "schema": "stacks-zh-hans-cn-r15-qa-preflight/v1",
                "static_inputs_valid": True,
                "full_source_binding_replay": not args.shallow,
                "manifest": file_record(static["manifest_path"]),
                "source_replay": file_record(static["replay_path"]),
                "active_build_processes": active,
                "post_build_gates_ready": not active,
                "writes_performed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_bind_build(_: argparse.Namespace) -> int:
    config = load_config()
    static = validate_static_inputs(config, full_replay=True)
    active = active_build_processes(config)
    if active:
        raise GateError(f"build is still active; refusing to bind: {active}")
    paths = build_paths(config)
    artifact_names = ("pdf", "log", "fls", "aux", "bbl", "blg", "out", "toc")
    artifacts = [paths[name] for name in artifact_names]
    before = snapshot(artifacts)
    delay = int(require_object(config["build"], "config.build").get("stability_seconds", 2))
    time.sleep(delay)
    middle = snapshot(artifacts)
    if before != middle:
        raise GateError("build artifacts changed during the terminal stability interval")
    diagnostics = parse_final_log(config, paths["log"], paths["pdf"])
    mechanical = audit_pdf(config, paths["pdf"])
    fls = validate_fls(paths, static)
    after = snapshot(artifacts)
    if middle != after:
        raise GateError("build artifacts changed while post-build receipts were being prepared")
    if active_build_processes(config):
        raise GateError("a build process reappeared while post-build receipts were being prepared")

    mechanical_payload = json_bytes(mechanical)
    receipt = {
        "schema": "stacks-zh-hans-cn-r15-build-receipt/v1",
        "release_candidate": config["release_candidate"],
        "locale": config["locale"],
        "scope": config["scope"],
        "authority_commit": config["authority_commit"],
        "status": "PASS",
        "source_bindings": {
            "chapter_count": config["expected"]["chapter_count"],
            "manifest": file_record(static["manifest_path"]),
            "source_replay": file_record(static["replay_path"]),
            "verified_input_bindings": len(static["replay"]["verified_inputs"]),
            "verified_generated_outputs": len(static["replay"]["generated_outputs"]),
            "unique_reference_targets": static["replay"]["reference_resolution"]["unique_targets"],
            "unresolved_reference_targets": 0,
            "ordered_input_binding_sha256": static["ordered_input_binding_sha256"],
            "ordered_output_binding_sha256": static["ordered_output_binding_sha256"],
        },
        "tool_bindings": {
            "compose": file_record(static["compose_path"]),
            "build": file_record(static["build_path"]),
            "qa_pipeline": file_record(Path(__file__).resolve()),
            "qa_config": file_record(CONFIG_PATH),
        },
        "build_bindings": {
            "pdf": {**file_record(paths["pdf"]), "pages": config["expected"]["page_count"]},
            "final_log": file_record(paths["log"]),
            "final_fls": file_record(paths["fls"]),
            "sidecars": {name: file_record(paths[name]) for name in ("aux", "bbl", "blg", "out", "toc")},
            "mechanical_audit": {
                "path": root_relative(paths["mechanical"]),
                "bytes": len(mechanical_payload),
                "sha256": sha256_bytes(mechanical_payload),
            },
            "fls_validation": fls,
        },
        "diagnostics": diagnostics,
        "build_terminal_gate": {
            "active_build_processes_before": [],
            "active_build_processes_after": [],
            "stable_snapshot_interval_seconds": delay,
            "artifacts_stable": True,
            "terminal": True,
        },
        "passed": True,
    }
    receipt_payload = json_bytes(receipt)
    atomic_write_many({paths["mechanical"]: mechanical_payload, paths["receipt"]: receipt_payload})
    print(
        json.dumps(
            {
                "status": "PASS",
                "build_receipt": file_record(paths["receipt"]),
                "mechanical_receipt": file_record(paths["mechanical"]),
                "pdf": file_record(paths["pdf"]),
                "box_warning_pages": len(diagnostics["unique_box_warning_pdf_pages"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


CHAPTER_DESTINATION_RE = re.compile(r"chapter\.(\d+)")
ROMAN_RE = re.compile(r"[ivxlcdm]+")


def chapter_ranges(pdf_path: Path, chapters: list[int]) -> tuple[dict[str, dict[str, int]], int]:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise GateError("pypdf is required for R15 visual planning") from error
    reader = PdfReader(str(pdf_path), strict=False)
    starts: dict[int, int] = {}
    for name, destination in reader.named_destinations.items():
        match = CHAPTER_DESTINATION_RE.fullmatch(name)
        if not match:
            continue
        chapter = int(match.group(1))
        physical = reader.get_destination_page_number(destination) + 1
        if chapter in starts:
            raise GateError(f"duplicate chapter destination: {chapter}")
        starts[chapter] = physical
    if set(starts) != set(chapters):
        raise GateError(
            f"chapter destinations differ from manifest: missing={sorted(set(chapters)-set(starts))}, extra={sorted(set(starts)-set(chapters))}"
        )
    ordered = sorted(starts.items(), key=lambda item: item[1])
    if [chapter for chapter, _ in ordered] != chapters:
        raise GateError("chapter destination order differs from manifest")
    ranges: dict[str, dict[str, int]] = {}
    for index, (chapter, start) in enumerate(ordered):
        end = ordered[index + 1][1] - 1 if index + 1 < len(ordered) else len(reader.pages)
        if not 1 <= start <= end <= len(reader.pages):
            raise GateError(f"invalid Chapter {chapter} physical range: {start}-{end}")
        ranges[str(chapter)] = {"start": start, "end": end}
    return ranges, ordered[0][1]


def visual_paths(pdf_sha256: str) -> dict[str, Path]:
    stem = pdf_sha256[:8]
    visual = QA / "visual"
    return {
        "full_dir": visual / f"r15-render-{stem}-100dpi",
        "full_stderr": visual / f"R15_RENDER_{stem}_RETRY1_STDERR.log",
        "full_manifest": visual / f"R15_RENDER_MANIFEST_{stem}.csv",
        "full_summary": visual / f"R15_RENDER_SUMMARY_{stem}.json",
        "contact_dir": visual / f"r15-{stem}-contact-sheets",
        "contact_stderr": visual / f"R15_CONTACT_{stem}.stderr.txt",
        "contact_manifest": visual / f"R15_CONTACT_SHEETS_{stem}.csv",
        "contact_summary": visual / f"R15_CONTACT_SUMMARY_{stem}.json",
        "targeted_dir": visual / f"r15-{stem}-200dpi",
        "targeted_stderr": visual / f"R15_TARGETED_{stem}.stderr.txt",
        "targeted_manifest": visual / f"R15_TARGETED_MANIFEST_{stem}.csv",
        "targeted_summary": visual / f"R15_TARGETED_SUMMARY_{stem}.json",
    }


def command_plan_visual(_: argparse.Namespace) -> int:
    config = load_config()
    static = validate_static_inputs(config, full_replay=False)
    receipt, mechanical, paths = validate_bound_receipt(config)
    chapters = [int(value) for value in config["expected"]["chapter_numbers"]]
    ranges, first_chapter = chapter_ranges(paths["pdf"], chapters)
    new_chapters = [int(value) for value in config["expected"]["new_or_repaired_chapters"]]
    new_pages = sorted(
        page
        for chapter in new_chapters
        for page in range(ranges[str(chapter)]["start"], ranges[str(chapter)]["end"] + 1)
    )
    warning_pages = [int(value) for value in receipt["diagnostics"]["unique_box_warning_pdf_pages"]]
    page_count = int(config["expected"]["page_count"])
    front_pages = list(range(1, first_chapter))
    fixed = sorted(
        {
            1,
            front_pages[0],
            front_pages[(len(front_pages) - 1) // 2],
            front_pages[len(front_pages) // 2],
            front_pages[-1],
            first_chapter,
            page_count,
        }
    )
    selected = sorted(set(new_pages + warning_pages + fixed))
    plan_path = resolve_root_path(config["visual"]["plan"])
    dynamic = visual_paths(receipt["build_bindings"]["pdf"]["sha256"])
    plan = {
        "schema": "stacks-zh-hans-cn-r15-visual-plan/v1",
        "release_candidate": config["release_candidate"],
        "pdf": receipt["build_bindings"]["pdf"],
        "page_count": page_count,
        "manifest": file_record(static["manifest_path"]),
        "mechanical_receipt": file_record(paths["mechanical"]),
        "build_receipt": file_record(paths["receipt"]),
        "chapter_range_basis": "numeric PDF named destinations",
        "chapter_ranges": ranges,
        "first_chapter_physical_page": first_chapter,
        "new_chapters": new_chapters,
        "new_chapter_pages": new_pages,
        "new_chapter_page_count": len(new_pages),
        "box_warning_pages": warning_pages,
        "box_warning_page_count": len(warning_pages),
        "fixed_control_pages": fixed,
        "targeted_200dpi_pages": selected,
        "targeted_200dpi_page_count": len(selected),
        "full_100dpi_pages": {"first": 1, "last": page_count, "count": page_count},
        "contact_sheets": {
            "pages_per_sheet": int(config["visual"]["contact_sheet_columns"]) * int(config["visual"]["contact_sheet_rows"]),
            "expected_count": int(config["visual"]["expected_contact_sheets"]),
            "gap_free_required": True,
        },
        "dynamic_paths": {key: root_relative(value) for key, value in dynamic.items()},
        "passed": True,
    }
    atomic_write_many({plan_path: json_bytes(plan)})
    print(json.dumps({"status": "PASS", "plan": file_record(plan_path), "targeted_pages": len(selected)}, indent=2))
    return 0


def load_visual_plan(config: dict[str, Any], receipt: dict[str, Any]) -> tuple[dict[str, Any], Path, dict[str, Path]]:
    plan_path = resolve_root_path(config["visual"]["plan"])
    plan = load_json(plan_path)
    if plan.get("schema") != "stacks-zh-hans-cn-r15-visual-plan/v1" or plan.get("passed") is not True:
        raise GateError("R15 visual plan is absent or not passing")
    if plan["pdf"]["sha256"] != receipt["build_bindings"]["pdf"]["sha256"]:
        raise GateError("visual plan binds another PDF")
    assert_binding(plan["pdf"], resolve_root_path(config["build"]["pdf"]), "visual-plan PDF")
    dynamic = visual_paths(plan["pdf"]["sha256"])
    declared = require_object(plan.get("dynamic_paths"), "visual plan dynamic_paths")
    for key, path in dynamic.items():
        if resolve_root_path(declared.get(key)) != path.resolve():
            raise GateError(f"visual plan dynamic path drift: {key}")
    return plan, plan_path, dynamic


def renderer_version() -> str:
    completed = subprocess.run(["pdftoppm", "-v"], text=True, capture_output=True, timeout=30)
    text = (completed.stdout + completed.stderr).strip().splitlines()
    if completed.returncode != 0 or not text:
        raise GateError("pdftoppm version query failed")
    return text[0]


def audit_pngs(
    directory: Path,
    pages: list[int],
    *,
    dpi: int,
    pdf_points: tuple[float, float],
) -> list[dict[str, object]]:
    try:
        from PIL import Image
    except ImportError as error:
        raise GateError("Pillow is required for R15 render QA") from error
    digits = max(4, len(str(max(pages))))
    expected_names = [f"page-{page:0{digits}d}.png" for page in pages]
    actual_paths = sorted(directory.glob("page-*.png"), key=lambda path: path.name)
    actual_names = [path.name for path in actual_paths]
    if actual_names != expected_names:
        missing = sorted(set(expected_names) - set(actual_names))
        extra = sorted(set(actual_names) - set(expected_names))
        raise GateError(f"render sequence mismatch: missing={missing[:10]}, extra={extra[:10]}")
    expected_dimensions = (
        math.ceil(pdf_points[0] / 72 * dpi),
        math.ceil(pdf_points[1] / 72 * dpi),
    )
    records = []
    for page, path in zip(pages, actual_paths, strict=True):
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            dimensions = image.size
            mode = image.mode
        if dimensions != expected_dimensions or mode != "RGB":
            raise GateError(
                f"page {page} render contract drift: {dimensions}/{mode} != {expected_dimensions}/RGB"
            )
        records.append(
            {
                "page": page,
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "width_px": dimensions[0],
                "height_px": dimensions[1],
                "mode": mode,
            }
        )
    return records


def write_csv(path: Path, records: list[dict[str, object]]) -> bytes:
    if not records:
        raise GateError("cannot serialize an empty render manifest")
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(records[0]))
    writer.writeheader()
    writer.writerows(records)
    return stream.getvalue().encode("utf-8")


def ordered_page_binding(records: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(f"{record['page']}\t{record['sha256']}\n".encode("ascii"))
    return digest.hexdigest().upper()


def command_audit_render(args: argparse.Namespace) -> int:
    config = load_config()
    receipt, _, build = validate_bound_receipt(config)
    plan, plan_path, dynamic = load_visual_plan(config, receipt)
    if args.kind == "full":
        pages = list(range(1, int(config["expected"]["page_count"]) + 1))
        directory = dynamic["full_dir"]
        manifest_path = dynamic["full_manifest"]
        summary_path = dynamic["full_summary"]
        dpi = int(config["visual"]["full_render_dpi"])
        schema = "stacks-zh-hans-cn-r15-full-render-audit/v1"
        stderr_path = dynamic["full_stderr"]
    else:
        pages = [int(value) for value in plan["targeted_200dpi_pages"]]
        directory = dynamic["targeted_dir"]
        manifest_path = dynamic["targeted_manifest"]
        summary_path = dynamic["targeted_summary"]
        dpi = int(config["visual"]["targeted_render_dpi"])
        schema = "stacks-zh-hans-cn-r15-targeted-render-audit/v1"
        stderr_path = dynamic["targeted_stderr"]
    if not stderr_path.is_file():
        raise GateError(f"render stderr receipt is missing: {stderr_path}")
    if stderr_path.stat().st_size != 0:
        raise GateError(f"render stderr is nonempty: {stderr_path}")
    records = audit_pngs(
        directory,
        pages,
        dpi=dpi,
        pdf_points=tuple(float(value) for value in config["expected"]["a4_points"]),
    )
    manifest_payload = write_csv(manifest_path, records)
    manifest_binding = {
        "path": root_relative(manifest_path),
        "bytes": len(manifest_payload),
        "sha256": sha256_bytes(manifest_payload),
    }
    summary = {
        "schema": schema,
        "release_candidate": config["release_candidate"],
        "pdf": receipt["build_bindings"]["pdf"],
        "visual_plan": file_record(plan_path),
        "renderer": {"name": "pdftoppm", "implementation": "Poppler", "version": renderer_version()},
        "renderer_stderr": file_record(stderr_path),
        "render_dpi": dpi,
        "render_directory": root_relative(directory),
        "page_count": int(config["expected"]["page_count"]),
        "rendered_page_count": len(records),
        "rendered_pages": pages if args.kind == "targeted" else {"first": 1, "last": pages[-1], "count": len(pages)},
        "total_bytes": sum(int(record["bytes"]) for record in records),
        "dimensions_px": [
            list(value)
            for value in sorted(
                {
                    (int(record["width_px"]), int(record["height_px"]))
                    for record in records
                }
            )
        ],
        "mode": "RGB",
        "ordered_page_hash_binding_sha256": ordered_page_binding(records),
        "manifest": manifest_binding,
        "passed": True,
    }
    atomic_write_many({manifest_path: manifest_payload, summary_path: json_bytes(summary)})
    print(json.dumps({"status": "PASS", "kind": args.kind, "manifest": file_record(manifest_path), "summary": file_record(summary_path)}, indent=2))
    return 0


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def command_audit_contacts(_: argparse.Namespace) -> int:
    config = load_config()
    receipt, _, _ = validate_bound_receipt(config)
    plan, _, dynamic = load_visual_plan(config, receipt)
    full_summary = load_json(dynamic["full_summary"])
    assert_binding(full_summary["pdf"], resolve_root_path(config["build"]["pdf"]), "full-render PDF")
    rows = read_csv(dynamic["contact_manifest"])
    if not dynamic["contact_stderr"].is_file():
        raise GateError("contact-sheet stderr receipt is missing")
    if dynamic["contact_stderr"].stat().st_size != 0:
        raise GateError("contact-sheet stderr is nonempty")
    expected_pages = int(config["expected"]["page_count"])
    per_sheet = int(plan["contact_sheets"]["pages_per_sheet"])
    expected_sheets = int(plan["contact_sheets"]["expected_count"])
    if len(rows) != expected_sheets:
        raise GateError(f"contact-sheet count drift: {len(rows)} != {expected_sheets}")
    covered: list[int] = []
    verified_rows = []
    try:
        from PIL import Image
    except ImportError as error:
        raise GateError("Pillow is required for contact-sheet QA") from error
    for index, row in enumerate(rows, start=1):
        sheet = int(row["sheet"])
        first = int(row["first_page"])
        last = int(row["last_page"])
        expected_first = (index - 1) * per_sheet + 1
        expected_last = min(index * per_sheet, expected_pages)
        if sheet != index or first != expected_first or last != expected_last:
            raise GateError(f"contact-sheet range drift at sheet {index}: {first}-{last}")
        path = Path(row["path"])
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        if path.parent != dynamic["contact_dir"].resolve() or not path.is_file():
            raise GateError(f"contact-sheet path drift: {path}")
        if int(row["bytes"]) != path.stat().st_size or row["sha256"].upper() != sha256(path):
            raise GateError(f"contact-sheet identity drift: {path}")
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            dimensions = image.size
            mode = image.mode
        expected_dimensions = (
            12 + int(config["visual"]["contact_sheet_columns"]) * (300 + 12),
            12 + int(config["visual"]["contact_sheet_rows"]) * (424 + 24 + 12),
        )
        if dimensions != expected_dimensions or mode != "RGB":
            raise GateError(
                f"contact-sheet image contract drift at sheet {index}: "
                f"{dimensions}/{mode} != {expected_dimensions}/RGB"
            )
        covered.extend(range(first, last + 1))
        verified_rows.append(
            {
                "sheet": sheet,
                "first_page": first,
                "last_page": last,
                "path": root_relative(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "width_px": dimensions[0],
                "height_px": dimensions[1],
                "mode": mode,
            }
        )
    if covered != list(range(1, expected_pages + 1)):
        raise GateError("contact sheets do not cover every page exactly once in order")
    digest = hashlib.sha256()
    for row in verified_rows:
        digest.update(f"{row['sheet']}\t{row['first_page']}\t{row['last_page']}\t{row['sha256']}\n".encode("ascii"))
    summary = {
        "schema": "stacks-zh-hans-cn-r15-contact-sheet-audit/v1",
        "release_candidate": config["release_candidate"],
        "pdf": receipt["build_bindings"]["pdf"],
        "full_render_summary": file_record(dynamic["full_summary"]),
        "contact_sheet_manifest": file_record(dynamic["contact_manifest"]),
        "generator_stderr": file_record(dynamic["contact_stderr"]),
        "contact_sheet_directory": root_relative(dynamic["contact_dir"]),
        "contact_sheet_count": len(rows),
        "pages_per_sheet": per_sheet,
        "covered_pages": {"first": 1, "last": expected_pages, "count": len(covered)},
        "gap_count": 0,
        "duplicate_page_count": 0,
        "dimensions_px": [list(expected_dimensions)],
        "mode": "RGB",
        "ordered_sheet_hash_binding_sha256": digest.hexdigest().upper(),
        "records": verified_rows,
        "passed": True,
    }
    atomic_write_many({dynamic["contact_summary"]: json_bytes(summary)})
    print(json.dumps({"status": "PASS", "summary": file_record(dynamic["contact_summary"]), "sheets": len(rows)}, indent=2))
    return 0


def validate_render_receipts(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Path]]:
    receipt, _, _ = validate_bound_receipt(config)
    plan, _, dynamic = load_visual_plan(config, receipt)
    full = load_json(dynamic["full_summary"])
    targeted = load_json(dynamic["targeted_summary"])
    contacts = load_json(dynamic["contact_summary"])
    if full.get("schema") != "stacks-zh-hans-cn-r15-full-render-audit/v1" or full.get("passed") is not True:
        raise GateError("full-render audit is absent or not passing")
    if targeted.get("schema") != "stacks-zh-hans-cn-r15-targeted-render-audit/v1" or targeted.get("passed") is not True:
        raise GateError("targeted-render audit is absent or not passing")
    if contacts.get("schema") != "stacks-zh-hans-cn-r15-contact-sheet-audit/v1" or contacts.get("passed") is not True:
        raise GateError("contact-sheet audit is absent or not passing")
    assert_binding(full.get("manifest"), dynamic["full_manifest"], "full-render manifest")
    assert_binding(targeted.get("manifest"), dynamic["targeted_manifest"], "targeted-render manifest")
    assert_binding(contacts.get("contact_sheet_manifest"), dynamic["contact_manifest"], "contact-sheet manifest")
    assert_binding(full.get("renderer_stderr"), dynamic["full_stderr"], "full-render stderr")
    assert_binding(targeted.get("renderer_stderr"), dynamic["targeted_stderr"], "targeted-render stderr")
    assert_binding(contacts.get("generator_stderr"), dynamic["contact_stderr"], "contact-sheet stderr")
    pdf_hash = receipt["build_bindings"]["pdf"]["sha256"]
    for label, value in (("full", full), ("targeted", targeted), ("contacts", contacts)):
        if value["pdf"]["sha256"] != pdf_hash:
            raise GateError(f"{label} render evidence binds another PDF")
    if int(full["rendered_page_count"]) != int(config["expected"]["page_count"]):
        raise GateError("full-render page count drift")
    if [int(value) for value in targeted["rendered_pages"]] != [int(value) for value in plan["targeted_200dpi_pages"]]:
        raise GateError("targeted-render page list drift")
    if int(contacts["contact_sheet_count"]) != int(config["visual"]["expected_contact_sheets"]):
        raise GateError("contact-sheet count drift")
    return full, targeted, contacts, dynamic


def command_make_inspection_template(_: argparse.Namespace) -> int:
    config = load_config()
    receipt, _, _ = validate_bound_receipt(config)
    plan, _, _ = load_visual_plan(config, receipt)
    full, targeted, contacts, dynamic = validate_render_receipts(config)
    template = load_json(QA / "R15_VISUAL_INSPECTION_TEMPLATE.json")
    inspection_path = resolve_root_path(config["visual"]["inspection"])
    template.update(
        {
            "pdf": receipt["build_bindings"]["pdf"],
            "contact_sheet_evidence": {
                "summary": file_record(dynamic["contact_summary"]),
                "manifest": file_record(dynamic["contact_manifest"]),
                "sheet_count": contacts["contact_sheet_count"],
                "required_ranges": [[row["first_page"], row["last_page"]] for row in contacts["records"]],
            },
            "targeted_200dpi_evidence": {
                "summary": file_record(dynamic["targeted_summary"]),
                "manifest": file_record(dynamic["targeted_manifest"]),
                "target_count": targeted["rendered_page_count"],
                "required_pages": plan["targeted_200dpi_pages"],
            },
            "full_100dpi_evidence": {
                "summary": file_record(dynamic["full_summary"]),
                "manifest": file_record(dynamic["full_manifest"]),
                "page_count": full["rendered_page_count"],
            },
        }
    )
    atomic_write_many({inspection_path: json_bytes(template)})
    print(json.dumps({"status": "PENDING_AGENT_INSPECTION", "inspection": file_record(inspection_path)}, indent=2))
    return 0


def validate_visual_inspection(
    config: dict[str, Any],
    plan: dict[str, Any],
    contacts: dict[str, Any],
    targeted: dict[str, Any],
    dynamic: dict[str, Path],
) -> dict[str, Any]:
    path = resolve_root_path(config["visual"]["inspection"])
    receipt = load_json(path)
    if receipt.get("schema") != "stacks-zh-hans-cn-r15-explicit-visual-inspection/v1":
        raise GateError("unexpected visual-inspection schema")
    if receipt.get("performed") is not True or receipt.get("passed") is not True:
        raise GateError("visual inspection is not complete and passing")
    if str(receipt.get("status")) != "PASS":
        raise GateError("visual inspection status is not PASS")
    inspection_id = receipt.get("inspection_id")
    if not isinstance(inspection_id, str) or not inspection_id.strip():
        raise GateError("visual inspection has no nonblank inspection_id")
    inspector = receipt.get("inspector")
    if not isinstance(inspector, str) or not inspector.strip():
        raise GateError("visual inspection has no nonblank inspector")
    inspected_at = receipt.get("inspected_at")
    if not isinstance(inspected_at, str) or not inspected_at.endswith("Z"):
        raise GateError("visual inspection inspected_at is not a UTC Z timestamp")
    try:
        parsed_inspected_at = datetime.fromisoformat(inspected_at[:-1] + "+00:00")
    except ValueError as error:
        raise GateError("visual inspection inspected_at is not ISO-8601") from error
    if parsed_inspected_at.utcoffset() is None or parsed_inspected_at.utcoffset().total_seconds() != 0:
        raise GateError("visual inspection inspected_at is not UTC")
    if int(receipt.get("blocker_count", -1)) != 0 or require_list(receipt.get("blockers"), "inspection blockers"):
        raise GateError("visual inspection retains blockers")
    if receipt.get("pdf", {}).get("sha256") != plan["pdf"]["sha256"]:
        raise GateError("visual inspection binds another PDF")
    required_ranges = [[row["first_page"], row["last_page"]] for row in contacts["records"]]
    actual_ranges = [[int(pair[0]), int(pair[1])] for pair in receipt.get("contact_sheet_ranges_inspected", [])]
    if actual_ranges != required_ranges:
        raise GateError("visual inspection does not attest every contact-sheet range exactly once")
    required_pages = [int(value) for value in plan["targeted_200dpi_pages"]]
    actual_pages = [int(value) for value in receipt.get("targeted_pages_inspected", [])]
    if actual_pages != required_pages:
        raise GateError("visual inspection does not attest every selected 200-dpi page exactly once")
    zero = require_object(receipt.get("required_zero_findings"), "required_zero_findings")
    required_zero_keys = {
        "clipped_or_out_of_page_text",
        "overlapping_text_or_math",
        "missing_or_tofu_glyphs",
        "blank_or_duplicate_reader_pages",
        "broken_diagrams_or_unreadable_labels",
        "header_footer_or_page_number_defects",
        "unacceptable_box_warning_manifestation",
    }
    if set(zero) != required_zero_keys:
        raise GateError("required visual finding keys do not match the contract")
    if any(type(value) is not int or value != 0 for value in zero.values()):
        raise GateError("required visual finding counts are not all numeric zero")
    if receipt.get("contact_sheet_evidence", {}).get("summary", {}).get("sha256") != sha256(dynamic["contact_summary"]):
        raise GateError("visual inspection contact-summary binding drift")
    if receipt.get("targeted_200dpi_evidence", {}).get("summary", {}).get("sha256") != sha256(dynamic["targeted_summary"]):
        raise GateError("visual inspection targeted-summary binding drift")
    return receipt


def command_finalize(_: argparse.Namespace) -> int:
    config = load_config()
    static = validate_static_inputs(config, full_replay=True)
    receipt, mechanical, build = validate_bound_receipt(config)
    plan, plan_path, _ = load_visual_plan(config, receipt)
    full, targeted, contacts, dynamic = validate_render_receipts(config)
    inspection = validate_visual_inspection(config, plan, contacts, targeted, dynamic)
    final_path = resolve_root_path(config["visual"]["final_qa"])
    result = {
        "schema": "stacks-zh-hans-cn-r15-final-qa/v1",
        "release_candidate": config["release_candidate"],
        "locale": config["locale"],
        "authority_commit": config["authority_commit"],
        "chapter_count": config["expected"]["chapter_count"],
        "page_count": config["expected"]["page_count"],
        "pdf": receipt["build_bindings"]["pdf"],
        "source": {
            "manifest": file_record(static["manifest_path"]),
            "source_replay": file_record(static["replay_path"]),
            "verified_input_bindings": config["expected"]["verified_input_bindings"],
            "verified_generated_outputs": config["expected"]["generated_outputs"],
            "unique_reference_targets": config["expected"]["unique_reference_targets"],
            "unresolved_reference_targets": 0,
        },
        "build_qa": {
            "receipt": file_record(build["receipt"]),
            "final_log_converged": receipt["diagnostics"]["final_pass_convergence"]["converged"],
            "blocking_condition_counts": receipt["diagnostics"]["blocking_condition_counts"],
            "box_warning_counts": receipt["diagnostics"]["box_warning_counts"],
        },
        "mechanical_qa": {
            "receipt": file_record(build["mechanical"]),
            "passed": mechanical["passed"],
            "named_destinations": mechanical["named_destinations"]["total"],
            "internal_links": mechanical["link_targets"]["internal"],
            "resolved_internal_links": mechanical["link_targets"]["resolved_internal"],
            "font_count": mechanical["fonts"]["total"],
            "embedded_fonts": mechanical["fonts"]["embedded"],
            "fonts_with_to_unicode": mechanical["fonts"]["with_to_unicode"],
            "extracted_characters": mechanical["text_extraction"]["characters"],
            "extracted_cjk_ideographs": mechanical["text_extraction"]["cjk_unified_ideographs"],
            "replacement_characters": mechanical["text_extraction"]["replacement_characters"],
        },
        "visual_qa": {
            "plan": file_record(plan_path),
            "full_render_summary": file_record(dynamic["full_summary"]),
            "full_rendered_pages": full["rendered_page_count"],
            "contact_sheet_summary": file_record(dynamic["contact_summary"]),
            "contact_sheets": contacts["contact_sheet_count"],
            "targeted_render_summary": file_record(dynamic["targeted_summary"]),
            "targeted_200dpi_pages": targeted["rendered_page_count"],
            "inspection": file_record(resolve_root_path(config["visual"]["inspection"])),
            "inspection_id": inspection.get("inspection_id"),
            "passed": True,
        },
        "publication_performed": False,
        "passed": True,
    }
    atomic_write_many({final_path: json_bytes(result)})
    print(json.dumps({"status": "PASS", "final_qa": file_record(final_path), "pdf": result["pdf"]}, ensure_ascii=False, indent=2))
    return 0


def command_paths(_: argparse.Namespace) -> int:
    config = load_config()
    receipt, _, _ = validate_bound_receipt(config)
    plan, plan_path, dynamic = load_visual_plan(config, receipt)
    print(
        json.dumps(
            {
                "pdf": root_relative(resolve_root_path(config["build"]["pdf"])),
                "pdf_sha256": receipt["build_bindings"]["pdf"]["sha256"],
                "page_count": config["expected"]["page_count"],
                "full_render_dpi": config["visual"]["full_render_dpi"],
                "targeted_render_dpi": config["visual"]["targeted_render_dpi"],
                "targeted_pages": plan["targeted_200dpi_pages"],
                "visual_plan": root_relative(plan_path),
                **{key: root_relative(path) for key, path in dynamic.items()},
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_contract(_: argparse.Namespace) -> int:
    config = load_config()
    validate_static_inputs(config, full_replay=False)
    print(
        json.dumps(
            {
                "schema": "stacks-zh-hans-cn-r15-qa-contract/v1",
                "config": file_record(CONFIG_PATH),
                "expected_chapters": config["expected"]["chapter_count"],
                "expected_pages": config["expected"]["page_count"],
                "unbound_pdf_sha256": config["unbound_until_build_terminal"]["pdf_sha256"],
                "fail_closed_until_build_terminal": True,
                "stages": [
                    "preflight",
                    "bind-build",
                    "plan-visual",
                    "external 100-dpi and targeted 200-dpi rendering",
                    "audit-render --kind full",
                    "contact-sheet generation and audit-contacts",
                    "audit-render --kind targeted",
                    "make-inspection-template",
                    "complete agent visual inspection receipt",
                    "finalize",
                ],
                "writes_performed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed deterministic QA pipeline for the 116-chapter Stacks "
            "zh-Hans-CN R15 cumulative reader. No PDF identity is accepted until "
            "bind-build proves the configured build has terminated and stabilized."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    contract = subparsers.add_parser("contract", help="validate static contract without writing")
    contract.set_defaults(func=command_contract)
    preflight = subparsers.add_parser("preflight", help="rehash static inputs and report active build state")
    preflight.add_argument("--shallow", action="store_true", help="skip rehashing all 483 replay input/output records")
    preflight.set_defaults(func=command_preflight)
    bind = subparsers.add_parser("bind-build", help="bind a terminal, stable, passing build and run the mechanical audit")
    bind.set_defaults(func=command_bind_build)
    plan = subparsers.add_parser("plan-visual", help="derive warning/new-chapter/fixed 200-dpi targets from the bound PDF")
    plan.set_defaults(func=command_plan_visual)
    paths = subparsers.add_parser("paths", help="emit hash-derived render paths as JSON")
    paths.set_defaults(func=command_paths)
    audit = subparsers.add_parser("audit-render", help="audit an already rendered PNG set")
    audit.add_argument("--kind", choices=("full", "targeted"), required=True)
    audit.set_defaults(func=command_audit_render)
    contacts = subparsers.add_parser("audit-contacts", help="prove gap-free contact-sheet coverage")
    contacts.set_defaults(func=command_audit_contacts)
    inspection = subparsers.add_parser("make-inspection-template", help="bind render evidence into a pending inspection receipt")
    inspection.set_defaults(func=command_make_inspection_template)
    finalize = subparsers.add_parser("finalize", help="bind all passing source/build/mechanical/render/visual evidence")
    finalize.set_defaults(func=command_finalize)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (GateError, FileNotFoundError, json.JSONDecodeError, ValueError) as error:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
