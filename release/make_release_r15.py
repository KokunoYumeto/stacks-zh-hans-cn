from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Iterator


PUBLICATION_DATE = "2026-08-30"
RELEASE_ID = "2026-08-30-r15"
VERSION = "2026.08.30-r15"
AUTHORITY_COMMIT = "a04446e57ec1fbc252a871afcec7752fb2807b14"
CONCEPT_DOI = "10.5281/zenodo.22060287"
EXPECTED_PREVIOUS_ZENODO_RECORD_ID = 22105251
GITHUB_REPOSITORY = "KokunoYumeto/stacks-zh-hans-cn"
GITHUB_RELEASE_TAG = "zh-hans-cn-2026.08.30-r15"
EXPECTED_PREVIOUS_GITHUB_RELEASE_TAG = "zh-hans-cn-2026.08.26-r14"
EXPECTED_CHAPTERS = 116
EXPECTED_PAGES = 5906
EXPECTED_INPUT_BINDINGS = 360
EXPECTED_GENERATED_OUTPUTS = 123
EXPECTED_UNIQUE_REFERENCE_TARGETS = 16_745
ZIP_TIMESTAMP = (2026, 8, 30, 0, 0, 0)
PUBLIC_FILE_COUNT = 5
RASTER_SUFFIXES = {".jpg", ".jpeg", ".png"}
EXPECTED_PUBLIC_ARTIFACT_NAMES = [
    "00_Stacks_Project_zh-Hans-CN_Cumulative_116_Chapters_2026-08-30.pdf",
    "01_Stacks_Project_zh-Hans-CN_Cumulative_116_Chapters_2026-08-30_Source_and_Evidence.zip",
    "02_Stacks_Project_zh-Hans-CN_Cumulative_116_Chapters_2026-08-30_README.md",
    "03_Stacks_Project_zh-Hans-CN_Cumulative_116_Chapters_2026-08-30_RELEASE_MANIFEST.json",
    "04_SHA256SUMS_2026-08-30-r15.txt",
]

REQUIRED_QA_RECEIPTS = {
    "source replay": "qa/source-replay.json",
    "independent source-replay verification": "qa/source-replay-verification-r15.json",
    "build receipt": "qa/R15_REPAIR_BUILD_RECEIPT.json",
    "mechanical PDF audit": "qa/R15_REPAIR_PDF_MECHANICAL.json",
    "visual PDF audit": "qa/R15_REPAIR_VISUAL_INSPECTION.json",
    "final prepublication QA": "qa/R15_REPAIR_FINAL_QA.json",
    "generated freeze rebind": "qa/R15_GENERATED_FREEZE_REBIND.json",
    "generated freeze chain audit": "qa/R15_GENERATED_FREEZE_CHAIN_AUDIT_01.json",
    "release evidence chain": "qa/R15_RELEASE_EVIDENCE_CHAIN_01.json",
}

EXPECTED_R14_GITHUB_RECEIPT = {
    "bytes": 3958,
    "sha256": "ED5B606227D317A8DCC29DED2B031EF5B4B7C39F0DE6596E1E654AB25237A2EE",
}
EXPECTED_R14_ZENODO_RECEIPT = {
    "bytes": 3579,
    "sha256": "B7B9F540E14F163F0CF55CEA868F9540AF27EE5B158CED15B2EC1027666FCA90",
}
TEXT_PUBLICIZATION_SUFFIXES = {
    ".aux",
    ".bbl",
    ".blg",
    ".cls",
    ".csv",
    ".fls",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".out",
    ".ps1",
    ".py",
    ".sty",
    ".tex",
    ".txt",
    ".toc",
    ".toml",
}
PUBLICIZATION_REPLACEMENTS: list[tuple[str, str]] = []
PUBLICIZATION_RECORDS: dict[str, dict[str, object]] = {}
PUBLICIZATION_DRIVES: set[str] = set()


class ReleaseInputError(RuntimeError):
    pass


def configure_publicization(root: Path, program_root: Path) -> None:
    global PUBLICIZATION_REPLACEMENTS, PUBLICIZATION_RECORDS, PUBLICIZATION_DRIVES
    home = Path.home().resolve()
    workspace_root = next(
        (value for value in (root, *root.parents) if value.name.lower() == "interlanguage"),
        program_root,
    )
    candidates: list[tuple[Path, str]] = [
        (root.resolve(), "${CANON_ROOT}"),
        (program_root.resolve(), "${PROGRAM_ROOT}"),
        (workspace_root.resolve(), "${WORKSPACE_ROOT}"),
        ((home / "AppData" / "Local" / "Programs" / "MiKTeX").resolve(), "${TEXMF_ROOT}"),
        ((home / "AppData" / "Local" / "MiKTeX").resolve(), "${MIKTEX_DATA_ROOT}"),
        ((home / "AppData" / "Roaming" / "MiKTeX").resolve(), "${MIKTEX_CONFIG_ROOT}"),
        (home, "${USER_HOME}"),
    ]
    for environment_name, token in (
        ("WINDIR", "${WINDOWS_ROOT}"),
        ("ProgramFiles", "${PROGRAM_FILES}"),
        ("ProgramFiles(x86)", "${PROGRAM_FILES_X86}"),
    ):
        value = os.environ.get(environment_name)
        if value:
            candidates.append((Path(value).resolve(), token))
    replacements: dict[str, str] = {}
    private_fragment = home.name
    for path, token in candidates:
        literal = str(path)
        variants = {
            literal,
            path.as_posix(),
            literal.replace("\\", "\\\\"),
        }
        if private_fragment:
            variants.update(
                re.sub(
                    re.escape(private_fragment),
                    "<USER>",
                    variant,
                    flags=re.IGNORECASE,
                )
                for variant in tuple(variants)
            )
        for variant in variants:
            replacements[variant] = token
    PUBLICIZATION_REPLACEMENTS = sorted(
        replacements.items(), key=lambda pair: len(pair[0]), reverse=True
    )
    PUBLICIZATION_RECORDS = {}
    PUBLICIZATION_DRIVES = {
        path.drive.rstrip(":").upper() for path, _ in candidates if path.drive
    }


def sanitize_public_bytes(data: bytes, label: str) -> tuple[bytes, list[str]]:
    suffix = Path(label).suffix.lower()
    if suffix not in TEXT_PUBLICIZATION_SUFFIXES:
        require_public_bytes_clean(data, label)
        return data, []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"declared text public payload is not UTF-8: {label}") from exc
    applied: list[str] = []
    for source, token in PUBLICIZATION_REPLACEMENTS:
        updated, count = re.subn(re.escape(source), token, text, flags=re.IGNORECASE)
        if count:
            text = updated
            applied.append(token)
    private_fragment = Path.home().name
    if private_fragment:
        text, count = re.subn(
            re.escape(private_fragment), "<USER>", text, flags=re.IGNORECASE
        )
        if count:
            applied.append("<USER>")
    public = text.encode("utf-8")
    require_public_bytes_clean(public, label)
    return public, sorted(set(applied))


def require_public_bytes_clean(
    data: bytes, label: str, *, text_payload: bool | None = None
) -> None:
    fragment = Path.home().name.encode("utf-8")
    lowered = data.lower()
    if fragment and fragment.lower() in lowered:
        raise RuntimeError(f"private user-name fragment remains in public payload: {label}")
    if text_payload is None:
        text_payload = Path(label).suffix.lower() in TEXT_PUBLICIZATION_SUFFIXES
    if not text_payload:
        return
    text = data.decode("utf-8")
    # Restrict the filesystem-path test to drive designators actually used by
    # the roots registered above.  This keeps mathematical TeX maps such as
    # ``D:\\mathcal B\\to`` intact while rejecting both literal and
    # JSON-escaped paths on the current machine.
    for drive in PUBLICIZATION_DRIVES:
        if re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(drive)}:(?:\\\\|\\|/)", text
        ):
            raise RuntimeError(
                f"absolute Windows drive path remains in public payload: {label}"
            )
    # The path character requirement avoids flagging this validator's own
    # source literal while still rejecting an actual local or remote file URI.
    if re.search(rb"(?i)file://(?:/|[A-Za-z0-9._~-])", data):
        raise RuntimeError(f"file URI remains in public payload: {label}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def file_record(path: Path) -> dict[str, object]:
    return {"filename": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}


def bound_file_record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseInputError(f"required release input is missing: {path}") from exc
    if not isinstance(value, dict):
        raise ReleaseInputError(f"JSON release input is not an object: {path}")
    return value


def require_versioned_schema(value: dict[str, object], prefix: str, label: str) -> str:
    schema = str(value.get("schema") or "")
    marker = f"{prefix}/v"
    suffix = schema.removeprefix(marker)
    if not schema.startswith(marker) or not suffix.isdigit() or int(suffix) < 1:
        raise ReleaseInputError(f"{label} lacks a supported versioned schema: {schema!r}")
    return schema


def require_required_receipts(root: Path) -> dict[str, Path]:
    paths = {label: root / relative for label, relative in REQUIRED_QA_RECEIPTS.items()}
    missing = [
        f"{path.relative_to(root).as_posix()} ({label})"
        for label, path in paths.items()
        if not path.is_file()
    ]
    if missing:
        details = "\n".join(f"  - {value}" for value in missing)
        raise ReleaseInputError(
            "R15 packaging preflight failed; packaging did not start. "
            f"Required QA inputs are missing:\n{details}"
        )
    return paths


def resolve_program_path(program_root: Path, relative: str) -> Path:
    path = (program_root / Path(relative)).resolve()
    if program_root != path and program_root not in path.parents:
        raise ReleaseInputError(f"release input escapes program root: {relative}")
    return path


def resolve_receipt_path(root: Path, recorded: object, label: str) -> Path:
    if not isinstance(recorded, str) or not recorded:
        raise ReleaseInputError(f"{label} has no path")
    candidate = Path(recorded)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if root != path and root not in path.parents:
        raise ReleaseInputError(f"{label} points outside the Chinese canon root: {recorded}")
    return path


def validate_bound_record(root: Path, record: dict[str, object], label: str) -> Path:
    path = resolve_receipt_path(root, record.get("path"), label)
    if not path.is_file():
        raise ReleaseInputError(f"{label} points to a missing file: {path}")
    try:
        expected_bytes = int(record["bytes"])
        expected_sha = str(record["sha256"]).upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseInputError(f"{label} is not a complete byte/hash file binding") from exc
    actual_bytes = path.stat().st_size
    actual_sha = sha256(path)
    if actual_bytes != expected_bytes or actual_sha != expected_sha:
        raise ReleaseInputError(
            f"{label} byte/hash binding failed for {path}: "
            f"actual=({actual_bytes}, {actual_sha}) "
            f"expected=({expected_bytes}, {expected_sha})"
        )
    return path


def validate_exact_bound_record(
    root: Path,
    record: dict[str, object],
    expected_path: Path,
    label: str,
) -> Path:
    path = validate_bound_record(root, record, label)
    if path != expected_path.resolve():
        raise ReleaseInputError(
            f"{label} points to the wrong file: {path} != {expected_path.resolve()}"
        )
    return path


def iter_bound_records(value: object, label: str = "receipt") -> Iterator[tuple[str, dict[str, object]]]:
    if isinstance(value, dict):
        if {"path", "bytes", "sha256"}.issubset(value):
            yield label, value
        for key, child in value.items():
            yield from iter_bound_records(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_bound_records(child, f"{label}[{index}]")


def validate_exact_external_file(
    path: Path, expected: dict[str, object], label: str
) -> None:
    if not path.is_file():
        raise ReleaseInputError(f"{label} is missing: {path}")
    actual = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    if actual != expected:
        raise ReleaseInputError(
            f"{label} identity drift: actual={actual}, expected={expected}"
        )


def validate_r14_lineage(root: Path) -> dict[str, object]:
    receipt_root = root.parent / "zh-hans-cn" / "release" / "receipts"
    github_path = receipt_root / "GITHUB_PUBLICATION_RECEIPT_20260826_R14.json"
    zenodo_path = receipt_root / "ZENODO_PUBLICATION_RECEIPT_20260826_R14.json"
    validate_exact_external_file(
        github_path, EXPECTED_R14_GITHUB_RECEIPT, "R14 GitHub publication receipt"
    )
    validate_exact_external_file(
        zenodo_path, EXPECTED_R14_ZENODO_RECEIPT, "R14 Zenodo publication receipt"
    )
    github = load_json(github_path)
    zenodo = load_json(zenodo_path)
    if github.get("schema") != "stacks-zh-hans-cn-github-publication-receipt/v3":
        raise ReleaseInputError("R14 GitHub publication-receipt schema drift")
    if zenodo.get("schema") != "stacks-zh-hans-cn-zenodo-publication-receipt/v2":
        raise ReleaseInputError("R14 Zenodo publication-receipt schema drift")
    if (
        github.get("repository") != GITHUB_REPOSITORY
        or github.get("visibility") != "public"
        or github.get("release_tag") != EXPECTED_PREVIOUS_GITHUB_RELEASE_TAG
        or github.get("anonymous_public_readback_passed") is not True
        or github.get("authority_commit") != AUTHORITY_COMMIT
        or github.get("release_id") != "2026-08-26-r14"
    ):
        raise ReleaseInputError("R14 GitHub lineage/public-access fields drift")
    if (
        int(zenodo.get("record_id", -1)) != EXPECTED_PREVIOUS_ZENODO_RECORD_ID
        or zenodo.get("conceptdoi") != CONCEPT_DOI
        or zenodo.get("action") != "existing_public_version_already_matches"
        or zenodo.get("pdf_present_verified") is not True
        or zenodo.get("authority_commit") != AUTHORITY_COMMIT
        or zenodo.get("release_id") != "2026-08-26-r14"
    ):
        raise ReleaseInputError("R14 Zenodo lineage/public-access fields drift")
    github_assets = list(github.get("public_release_assets") or [])
    zenodo_assets = list(zenodo.get("public_readback") or [])
    if len(github_assets) != PUBLIC_FILE_COUNT or len(zenodo_assets) != PUBLIC_FILE_COUNT:
        raise ReleaseInputError("R14 public inventories are not exactly five files")

    def inventory(records: list[object], label: str) -> dict[str, tuple[int, str]]:
        result: dict[str, tuple[int, str]] = {}
        for index, raw in enumerate(records, start=1):
            if not isinstance(raw, dict):
                raise ReleaseInputError(f"{label} row {index} is not an object")
            name = str(raw.get("filename") or "")
            identity = (int(raw.get("bytes", -1)), str(raw.get("sha256") or "").upper())
            if not name or name in result or identity[0] < 0 or len(identity[1]) != 64:
                raise ReleaseInputError(f"{label} row {index} is malformed or duplicate")
            if not str(raw.get("url") or "").startswith("https://"):
                raise ReleaseInputError(f"{label} row {index} lacks a public HTTPS URL")
            result[name] = identity
        return result

    github_inventory = inventory(github_assets, "R14 GitHub inventory")
    zenodo_inventory = inventory(zenodo_assets, "R14 Zenodo inventory")
    if github_inventory != zenodo_inventory:
        raise ReleaseInputError("R14 GitHub and Zenodo public inventories differ")
    expected_names = list(github.get("public_asset_order") or [])
    if (
        expected_names != list(github_inventory)
        or list(zenodo.get("expected_upload_order") or []) != expected_names
        or set(zenodo.get("public_file_order") or []) != set(expected_names)
    ):
        raise ReleaseInputError("R14 five-file inventory names/order drift")
    return {
        "github_path": github_path,
        "zenodo_path": zenodo_path,
        "github": github,
        "zenodo": zenodo,
        "inventory": github_inventory,
    }


def validate_preflight(root: Path) -> dict[str, object]:
    root = root.resolve()
    lineage = validate_r14_lineage(root)
    receipt_paths = require_required_receipts(root)
    manifest_path = root / "manifest.json"
    source_pdf = root / "build" / "stacks-zh-hans-cn-partial.pdf"
    static_inputs = [
        manifest_path,
        root / "compose.py",
        root / "build.ps1",
        root / "release" / "make_release_r15.py",
        root / "qa" / "verify_source_replay_r15.py",
        root / "qa" / "r15_qa_pipeline.py",
        root / "qa" / "R15_QA_CONFIG.json",
        source_pdf,
    ]
    missing_static = [path for path in static_inputs if not path.is_file()]
    if missing_static:
        details = "\n".join(
            f"  - {path.relative_to(root).as_posix()}" for path in missing_static
        )
        raise ReleaseInputError(f"required deterministic build inputs are missing:\n{details}")

    manifest = load_json(manifest_path)
    source_replay = load_json(receipt_paths["source replay"])
    replay_verification = load_json(
        receipt_paths["independent source-replay verification"]
    )
    build_receipt = load_json(receipt_paths["build receipt"])
    pdf_audit = load_json(receipt_paths["mechanical PDF audit"])
    visual_qa = load_json(receipt_paths["visual PDF audit"])
    final_qa = load_json(receipt_paths["final prepublication QA"])
    freeze_rebind = load_json(receipt_paths["generated freeze rebind"])
    freeze_chain = load_json(receipt_paths["generated freeze chain audit"])
    evidence_chain = load_json(receipt_paths["release evidence chain"])

    require_versioned_schema(
        source_replay, "stacks-zh-hans-cn-source-replay", "source replay"
    )
    require_versioned_schema(
        replay_verification,
        "stacks-zh-hans-cn-source-replay-verification",
        "independent source-replay verification",
    )
    require_versioned_schema(
        build_receipt, "stacks-zh-hans-cn-r15-build-receipt", "build receipt"
    )
    require_versioned_schema(
        pdf_audit, "stacks-zh-hans-cn-r15-pdf-mechanical", "mechanical PDF audit"
    )
    require_versioned_schema(
        visual_qa,
        "stacks-zh-hans-cn-r15-explicit-visual-inspection",
        "visual PDF audit",
    )
    require_versioned_schema(
        final_qa, "stacks-zh-hans-cn-r15-final-qa", "final prepublication QA"
    )
    if (
        freeze_rebind.get("schema")
        != "stacks_zh_hans_cn_r15_generated_freeze_rebind/v1"
        or freeze_rebind.get("status") != "PASS"
    ):
        raise ReleaseInputError("generated-freeze rebind schema/status drift")
    if (
        freeze_chain.get("schema")
        != "stacks_zh_hans_cn_r15_generated_freeze_chain_audit/v1"
        or freeze_chain.get("passed") is not True
    ):
        raise ReleaseInputError("generated-freeze chain-audit schema/status drift")
    if (
        evidence_chain.get("schema")
        != "stacks-zh-hans-cn-r15-release-evidence-chain/v1"
        or evidence_chain.get("status") != "PASS"
        or evidence_chain.get("passed") is not True
        or evidence_chain.get("append_only_closure") is not True
        or str(evidence_chain.get("release_candidate")) != VERSION
        or str(evidence_chain.get("authority_commit")) != AUTHORITY_COMMIT
    ):
        raise ReleaseInputError("R15 release-evidence chain is not passing")

    chapters = list(manifest.get("chapters") or [])
    chapter_count = len(chapters)
    chapter_numbers = [int(chapter["chapter"]) for chapter in chapters]
    if str((manifest.get("authority") or {}).get("commit")) != AUTHORITY_COMMIT:
        raise ReleaseInputError("release manifest authority drift")
    if chapter_count != EXPECTED_CHAPTERS:
        raise ReleaseInputError(
            f"expected {EXPECTED_CHAPTERS} chapters, got {chapter_count}"
        )
    if len(chapter_numbers) != len(set(chapter_numbers)):
        raise ReleaseInputError("release manifest contains duplicate chapter numbers")
    if chapter_numbers != list(range(1, EXPECTED_CHAPTERS + 1)):
        raise ReleaseInputError("release manifest chapter sequence is not exactly 1 through 116")

    if source_replay.get("passed") is not True:
        raise ReleaseInputError("source replay is not passing")
    if int(source_replay.get("chapter_count", -1)) != chapter_count:
        raise ReleaseInputError("source replay chapter count differs from the manifest")
    if str(source_replay.get("authority_commit")) != AUTHORITY_COMMIT:
        raise ReleaseInputError("source replay authority commit drift")
    reference = source_replay.get("reference_resolution") or {}
    if list(reference.get("unresolved_targets") or []):
        raise ReleaseInputError("source replay contains unresolved reference targets")
    if int(reference.get("unique_targets", -1)) != EXPECTED_UNIQUE_REFERENCE_TARGETS:
        raise ReleaseInputError("source replay unique-reference-target count drift")

    if replay_verification.get("passed") is not True:
        raise ReleaseInputError("independent source-replay verification is not passing")
    if (
        str(replay_verification.get("authority_commit")) != AUTHORITY_COMMIT
        or replay_verification.get("hashes_derived_at_verification_time") is not True
    ):
        raise ReleaseInputError("independent source-replay verification provenance drift")
    replay_numbers = {
        "chapter_count": (int(replay_verification.get("chapter_count", -1)), chapter_count),
        "verified_input_bindings": (
            int(replay_verification.get("verified_input_bindings", -1)),
            EXPECTED_INPUT_BINDINGS,
        ),
        "verified_generated_outputs": (
            int(replay_verification.get("verified_generated_outputs", -1)),
            EXPECTED_GENERATED_OUTPUTS,
        ),
        "unresolved_reference_targets": (
            int(replay_verification.get("unresolved_reference_targets", -1)),
            0,
        ),
        "unique_reference_targets": (
            int(replay_verification.get("unique_reference_targets", -1)),
            EXPECTED_UNIQUE_REFERENCE_TARGETS,
        ),
    }
    drift = {
        key: {"actual": actual, "expected": expected}
        for key, (actual, expected) in replay_numbers.items()
        if actual != expected
    }
    if drift:
        raise ReleaseInputError(f"source-replay verification drift: {drift}")
    validate_exact_bound_record(
        root,
        replay_verification["source_replay"],
        receipt_paths["source replay"],
        "source replay verification.source_replay",
    )
    validate_exact_bound_record(
        root,
        replay_verification["manifest"],
        manifest_path,
        "source replay verification.manifest",
    )

    if build_receipt.get("passed") is not True or str(build_receipt.get("status")) != "PASS":
        raise ReleaseInputError("R15 build receipt is not passing")
    if str(build_receipt.get("release_candidate")) != VERSION:
        raise ReleaseInputError("R15 build receipt release-candidate version drift")
    if str(build_receipt.get("authority_commit")) != AUTHORITY_COMMIT:
        raise ReleaseInputError("R15 build receipt authority drift")
    if int((build_receipt.get("source_bindings") or {}).get("chapter_count", -1)) != chapter_count:
        raise ReleaseInputError("R15 build receipt chapter-count drift")
    build_source = build_receipt.get("source_bindings") or {}
    for key, expected in (
        ("verified_input_bindings", EXPECTED_INPUT_BINDINGS),
        ("verified_generated_outputs", EXPECTED_GENERATED_OUTPUTS),
        ("unique_reference_targets", EXPECTED_UNIQUE_REFERENCE_TARGETS),
        ("unresolved_reference_targets", 0),
    ):
        if int(build_source.get(key, -1)) != expected:
            raise ReleaseInputError(f"R15 build receipt {key} drift")
    validate_exact_bound_record(
        root,
        build_source.get("manifest") or {},
        manifest_path,
        "R15 build receipt.source_bindings.manifest",
    )
    validate_exact_bound_record(
        root,
        build_source.get("source_replay") or {},
        receipt_paths["source replay"],
        "R15 build receipt.source_bindings.source_replay",
    )

    page_count = int(pdf_audit.get("pages", -1))
    if page_count != EXPECTED_PAGES:
        raise ReleaseInputError(f"expected {EXPECTED_PAGES} pages, got {page_count}")
    if (
        pdf_audit.get("passed") is not True
        or int(pdf_audit.get("expected_pages", -1)) != EXPECTED_PAGES
    ):
        raise ReleaseInputError("final PDF mechanical audit is not passing")
    validation = pdf_audit.get("validation") or {}
    required_mechanical_gates = (
        "a4_only",
        "all_pages_unrotated",
        "all_named_destinations_resolve",
        "all_annotations_are_links",
        "all_internal_link_targets_resolve",
        "all_fonts_embedded",
        "all_type0_fonts_have_to_unicode",
        "all_pages_have_extractable_text",
        "all_pages_have_content_stream_bytes",
    )
    if any(validation.get(key) is not True for key in required_mechanical_gates):
        raise ReleaseInputError("final PDF mechanical sub-gates are not all passing")
    if pdf_audit.get("encrypted") is not False:
        raise ReleaseInputError("final PDF is encrypted")
    links = pdf_audit.get("link_targets") or {}
    if (
        int(links.get("internal", -1)) != int(links.get("resolved_internal", -2))
        or list(links.get("unresolved") or [])
    ):
        raise ReleaseInputError("final PDF retains unresolved internal links")
    extraction = pdf_audit.get("text_extraction") or {}
    if int(extraction.get("replacement_characters", -1)) != 0 or list(extraction.get("errors") or []):
        raise ReleaseInputError("final PDF text extraction is not clean")
    source_pdf_sha = sha256(source_pdf)
    validate_exact_bound_record(
        root,
        pdf_audit["pdf"],
        source_pdf,
        "mechanical PDF audit.pdf",
    )
    if str(pdf_audit["pdf"].get("sha256")).upper() != source_pdf_sha:
        raise ReleaseInputError("mechanical audit is bound to a different PDF")
    build_pdf = (build_receipt.get("build_bindings") or {}).get("pdf") or {}
    validate_exact_bound_record(
        root,
        build_pdf,
        source_pdf,
        "build receipt.build_bindings.pdf",
    )
    if str(build_pdf.get("sha256")).upper() != source_pdf_sha:
        raise ReleaseInputError("R15 build receipt is bound to a different PDF")
    if int(build_pdf.get("pages", -1)) != page_count:
        raise ReleaseInputError("R15 build receipt PDF page-count drift")
    validate_exact_bound_record(
        root,
        (build_receipt.get("build_bindings") or {}).get("mechanical_audit") or {},
        receipt_paths["mechanical PDF audit"],
        "R15 build receipt.build_bindings.mechanical_audit",
    )

    if (
        visual_qa.get("performed") is not True
        or visual_qa.get("passed") is not True
        or str(visual_qa.get("status")) != "PASS"
        or str(visual_qa.get("release_candidate")) != VERSION
        or not str(visual_qa.get("inspection_id") or "").strip()
        or not str(visual_qa.get("inspector") or "").strip()
        or not str(visual_qa.get("inspected_at") or "").strip()
    ):
        raise ReleaseInputError("final PDF visual inspection is not passing")
    visual_pdf = visual_qa.get("pdf") or {}
    validate_exact_bound_record(
        root,
        visual_pdf,
        source_pdf,
        "visual inspection.pdf",
    )
    if (
        int(visual_pdf.get("pages", -1)) != page_count
        or str(visual_pdf.get("sha256")).upper() != source_pdf_sha
        or int(visual_qa.get("page_count", -1)) != page_count
    ):
        raise ReleaseInputError("visual inspection is bound to a different PDF")
    contact = visual_qa.get("contact_sheet_evidence") or {}
    ranges = list(visual_qa.get("contact_sheet_ranges_inspected") or [])
    cursor = 1
    for index, pair in enumerate(ranges, start=1):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ReleaseInputError(f"visual contact-sheet range {index} is malformed")
        first, last = int(pair[0]), int(pair[1])
        if first != cursor or last < first or last > page_count:
            raise ReleaseInputError(f"visual contact-sheet coverage drifts at range {index}")
        cursor = last + 1
    if cursor != page_count + 1 or int(contact.get("sheet_count", -1)) != len(ranges):
        raise ReleaseInputError("contact-sheet evidence does not cover every PDF page")
    targeted = visual_qa.get("targeted_200dpi_evidence") or {}
    required_pages = [int(value) for value in targeted.get("required_pages") or []]
    inspected_pages = [int(value) for value in visual_qa.get("targeted_pages_inspected") or []]
    if (
        not required_pages
        or required_pages != sorted(set(required_pages))
        or inspected_pages != required_pages
        or required_pages[0] < 1
        or required_pages[-1] > page_count
        or int(targeted.get("target_count", -1)) != len(required_pages)
    ):
        raise ReleaseInputError("targeted visual inspection coverage is incomplete")
    full_render = visual_qa.get("full_100dpi_evidence") or {}
    if int(full_render.get("page_count", -1)) != page_count:
        raise ReleaseInputError("full-resolution render evidence does not cover every page")
    if int(visual_qa.get("blocker_count", -1)) != 0 or list(visual_qa.get("blockers") or []):
        raise ReleaseInputError("visual inspection retains blockers")
    zero_findings = visual_qa.get("required_zero_findings") or {}
    required_zero_keys = {
        "clipped_or_out_of_page_text",
        "overlapping_text_or_math",
        "missing_or_tofu_glyphs",
        "blank_or_duplicate_reader_pages",
        "broken_diagrams_or_unreadable_labels",
        "header_footer_or_page_number_defects",
        "unacceptable_box_warning_manifestation",
    }
    if set(zero_findings) != required_zero_keys or any(
        type(value) is not int or value != 0 for value in zero_findings.values()
    ):
        raise ReleaseInputError("visual inspection retains required visual findings")

    if final_qa.get("passed") is not True:
        raise ReleaseInputError("R15 final-QA receipt is not passing")
    if final_qa.get("publication_performed") is not False:
        raise ReleaseInputError("R15 final-QA receipt is not prepublication")
    if str(final_qa.get("release_candidate")) != VERSION:
        raise ReleaseInputError("R15 final-QA release-candidate version drift")
    if str(final_qa.get("authority_commit")) != AUTHORITY_COMMIT:
        raise ReleaseInputError("R15 final-QA authority drift")
    if int(final_qa.get("chapter_count", -1)) != chapter_count:
        raise ReleaseInputError("R15 final-QA chapter-count drift")
    if int(final_qa.get("page_count", -1)) != page_count:
        raise ReleaseInputError("R15 final-QA page-count drift")
    final_pdf = final_qa.get("pdf") or {}
    validate_exact_bound_record(
        root,
        final_pdf,
        source_pdf,
        "R15 final-QA.pdf",
    )
    if (
        int(final_pdf.get("pages", -1)) != page_count
        or str(final_pdf.get("sha256")).upper() != source_pdf_sha
    ):
        raise ReleaseInputError("R15 final-QA receipt is bound to a different PDF")

    final_build_qa = final_qa.get("build_qa") or {}
    validate_exact_bound_record(
        root,
        final_build_qa.get("receipt") or {},
        receipt_paths["build receipt"],
        "R15 final-QA.build_qa.receipt",
    )
    blocking_counts = final_build_qa.get("blocking_condition_counts") or {}
    if (
        final_build_qa.get("final_log_converged") is not True
        or not blocking_counts
        or any(int(value) != 0 for value in blocking_counts.values())
    ):
        raise ReleaseInputError("R15 final-QA build binding is not passing")

    final_mechanical_qa = final_qa.get("mechanical_qa") or {}
    validate_exact_bound_record(
        root,
        final_mechanical_qa.get("receipt") or {},
        receipt_paths["mechanical PDF audit"],
        "R15 final-QA.mechanical_qa.receipt",
    )
    if final_mechanical_qa.get("passed") is not True:
        raise ReleaseInputError("R15 final-QA mechanical binding is not passing")

    final_visual_qa = final_qa.get("visual_qa") or {}
    validate_exact_bound_record(
        root,
        final_visual_qa.get("inspection") or {},
        receipt_paths["visual PDF audit"],
        "R15 final-QA.visual_qa.inspection",
    )
    if (
        final_visual_qa.get("passed") is not True
        or int(final_visual_qa.get("full_rendered_pages", -1)) != page_count
        or int(final_visual_qa.get("contact_sheets", -1)) != len(ranges)
        or int(final_visual_qa.get("targeted_200dpi_pages", -1)) != len(required_pages)
    ):
        raise ReleaseInputError("R15 final-QA visual binding is not passing")

    final_source = final_qa.get("source") or {}
    for key, expected_path in (
        ("manifest", manifest_path),
        ("source_replay", receipt_paths["source replay"]),
    ):
        validate_exact_bound_record(
            root,
            final_source.get(key) or {},
            expected_path,
            f"R15 final-QA.source.{key}",
        )
    for key, expected in (
        ("verified_input_bindings", EXPECTED_INPUT_BINDINGS),
        ("verified_generated_outputs", EXPECTED_GENERATED_OUTPUTS),
        ("unique_reference_targets", EXPECTED_UNIQUE_REFERENCE_TARGETS),
        ("unresolved_reference_targets", 0),
    ):
        if int(final_source.get(key, -1)) != expected:
            raise ReleaseInputError(f"R15 final-QA source {key} drift")

    program_root = root.parent.parent
    for index, substitution in enumerate(
        replay_verification.get("verified_frozen_input_substitutions") or []
    ):
        logical = substitution.get("logical_manifest_target") or {}
        physical = substitution.get("physical_replay_input") or {}
        resolve_program_path(program_root, str(logical.get("path") or ""))
        if (
            int(logical.get("bytes", -1)) != int(physical.get("bytes", -2))
            or str(logical.get("sha256", "")).upper()
            != str(physical.get("sha256", "")).upper()
        ):
            raise ReleaseInputError(
                "source replay verification frozen-input identity mismatch at "
                f"substitution {index}"
            )

    receipt_bound_paths: dict[str, Path] = {}
    for receipt_label, receipt in (
        ("source replay verification", replay_verification),
        ("build receipt", build_receipt),
        ("mechanical receipt", pdf_audit),
        ("visual inspection", visual_qa),
        ("final QA", final_qa),
        ("release evidence chain", evidence_chain),
    ):
        for record_label, record in iter_bound_records(receipt, receipt_label):
            if (
                record_label.startswith(
                    "source replay verification.verified_frozen_input_substitutions["
                )
                and record_label.endswith(".logical_manifest_target")
            ):
                # This is a historical logical identity, not a lease on the
                # producer's mutable live file.  The exact same byte/hash
                # identity is proved above against the immutable physical replay
                # input, which is validated and packaged below.
                continue
            path = validate_bound_record(root, record, record_label)
            archive_name = path.relative_to(root).as_posix()
            receipt_bound_paths[archive_name] = path

    intake_paths: dict[str, Path] = {}
    for chapter in chapters:
        intake = chapter.get("intake") or {}
        path = resolve_program_path(program_root, str(intake.get("path") or ""))
        if not path.is_file():
            raise ReleaseInputError(f"chapter intake receipt is missing: {path}")
        expected_sha = str(intake.get("sha256") or "").upper()
        if expected_sha and sha256(path) != expected_sha:
            raise ReleaseInputError(f"chapter intake receipt hash drift: {path}")
        if intake.get("bytes") is not None and path.stat().st_size != int(intake["bytes"]):
            raise ReleaseInputError(f"chapter intake receipt byte-count drift: {path}")
        arcname = f"control/{path.name}"
        previous = intake_paths.get(arcname)
        if previous is not None and previous != path:
            raise ReleaseInputError(f"duplicate intake receipt archive name: {arcname}")
        intake_paths[arcname] = path

    return {
        "root": root,
        "program_root": program_root,
        "receipt_paths": receipt_paths,
        "manifest": manifest,
        "source_replay": source_replay,
        "replay_verification": replay_verification,
        "build_receipt": build_receipt,
        "pdf_audit": pdf_audit,
        "visual_qa": visual_qa,
        "final_qa": final_qa,
        "chapters": chapters,
        "chapter_numbers": chapter_numbers,
        "chapter_count": chapter_count,
        "page_count": page_count,
        "source_pdf": source_pdf,
        "source_pdf_sha256": source_pdf_sha,
        "receipt_bound_paths": receipt_bound_paths,
        "intake_paths": intake_paths,
        "lineage": lineage,
    }


def add_zip_bytes(payloads: dict[str, bytes], arcname: str, data: bytes) -> None:
    normalized = Path(arcname).as_posix()
    archive_path = Path(normalized)
    if (
        normalized.startswith("/")
        or archive_path.drive
        or archive_path.is_absolute()
        or ".." in archive_path.parts
    ):
        raise RuntimeError(f"unsafe release ZIP entry name: {arcname}")
    if Path(normalized).suffix.lower() in RASTER_SUFFIXES:
        raise RuntimeError(f"raster render/contact evidence must not enter release ZIP: {arcname}")
    public_data, transformations = sanitize_public_bytes(data, normalized)
    require_public_bytes_clean(public_data, normalized)
    previous = payloads.get(normalized)
    if previous is not None and previous != public_data:
        raise RuntimeError(f"conflicting duplicate release ZIP entry: {normalized}")
    payloads[normalized] = public_data
    record = {
        "path": normalized,
        "source_bytes": len(data),
        "source_sha256": sha256_bytes(data),
        "public_bytes": len(public_data),
        "public_sha256": sha256_bytes(public_data),
        "changed": public_data != data,
        "transformations": transformations,
    }
    prior_record = PUBLICIZATION_RECORDS.get(normalized)
    if prior_record is not None and prior_record != record:
        raise RuntimeError(f"conflicting publicization record: {normalized}")
    PUBLICIZATION_RECORDS[normalized] = record


def add_zip_path(payloads: dict[str, bytes], path: Path, arcname: str) -> None:
    if not path.is_file():
        raise ReleaseInputError(f"release ZIP input is missing: {path}")
    add_zip_bytes(payloads, arcname, path.read_bytes())


def build_zip_payloads(
    context: dict[str, object], readme_data: bytes, metadata_data: bytes
) -> tuple[list[tuple[str, bytes]], list[str], dict[str, object]]:
    root = context["root"]
    assert isinstance(root, Path)
    program_root = context["program_root"]
    assert isinstance(program_root, Path)
    configure_publicization(root, program_root)
    payloads: dict[str, bytes] = {}
    excluded_raster_records: list[str] = []

    add_zip_bytes(payloads, "README.md", readme_data)
    add_zip_bytes(payloads, "publication-metadata.json", metadata_data)
    static_paths = {
        "manifest.json": root / "manifest.json",
        "compose.py": root / "compose.py",
        "build.ps1": root / "build.ps1",
        "release/make_release_r15.py": root / "release" / "make_release_r15.py",
        "qa/source-replay.json": root / "qa" / "source-replay.json",
        "qa/source-replay-verification-r15.json": root
        / "qa"
        / "source-replay-verification-r15.json",
        "qa/R15_REPAIR_BUILD_RECEIPT.json": root / "qa" / "R15_REPAIR_BUILD_RECEIPT.json",
        "qa/verify_source_replay_r15.py": root / "qa" / "verify_source_replay_r15.py",
        "qa/R15_REPAIR_PDF_MECHANICAL.json": root
        / "qa"
        / "R15_REPAIR_PDF_MECHANICAL.json",
        "qa/R15_REPAIR_VISUAL_INSPECTION.json": root
        / "qa"
        / "R15_REPAIR_VISUAL_INSPECTION.json",
        "qa/R15_REPAIR_FINAL_QA.json": root / "qa" / "R15_REPAIR_FINAL_QA.json",
        "qa/R15_GENERATED_FREEZE_REBIND.json": root
        / "qa"
        / "R15_GENERATED_FREEZE_REBIND.json",
        "qa/R15_GENERATED_FREEZE_CHAIN_AUDIT_01.json": root
        / "qa"
        / "R15_GENERATED_FREEZE_CHAIN_AUDIT_01.json",
        "qa/R15_RELEASE_EVIDENCE_CHAIN_01.json": root
        / "qa"
        / "R15_RELEASE_EVIDENCE_CHAIN_01.json",
        "qa/R15_PRE_GENERATED_FREEZE_SOURCE_REPLAY.json": root
        / "qa"
        / "R15_PRE_GENERATED_FREEZE_SOURCE_REPLAY.json",
        "qa/R15_QA_CONFIG.json": root / "qa" / "R15_QA_CONFIG.json",
        "qa/r15_qa_pipeline.py": root / "qa" / "r15_qa_pipeline.py",
    }
    for arcname, path in static_paths.items():
        add_zip_path(payloads, path, arcname)

    optional_reproducibility_files = [
        "qa/R15_REPAIR_VISUAL_PLAN.json",
        "qa/R15_REPAIR_BUILD_LAUNCH.json",
    ]
    for relative in optional_reproducibility_files:
        path = root / relative
        if path.is_file():
            add_zip_path(payloads, path, relative)

    lineage = context["lineage"]
    assert isinstance(lineage, dict)
    github_lineage_path = lineage["github_path"]
    zenodo_lineage_path = lineage["zenodo_path"]
    assert isinstance(github_lineage_path, Path)
    assert isinstance(zenodo_lineage_path, Path)
    add_zip_path(
        payloads,
        github_lineage_path,
        "lineage/GITHUB_PUBLICATION_RECEIPT_20260826_R14.json",
    )
    add_zip_path(
        payloads,
        zenodo_lineage_path,
        "lineage/ZENODO_PUBLICATION_RECEIPT_20260826_R14.json",
    )

    bound_paths = context["receipt_bound_paths"]
    assert isinstance(bound_paths, dict)
    for relative, path in sorted(bound_paths.items()):
        assert isinstance(path, Path)
        suffix = path.suffix.lower()
        if suffix in RASTER_SUFFIXES:
            excluded_raster_records.append(relative)
            continue
        if suffix == ".pdf":
            continue
        add_zip_path(payloads, path, relative)

    for suffix in (".aux", ".bbl", ".blg", ".fls", ".log", ".out", ".toc"):
        path = root / "build" / f"stacks-zh-hans-cn-partial{suffix}"
        add_zip_path(payloads, path, f"build/{path.name}")

    intake_paths = context["intake_paths"]
    assert isinstance(intake_paths, dict)
    for arcname, path in sorted(intake_paths.items()):
        assert isinstance(path, Path)
        add_zip_path(payloads, path, arcname)

    for source in sorted((root / "src").glob("*"), key=lambda value: value.name):
        if source.is_file():
            add_zip_path(payloads, source, f"src/{source.name}")

    publicization_entries = [
        PUBLICIZATION_RECORDS[name] for name in sorted(PUBLICIZATION_RECORDS)
    ]
    publicization_manifest = {
        "schema": "stacks-zh-hans-cn-publicization-manifest/v1",
        "release_id": RELEASE_ID,
        "path_policy": {
            "absolute_local_paths_forbidden": True,
            "file_uris_forbidden": True,
            "private_account_tokens_forbidden": True,
            "portable_tokens": [
                "${CANON_ROOT}",
                "${PROGRAM_ROOT}",
                "${WORKSPACE_ROOT}",
                "${TEXMF_ROOT}",
                "${MIKTEX_DATA_ROOT}",
                "${MIKTEX_CONFIG_ROOT}",
                "${USER_HOME}",
                "${WINDOWS_ROOT}",
                "${PROGRAM_FILES}",
                "${PROGRAM_FILES_X86}",
            ],
        },
        "binding_semantics": (
            "Embedded byte/hash fields retain the validated private-original identity domain. "
            "This manifest binds each original ZIP-input byte sequence to its portable public derivative."
        ),
        "record_count": len(publicization_entries),
        "changed_record_count": sum(bool(row["changed"]) for row in publicization_entries),
        "records": publicization_entries,
    }
    publicization_data = json_bytes(publicization_manifest)
    publicization_name = "evidence/PUBLICIZATION_MANIFEST.json"
    require_public_bytes_clean(publicization_data, publicization_name)
    payloads[publicization_name] = publicization_data
    publicization_record = {
        "path": publicization_name,
        "bytes": len(publicization_data),
        "sha256": sha256_bytes(publicization_data),
        "record_count": len(publicization_entries),
        "changed_record_count": publicization_manifest["changed_record_count"],
    }

    ordered = sorted(payloads.items(), key=lambda pair: pair[0])
    names = [name for name, _ in ordered]
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate release ZIP entry names")
    forbidden = [name for name in names if Path(name).suffix.lower() in RASTER_SUFFIXES]
    if forbidden:
        raise RuntimeError(f"raster files entered the source/evidence ZIP: {forbidden}")
    return ordered, sorted(set(excluded_raster_records)), publicization_record


def zip_add_bytes(archive: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname, date_time=ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def make_readme(context: dict[str, object], zip_name: str) -> str:
    chapter_count = int(context["chapter_count"])
    page_count = int(context["page_count"])
    chapter_numbers = context["chapter_numbers"]
    source_replay = context["source_replay"]
    replay_verification = context["replay_verification"]
    pdf_audit = context["pdf_audit"]
    visual_qa = context["visual_qa"]
    assert isinstance(chapter_numbers, list)
    assert isinstance(source_replay, dict)
    assert isinstance(replay_verification, dict)
    assert isinstance(pdf_audit, dict)
    assert isinstance(visual_qa, dict)
    reference = source_replay["reference_resolution"]
    fonts = pdf_audit["fonts"]
    annotations = pdf_audit["annotations"]
    extraction = pdf_audit["text_extraction"]
    contact = visual_qa["contact_sheet_evidence"]
    visual_targets = visual_qa["targeted_200dpi_evidence"]
    chapters_text = "、".join(str(number) for number in chapter_numbers)
    return f"""# Stacks Project 简体中文版（zh-Hans-CN）

这是面向中国大陆读者的阶段性累积版。版本 {VERSION} 收入 {chapter_count} 个完整译章，共 {page_count} 页 A4；它不是试译，也不是全书完成或独立中文认证声明。后续完成的章节将继续加入同一中文出版谱系。

## 当前覆盖

第 {chapters_text} 章。各章标题及其精确来源、目标字节数和 SHA-256 见 manifest.json。

## 来源与重放

英语 authority 固定为 Stacks Project 提交 {AUTHORITY_COMMIT}。累积构建验证全部 {chapter_count} 个译章的 {replay_verification['verified_input_bindings']} 个输入绑定及 {replay_verification['verified_generated_outputs']} 个生成输出；{reference['unique_targets']:,} 个唯一交叉引用目标中，{reference['internal_targets']:,} 个解析到本卷内部，{reference['permanent_tag_targets']:,} 个解析到 Stacks Project 永久标签，另有 {len(reference['manual_commit_pinned_targets'])} 个解析到提交锁定的英语源码，未解析目标为零。正文保持上游公式、标签和引用结构；疑似上游勘误保存在不渲染的 sidecar 中，不悄悄改写本书所绑定的 authority。

可编辑累积源和紧凑重放证据位于 {zip_name}。其中明确不包含逐页 PNG、联系表 JPEG 或全分辨率目标 PNG/JPEG 等大体积可再生成图像树，但保留版本化 QA 收据及其清单、摘要和有序哈希绑定。解压后可从 src/ 重建；compose.py 可重新验证全部输入绑定。

## 版式与 QA

版式采用 A4、11pt、Noto Serif CJK SC、22 mm 对称页边距和适合中文科技文献的行距。全部 {page_count} 页均已重绘并由版本化视觉 QA 收据覆盖；{contact['sheet_count']} 张联系表覆盖全部页面，另有 {visual_targets['target_count']} 个警告页、新增或修复章节页和控制页以 200 dpi 检查。未发现裁切、重叠、空白重复页、缺字方框或损坏图表。全部 {fonts['total']} 个字体已嵌入，{pdf_audit['named_destinations']['total']:,} 个命名目标和 {annotations['total']:,} 个链接注释通过机械检查。

不利证据：PDF 尚未带结构标签；{fonts['total'] - fonts['with_to_unicode']} 个旧式数学/Xy-pic 字体子集没有 ToUnicode；提取文本保留 {extraction['literal_double_question_pairs']} 处字面量双问号源占位符，但 TeX 和来源重放均无未解析引用；本版本不主张独立中文语言认证。这些限制没有阻断确定性构建、QA 或发布准备。

## 语言边界、许可与非隶属

locale 是 zh-Hans-CN，不代表新加坡简体中文，也不代表台湾、香港或澳门的繁体中文本地化。日本语版和韩语版是独立版本和独立 DOI 谱系。

原作与本衍生版依 GNU Free Documentation License 1.2 或其后版本发布，无不变章节、封面文字或封底文字；许可证全文收入 PDF。本版本与 Stacks Project 没有官方隶属或认可关系。

稳定中文概念 DOI：https://doi.org/{CONCEPT_DOI}。
"""


def make_metadata(
    context: dict[str, object], prefix: str, artifact_names: list[str]
) -> dict[str, object]:
    chapter_count = int(context["chapter_count"])
    page_count = int(context["page_count"])
    chapter_numbers = context["chapter_numbers"]
    source_replay = context["source_replay"]
    visual_qa = context["visual_qa"]
    pdf_audit = context["pdf_audit"]
    assert isinstance(chapter_numbers, list)
    assert isinstance(source_replay, dict)
    assert isinstance(visual_qa, dict)
    assert isinstance(pdf_audit, dict)
    chapters_text = "、".join(str(number) for number in chapter_numbers)
    reference = source_replay["reference_resolution"]
    fonts = pdf_audit["fonts"]
    visual_targets = visual_qa["targeted_200dpi_evidence"]
    title = f"Stacks Project 简体中文版（zh-Hans-CN）：{chapter_count} 章累积版"
    description_html = (
        f"<p><strong>{html.escape(title)}。</strong></p>"
        f"<p>本版本面向中国大陆读者，当前收录 {chapter_count} 个已经完成生产者检查和 canon 机械重放的完整译章，共 {page_count} 页 A4。"
        "它不是试译，也不是全书完成或独立中文认证声明；后续章节将继续加入同一中文出版谱系。</p>"
        f"<p><strong>覆盖范围：</strong>第 {html.escape(chapters_text)} 章。精确标题与哈希见随附清单。</p>"
        f"<p><strong>来源与方法：</strong>英语 authority 固定为 Stacks Project 提交 <code>{AUTHORITY_COMMIT}</code>。"
        f"公式、标签和引用结构均受重放检查；{reference['unique_targets']:,} 个唯一交叉引用目标全部解析。</p>"
        f"<p><strong>版式与 QA：</strong>A4、11pt、Noto Serif CJK SC、22 mm 对称页边距。全部 {page_count} 页已重绘并由版本化视觉 QA 收据覆盖；"
        f"另有 {visual_targets['target_count']} 个警告页、新增或修复章节页和控制页以 200 dpi 检查。所有字体均嵌入。"
        f"已知可访问性限制：PDF 尚未带结构标签，{fonts['total'] - fonts['with_to_unicode']} 个旧式数学/Xy-pic 字体子集没有 ToUnicode。</p>"
        "<p><strong>语言边界：</strong>locale 是 <code>zh-Hans-CN</code>，不代表新加坡简体中文，也不代表台湾、香港或澳门的繁体中文本地化。</p>"
        "<p><strong>许可与非隶属：</strong>原作与本衍生版依 GNU Free Documentation License 1.2 或其后版本发布，"
        "无不变章节、封面文字或封底文字。本版本与 Stacks Project 没有官方隶属或认可关系。</p>"
    )
    return {
        "schema": "stacks-zh-hans-cn-publication-metadata/v4",
        "release_id": RELEASE_ID,
        "version": VERSION,
        "publication_date": PUBLICATION_DATE,
        "title": title,
        "english_subtitle": (
            "Stacks Project in Mainland Simplified Chinese: "
            f"Cumulative Edition, {chapter_count} Chapters"
        ),
        "description_html": description_html,
        "authors": [
            {"name": "The Stacks Project Authors", "role": "upstream authors"},
            {
                "name": "OpenAI 5.6 Sol",
                "role": "Simplified Chinese translation producer",
            },
        ],
        "keywords": [
            "Stacks Project",
            "algebraic geometry",
            "Simplified Chinese",
            "zh-Hans-CN",
            "mathematics",
            "mathematical translation",
            "scheme theory",
            "homological algebra",
        ],
        "language": "zho",
        "license": "GNU Free Documentation License 1.2 or later",
        "authority_commit": AUTHORITY_COMMIT,
        "chapter_count": chapter_count,
        "chapters": chapter_numbers,
        "page_count": page_count,
        "status": "producer_cumulative_uncertified",
        "publication_prepared": True,
        "publication_performed": False,
        "zenodo_concept_doi": CONCEPT_DOI,
        "zenodo_expected_previous_record_id": EXPECTED_PREVIOUS_ZENODO_RECORD_ID,
        "github_repository": GITHUB_REPOSITORY,
        "github_release_tag": GITHUB_RELEASE_TAG,
        "github_expected_previous_release_tag": EXPECTED_PREVIOUS_GITHUB_RELEASE_TAG,
        "publication_policy": (
            "one cumulative Chinese lineage on each repository; "
            "Japanese and Korean are separate"
        ),
        "prefix": prefix,
        "artifact_names_in_public_order": artifact_names,
        "source_and_evidence_exclusions": [
            "**/*.png",
            "**/*.jpg",
            "**/*.jpeg",
            "qa/rendered-*",
            "qa/visual/contact-sheets-*",
            "qa/visual/full-res-*",
            "qa/visual/r15-render-*",
            "qa/visual/r15-*-contact-sheets",
            "qa/visual/r15-*-200dpi",
        ],
    }


def package_release(context: dict[str, object]) -> dict[str, object]:
    root = context["root"]
    assert isinstance(root, Path)
    release_control = root / "release" / "control-r15"
    release = root / "release" / "public-r15"
    chapter_count = int(context["chapter_count"])
    page_count = int(context["page_count"])
    prefix = (
        f"Stacks_Project_zh-Hans-CN_Cumulative_{chapter_count}_Chapters_"
        f"{PUBLICATION_DATE}"
    )
    pdf_path = release / f"00_{prefix}.pdf"
    zip_path = release / f"01_{prefix}_Source_and_Evidence.zip"
    readme_path = release / f"02_{prefix}_README.md"
    release_manifest_path = release / f"03_{prefix}_RELEASE_MANIFEST.json"
    sums_path = release / f"04_SHA256SUMS_{RELEASE_ID}.txt"
    metadata_path = release_control / "publication-metadata.json"
    artifact_names = [
        pdf_path.name,
        zip_path.name,
        readme_path.name,
        release_manifest_path.name,
        sums_path.name,
    ]
    if len(artifact_names) != PUBLIC_FILE_COUNT or len(set(artifact_names)) != PUBLIC_FILE_COUNT:
        raise RuntimeError("controlled public inventory must contain five unique files")
    if artifact_names != EXPECTED_PUBLIC_ARTIFACT_NAMES:
        raise RuntimeError("controlled public inventory differs from the R15 release contract")
    if RELEASE_ID not in sums_path.name:
        raise RuntimeError("checksum filename is not uniquely bound to the R15 release ID")

    readme_data = make_readme(context, zip_path.name).encode("utf-8")
    metadata = make_metadata(context, prefix, artifact_names)
    metadata_data = json_bytes(metadata)
    zip_payloads, excluded_raster_records, publicization_record = build_zip_payloads(
        context, readme_data, metadata_data
    )

    if release.exists():
        existing = {path.name for path in release.iterdir() if path.is_file()}
        directories = [path.name for path in release.iterdir() if path.is_dir()]
        unexpected = sorted(existing - set(EXPECTED_PUBLIC_ARTIFACT_NAMES))
        if unexpected or directories:
            raise RuntimeError(
                "R15 public staging directory is not isolated: "
                f"unexpected_files={unexpected}, directories={directories}"
            )
    release.mkdir(parents=True, exist_ok=True)
    release_control.mkdir(parents=True, exist_ok=True)
    source_pdf = context["source_pdf"]
    assert isinstance(source_pdf, Path)
    shutil.copyfile(source_pdf, pdf_path)
    if sha256(pdf_path) != context["source_pdf_sha256"]:
        raise RuntimeError("stable release PDF copy differs from the verified build PDF")
    readme_path.write_bytes(readme_data)
    metadata_path.write_bytes(metadata_data)
    with zipfile.ZipFile(zip_path, "w", allowZip64=True) as archive:
        for arcname, data in zip_payloads:
            zip_add_bytes(archive, arcname, data)
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        names = archive.namelist()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
        if names != [name for name, _ in zip_payloads]:
            raise RuntimeError("ZIP entry sequence differs from deterministic inventory")
        for name in names:
            if Path(name).suffix.lower() in RASTER_SUFFIXES:
                raise RuntimeError(f"forbidden raster evidence in ZIP: {name}")
            require_public_bytes_clean(archive.read(name), f"ZIP entry {name}")

    artifact_records = [file_record(pdf_path), file_record(zip_path), file_record(readme_path)]
    receipt_paths = context["receipt_paths"]
    assert isinstance(receipt_paths, dict)
    receipt_schemas = {}
    receipt_bindings = {}
    for label, path in sorted(receipt_paths.items()):
        assert isinstance(path, Path)
        value = load_json(path)
        receipt_schemas[label] = value["schema"]
        receipt_bindings[label] = bound_file_record(path, root)
    replay_verification = context["replay_verification"]
    visual_qa = context["visual_qa"]
    assert isinstance(replay_verification, dict)
    assert isinstance(visual_qa, dict)
    visual_targets = visual_qa["targeted_200dpi_evidence"]
    lineage = context["lineage"]
    assert isinstance(lineage, dict)
    github_lineage_path = lineage["github_path"]
    zenodo_lineage_path = lineage["zenodo_path"]
    assert isinstance(github_lineage_path, Path)
    assert isinstance(zenodo_lineage_path, Path)
    release_manifest = {
        "schema": "stacks-zh-hans-cn-release/v4",
        "release_id": RELEASE_ID,
        "version": VERSION,
        "publication_date": PUBLICATION_DATE,
        "locale": "zh-Hans-CN",
        "status": "producer_cumulative_uncertified",
        "publication_prepared": True,
        "publication_performed": False,
        "authority_commit": AUTHORITY_COMMIT,
        "zenodo_concept_doi": CONCEPT_DOI,
        "zenodo_expected_previous_record_id": EXPECTED_PREVIOUS_ZENODO_RECORD_ID,
        "github_repository": GITHUB_REPOSITORY,
        "github_release_tag": GITHUB_RELEASE_TAG,
        "github_expected_previous_release_tag": EXPECTED_PREVIOUS_GITHUB_RELEASE_TAG,
        "predecessor_lineage_receipts": {
            "github": {
                "path": "lineage/GITHUB_PUBLICATION_RECEIPT_20260826_R14.json",
                "bytes": github_lineage_path.stat().st_size,
                "sha256": sha256(github_lineage_path),
            },
            "zenodo": {
                "path": "lineage/ZENODO_PUBLICATION_RECEIPT_20260826_R14.json",
                "bytes": zenodo_lineage_path.stat().st_size,
                "sha256": sha256(zenodo_lineage_path),
            },
        },
        "chapter_count": chapter_count,
        "chapters": context["chapter_numbers"],
        "page_count": page_count,
        "source_replay_passed": True,
        "source_replay_verified_inputs": replay_verification["verified_input_bindings"],
        "source_replay_verified_outputs": replay_verification[
            "verified_generated_outputs"
        ],
        "source_replay_unresolved_targets": replay_verification[
            "unresolved_reference_targets"
        ],
        "pdf_mechanical_passed": True,
        "pdf_visual_passed": True,
        "all_pages_visually_inspected": True,
        "full_resolution_targets_inspected": visual_targets["target_count"],
        "qa_receipt_schemas": receipt_schemas,
        "qa_receipt_bindings": receipt_bindings,
        "zip_entry_count": len(zip_payloads),
        "zip_uncompressed_bytes": sum(len(data) for _, data in zip_payloads),
        "publicization_manifest": publicization_record,
        "excluded_raster_record_count": len(excluded_raster_records),
        "source_and_evidence_exclusions": metadata[
            "source_and_evidence_exclusions"
        ],
        "public_artifact_names_in_order": artifact_names,
        "checksum_scope": artifact_names[:4],
        "artifacts_preceding_release_manifest": artifact_records,
    }
    release_manifest_path.write_bytes(json_bytes(release_manifest))
    artifact_records.append(file_record(release_manifest_path))
    sums_path.write_text(
        "".join(
            f"{record['sha256']}  {record['filename']}\n"
            for record in artifact_records
        ),
        encoding="ascii",
        newline="\n",
    )
    artifact_records.append(file_record(sums_path))

    public_paths = [
        pdf_path,
        zip_path,
        readme_path,
        release_manifest_path,
        sums_path,
    ]
    actual_public_names = sorted(path.name for path in release.iterdir() if path.is_file())
    if actual_public_names != sorted(EXPECTED_PUBLIC_ARTIFACT_NAMES):
        raise RuntimeError(
            "R15 public staging inventory is not exactly the controlled five files: "
            f"{actual_public_names}"
        )
    for artifact in [*public_paths, metadata_path]:
        require_public_bytes_clean(artifact.read_bytes(), artifact.name)
    sums_lines = sums_path.read_text(encoding="ascii").splitlines()
    if len(sums_lines) != 4:
        raise RuntimeError("checksum inventory must bind the four preceding release files")
    for record, line in zip(artifact_records[:4], sums_lines, strict=True):
        if line != f"{record['sha256']}  {record['filename']}":
            raise RuntimeError("checksum inventory drift")

    return {
        "schema": "stacks-zh-hans-cn-release-build-result/v1",
        "release_directory": "release/public-r15",
        "release_id": RELEASE_ID,
        "version": VERSION,
        "github_release_tag": GITHUB_RELEASE_TAG,
        "chapter_count": chapter_count,
        "page_count": page_count,
        "zip_entry_count": len(zip_payloads),
        "zip_uncompressed_bytes": sum(len(data) for _, data in zip_payloads),
        "publication_performed": False,
        "artifacts": artifact_records,
        "publication_metadata": file_record(metadata_path),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preflight and deterministically package the zh-Hans-CN R15 release."
    )
    parser.add_argument("canon_root", type=Path)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate all release inputs without writing release artifacts",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        context = validate_preflight(args.canon_root)
    except ReleaseInputError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if args.check_only:
        prefix = (
            f"Stacks_Project_zh-Hans-CN_Cumulative_{context['chapter_count']}_Chapters_"
            f"{PUBLICATION_DATE}"
        )
        readme_data = make_readme(
            context, EXPECTED_PUBLIC_ARTIFACT_NAMES[1]
        ).encode("utf-8")
        metadata_data = json_bytes(
            make_metadata(context, prefix, EXPECTED_PUBLIC_ARTIFACT_NAMES)
        )
        try:
            zip_payloads, excluded_rasters, publicization = build_zip_payloads(
                context, readme_data, metadata_data
            )
        except (ReleaseInputError, RuntimeError) as exc:
            sys.stderr.write(f"{exc}\n")
            return 2
        result = {
            "schema": "stacks-zh-hans-cn-release-preflight/v1",
            "release_id": RELEASE_ID,
            "version": VERSION,
            "chapter_count": context["chapter_count"],
            "page_count": context["page_count"],
            "pdf_sha256": context["source_pdf_sha256"],
            "all_required_inputs_present": True,
            "packaging_dry_run_passed": True,
            "prospective_zip_entry_count": len(zip_payloads),
            "prospective_zip_uncompressed_bytes": sum(
                len(data) for _, data in zip_payloads
            ),
            "prospective_publicization_manifest": publicization,
            "excluded_raster_record_count": len(excluded_rasters),
            "packaging_performed": False,
        }
    else:
        result = package_release(context)
    sys.stdout.buffer.write(json_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
