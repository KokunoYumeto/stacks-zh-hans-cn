from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PROGRAM_ROOT = ROOT.parent.parent
MANIFEST = ROOT / "manifest.json"
REPLAY = ROOT / "qa" / "source-replay.json"
FREEZE_REBIND = ROOT / "qa" / "R15_GENERATED_FREEZE_REBIND.json"
FREEZE_CHAIN_AUDIT = ROOT / "qa" / "R15_GENERATED_FREEZE_CHAIN_AUDIT_01.json"
PRE_FREEZE_REPLAY = ROOT / "qa" / "R15_PRE_GENERATED_FREEZE_SOURCE_REPLAY.json"
OUT = ROOT / "qa" / "source-replay-verification-r15.json"

EXPECTED_REPLAY_SCHEMA = "stacks-zh-hans-cn-source-replay/v1"
EXPECTED_MANIFEST_SCHEMA = "stacks-zh-hans-cn-cumulative/v1"
EXPECTED_AUTHORITY_COMMIT = "a04446e57ec1fbc252a871afcec7752fb2807b14"
EXPECTED_CHAPTERS = 116
EXPECTED_INPUT_BINDINGS = 360
EXPECTED_OUTPUTS = 123
EXPECTED_UNIQUE_REFERENCE_TARGETS = 16_745
EXPECTED_RELEASE_CANDIDATE = "2026.08.30-r15"
EXPECTED_FREEZE_REBIND_SCHEMA = "stacks_zh_hans_cn_r15_generated_freeze_rebind/v1"
EXPECTED_FREEZE_CHAIN_SCHEMA = "stacks_zh_hans_cn_r15_generated_freeze_chain_audit/v1"


class VerificationError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise VerificationError(f"required input is missing: {path}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"expected a JSON object: {path}")
    return value


def require_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise VerificationError(f"{label} must be an array")
    return value


def within_program_root(path: Path) -> bool:
    resolved = path.resolve()
    program_root = PROGRAM_ROOT.resolve()
    return resolved == program_root or program_root in resolved.parents


def resolve_record_path(recorded: object, label: str) -> Path:
    if not isinstance(recorded, str) or not recorded:
        raise VerificationError(f"{label} has no path")
    candidate = Path(recorded)
    if candidate.is_absolute():
        path = candidate.resolve()
    else:
        candidates = {(ROOT / candidate).resolve(), (PROGRAM_ROOT / candidate).resolve()}
        existing = [value for value in candidates if value.is_file()]
        if len(existing) != 1:
            raise VerificationError(
                f"{label} relative path is missing or ambiguous: {recorded}"
            )
        path = existing[0]
    if not within_program_root(path):
        raise VerificationError(f"{label} escapes the bounded program root: {recorded}")
    return path


def portable_path(path: Path) -> str:
    return path.resolve().relative_to(PROGRAM_ROOT.resolve()).as_posix()


def verify_record(record: object, label: str) -> tuple[Path, dict[str, object]]:
    value = require_object(record, label)
    path = resolve_record_path(value.get("path"), label)
    if not path.is_file():
        raise VerificationError(f"{label} is missing: {path}")
    try:
        expected_bytes = int(value["bytes"])
        expected_sha256 = str(value["sha256"]).upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError(f"{label} lacks a complete byte/hash binding") from exc
    if len(expected_sha256) != 64 or any(
        char not in "0123456789ABCDEF" for char in expected_sha256
    ):
        raise VerificationError(f"{label} has an invalid SHA-256 value")
    actual_bytes = path.stat().st_size
    actual_sha256 = sha256(path)
    if actual_bytes != expected_bytes or actual_sha256 != expected_sha256:
        raise VerificationError(
            f"{label} binding drift at {portable_path(path)}: "
            f"expected {expected_bytes}/{expected_sha256}, "
            f"found {actual_bytes}/{actual_sha256}"
        )
    return path, {
        "path": portable_path(path),
        "bytes": actual_bytes,
        "sha256": actual_sha256,
    }


def ordered_binding_sha256(records: list[object], label: str) -> tuple[str, list[dict[str, object]]]:
    digest = hashlib.sha256()
    verified: list[dict[str, object]] = []
    for index, record in enumerate(records, start=1):
        path, portable = verify_record(record, f"{label} {index}")
        verified.append(portable)
        digest.update(
            (
                f"{index}\t{portable_path(path)}\t{portable['bytes']}\t"
                f"{portable['sha256']}\n"
            ).encode("utf-8")
        )
    return digest.hexdigest().upper(), verified


def record_identity(record: object, label: str) -> tuple[Path, int, str]:
    value = require_object(record, label)
    path = resolve_record_path(value.get("path"), label)
    try:
        return path, int(value["bytes"]), str(value["sha256"]).upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError(f"{label} lacks a complete identity") from exc


def atomic_write_json(path: Path, value: object) -> None:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def audit_record_identity(record: object, label: str) -> tuple[Path, int, str]:
    value = require_object(record, label)
    bases = {
        "workspace": PROGRAM_ROOT,
        "canon_root": ROOT.parent,
        "r15_root": ROOT,
    }
    base_name = str(value.get("path_base") or "")
    if base_name not in bases:
        raise VerificationError(f"{label} has an unknown path_base: {base_name!r}")
    relative = Path(str(value.get("path") or ""))
    if not str(relative) or relative.is_absolute():
        raise VerificationError(f"{label} path is blank or absolute")
    path = (bases[base_name] / relative).resolve()
    if not within_program_root(path):
        raise VerificationError(f"{label} escapes the bounded program root")
    try:
        return path, int(value["bytes"]), str(value["sha256"]).upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise VerificationError(f"{label} lacks a complete byte/hash identity") from exc


def verify_audit_record(record: object, label: str) -> tuple[Path, dict[str, object]]:
    path, expected_bytes, expected_sha256 = audit_record_identity(record, label)
    if not path.is_file():
        raise VerificationError(f"{label} is missing: {path}")
    actual_bytes = path.stat().st_size
    actual_sha256 = sha256(path)
    if actual_bytes != expected_bytes or actual_sha256 != expected_sha256:
        raise VerificationError(
            f"{label} binding drift: expected {expected_bytes}/{expected_sha256}, "
            f"found {actual_bytes}/{actual_sha256}"
        )
    return path, {
        "path": portable_path(path),
        "bytes": actual_bytes,
        "sha256": actual_sha256,
    }


def verify_generated_freeze_chain(
    current_replay: dict[str, Any],
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    rebind = load_object(FREEZE_REBIND)
    audit = load_object(FREEZE_CHAIN_AUDIT)
    if rebind.get("schema") != EXPECTED_FREEZE_REBIND_SCHEMA:
        raise VerificationError("generated-freeze predecessor schema drift")
    if rebind.get("status") != "PASS":
        raise VerificationError("generated-freeze predecessor is not PASS")
    if rebind.get("release_candidate") != EXPECTED_RELEASE_CANDIDATE:
        raise VerificationError("generated-freeze predecessor release-candidate drift")
    if rebind.get("authority_commit") != EXPECTED_AUTHORITY_COMMIT:
        raise VerificationError("generated-freeze predecessor authority drift")
    if rebind.get("locale") != "zh-Hans-CN":
        raise VerificationError("generated-freeze predecessor locale drift")
    if audit.get("schema") != EXPECTED_FREEZE_CHAIN_SCHEMA:
        raise VerificationError("generated-freeze chain-audit schema drift")
    if audit.get("status") != "PASS_WITH_APPEND_ONLY_CORRECTIONS" or audit.get("passed") is not True:
        raise VerificationError("generated-freeze chain audit is not passing")
    if audit.get("release_candidate") != EXPECTED_RELEASE_CANDIDATE:
        raise VerificationError("generated-freeze chain-audit release-candidate drift")
    for key in ("authority_mutated", "producer_target_mutated_by_canon"):
        if audit.get(key) is not False:
            raise VerificationError(f"generated-freeze chain mutation flag drift: {key}")
    immutability = require_object(rebind.get("immutability"), "generated-freeze immutability")
    for key in (
        "authority_mutated",
        "producer_target_mutated_by_canon",
        "completed_pdf_mutated",
        "predecessor_source_replay_mutated",
    ):
        if immutability.get(key) is not False:
            raise VerificationError(f"generated-freeze immutability flag drift: {key}")

    predecessor_path, predecessor_record = verify_record(
        audit.get("predecessor_rebind"), "generated-freeze chain predecessor"
    )
    if predecessor_path != FREEZE_REBIND.resolve():
        raise VerificationError("generated-freeze chain binds an unexpected predecessor")
    predecessor_binding = require_object(
        audit.get("predecessor_rebind"), "generated-freeze chain predecessor"
    )
    if predecessor_binding.get("preserved_unchanged") is not True:
        raise VerificationError("generated-freeze predecessor is not preserved unchanged")

    predecessor = require_object(rebind.get("predecessor"), "generated-freeze predecessor")
    predecessor_replay_path, _ = verify_record(
        predecessor.get("source_replay"), "generated-freeze predecessor source replay"
    )
    if predecessor_replay_path != PRE_FREEZE_REPLAY.resolve():
        raise VerificationError("generated-freeze predecessor replay path drift")
    predecessor_replay = load_object(PRE_FREEZE_REPLAY)
    if predecessor_replay.get("schema") != EXPECTED_REPLAY_SCHEMA or predecessor_replay.get("passed") is not True:
        raise VerificationError("generated-freeze predecessor replay schema/status drift")
    predecessor_manifest = require_object(predecessor.get("manifest"), "generated-freeze predecessor manifest")
    predecessor_replay_manifest = require_object(
        predecessor_replay.get("manifest"), "generated-freeze predecessor replay manifest"
    )
    if (
        int(predecessor_manifest.get("bytes", -1))
        != int(predecessor_replay_manifest.get("bytes", -2))
        or str(predecessor_manifest.get("sha256", "")).upper()
        != str(predecessor_replay_manifest.get("sha256", "")).upper()
    ):
        raise VerificationError("generated-freeze historical manifest identity drift")

    corrections = require_object(
        audit.get("append_only_corrections"), "generated-freeze append-only corrections"
    )
    if (
        int(corrections.get("changed_input_bindings", -1)) != 2
        or [int(value) for value in require_list(corrections.get("changed_input_ordinals"), "changed input ordinals")] != [183, 184]
        or int(corrections.get("unchanged_input_bindings", -1)) != 358
    ):
        raise VerificationError("generated-freeze append-only correction counts drift")
    if int(corrections.get("changed_input_bindings", -1)) + int(corrections.get("unchanged_input_bindings", -1)) != EXPECTED_INPUT_BINDINGS:
        raise VerificationError("generated-freeze correction totals do not equal all inputs")
    changed_records = require_list(audit.get("changed_records"), "generated-freeze changed records")
    if [int(require_object(value, "changed record").get("ordinal", -1)) for value in changed_records] != [183, 184]:
        raise VerificationError("generated-freeze changed-record order drift")
    predecessor_inputs = require_list(
        predecessor_replay.get("verified_inputs"), "generated-freeze predecessor inputs"
    )
    current_inputs = require_list(current_replay.get("verified_inputs"), "generated-freeze current inputs")
    if len(predecessor_inputs) != EXPECTED_INPUT_BINDINGS or len(current_inputs) != EXPECTED_INPUT_BINDINGS:
        raise VerificationError("generated-freeze replay input-count drift")
    actual_changed_ordinals = [
        index
        for index, (before, after) in enumerate(zip(predecessor_inputs, current_inputs, strict=True), start=1)
        if record_identity(before, f"predecessor input {index}")
        != record_identity(after, f"current input {index}")
    ]
    if actual_changed_ordinals != [183, 184]:
        raise VerificationError(
            f"generated-freeze actual changed ordinals drift: {actual_changed_ordinals}"
        )
    for raw in changed_records:
        record = require_object(raw, "generated-freeze changed record")
        ordinal = int(record["ordinal"])
        before = require_object(record.get("before"), "generated-freeze changed record before")
        after = require_object(record.get("after"), "generated-freeze changed record after")
        if audit_record_identity(before, f"generated-freeze changed record {ordinal} before") != record_identity(
            predecessor_inputs[ordinal - 1], f"generated-freeze predecessor input {ordinal}"
        ):
            raise VerificationError(f"generated-freeze changed record {ordinal} before mismatch")
        if audit_record_identity(after, f"generated-freeze changed record {ordinal} after") != record_identity(
            current_inputs[ordinal - 1], f"generated-freeze current input {ordinal}"
        ):
            raise VerificationError(f"generated-freeze changed record {ordinal} after mismatch")
        verify_audit_record(after, f"generated-freeze changed record {ordinal} after")

    predecessor_outputs = require_list(
        predecessor_replay.get("generated_outputs"), "generated-freeze predecessor outputs"
    )
    current_outputs = require_list(
        current_replay.get("generated_outputs"), "generated-freeze current outputs"
    )
    if len(predecessor_outputs) != EXPECTED_OUTPUTS or len(current_outputs) != EXPECTED_OUTPUTS:
        raise VerificationError("generated-freeze output-count drift")
    output_differences = sum(
        record_identity(before, f"predecessor output {index}")
        != record_identity(after, f"current output {index}")
        for index, (before, after) in enumerate(
            zip(predecessor_outputs, current_outputs, strict=True), start=1
        )
    )
    if output_differences != 0:
        raise VerificationError("generated-freeze output identities differ")
    predecessor_references = require_object(
        predecessor_replay.get("reference_resolution"), "generated-freeze predecessor references"
    )
    current_references = require_object(
        current_replay.get("reference_resolution"), "generated-freeze current references"
    )
    if (
        int(predecessor_references.get("unique_targets", -1)) != EXPECTED_UNIQUE_REFERENCE_TARGETS
        or int(current_references.get("unique_targets", -1)) != EXPECTED_UNIQUE_REFERENCE_TARGETS
        or require_list(current_references.get("unresolved_targets"), "current unresolved targets")
    ):
        raise VerificationError("generated-freeze reference-resolution drift")

    effective = require_object(audit.get("effective_successor"), "generated-freeze effective successor")
    manifest_path, _ = verify_audit_record(effective.get("manifest"), "generated-freeze effective manifest")
    replay_path, _ = verify_audit_record(effective.get("source_replay"), "generated-freeze effective source replay")
    if manifest_path != MANIFEST.resolve() or replay_path != REPLAY.resolve():
        raise VerificationError("generated-freeze effective successor points to unexpected files")
    if (
        int(effective.get("verified_inputs", -1)) != EXPECTED_INPUT_BINDINGS
        or int(effective.get("generated_outputs", -1)) != EXPECTED_OUTPUTS
        or int(effective.get("generated_output_path_byte_hash_differences_from_predecessor", -1)) != 0
        or int(effective.get("unique_reference_targets", -1)) != EXPECTED_UNIQUE_REFERENCE_TARGETS
        or int(effective.get("unresolved_reference_targets", -1)) != 0
        or effective.get("full_rehash_preflight") != "PASS"
    ):
        raise VerificationError("generated-freeze effective-successor counts drift")

    successor = require_object(rebind.get("successor"), "generated-freeze predecessor successor")
    for key, expected in (("manifest", MANIFEST), ("source_replay", REPLAY)):
        path, _ = verify_record(successor.get(key), f"generated-freeze predecessor successor {key}")
        if path != expected.resolve():
            raise VerificationError(f"generated-freeze predecessor successor {key} path drift")
    comparison = require_object(rebind.get("replay_comparison"), "generated-freeze replay comparison")
    if (
        int(comparison.get("verified_inputs_before", -1)) != EXPECTED_INPUT_BINDINGS
        or int(comparison.get("verified_inputs_after", -1)) != EXPECTED_INPUT_BINDINGS
        or int(comparison.get("generated_outputs_before", -1)) != EXPECTED_OUTPUTS
        or int(comparison.get("generated_outputs_after", -1)) != EXPECTED_OUTPUTS
        or int(comparison.get("generated_output_path_byte_hash_differences", -1)) != 0
        or int(comparison.get("unique_reference_targets_after", -1)) != EXPECTED_UNIQUE_REFERENCE_TARGETS
        or int(comparison.get("unresolved_reference_targets_after", -1)) != 0
    ):
        raise VerificationError("generated-freeze predecessor replay-comparison drift")
    predecessor_record["path"] = "qa/R15_GENERATED_FREEZE_REBIND.json"
    return predecessor_record, {
        "path": "qa/R15_GENERATED_FREEZE_CHAIN_AUDIT_01.json",
        "bytes": FREEZE_CHAIN_AUDIT.stat().st_size,
        "sha256": sha256(FREEZE_CHAIN_AUDIT),
    }, {
        "predecessor_source_replay": {
            "path": "qa/R15_PRE_GENERATED_FREEZE_SOURCE_REPLAY.json",
            "bytes": PRE_FREEZE_REPLAY.stat().st_size,
            "sha256": sha256(PRE_FREEZE_REPLAY),
        },
        "changed_input_ordinals": actual_changed_ordinals,
        "changed_input_bindings": 2,
        "unchanged_input_bindings": 358,
        "generated_output_differences": output_differences,
        "passed": True,
    }


def main() -> int:
    replay = load_object(REPLAY)
    manifest = load_object(MANIFEST)
    verified_freeze_rebind, verified_freeze_chain, freeze_chain_summary = verify_generated_freeze_chain(replay)
    if replay.get("schema") != EXPECTED_REPLAY_SCHEMA:
        raise VerificationError("source replay schema drift")
    if replay.get("passed") is not True:
        raise VerificationError("source replay receipt is not passing")
    if manifest.get("schema") != EXPECTED_MANIFEST_SCHEMA:
        raise VerificationError("manifest schema drift")

    authority = require_object(manifest.get("authority"), "manifest.authority")
    if authority.get("commit") != EXPECTED_AUTHORITY_COMMIT:
        raise VerificationError("manifest authority commit drift")
    if replay.get("authority_commit") != EXPECTED_AUTHORITY_COMMIT:
        raise VerificationError("source replay authority commit drift")

    manifest_binding_path, verified_manifest = verify_record(
        replay.get("manifest"), "source replay manifest"
    )
    if manifest_binding_path != MANIFEST.resolve():
        raise VerificationError("source replay binds an unexpected manifest")

    manifest_chapters = require_list(manifest.get("chapters"), "manifest.chapters")
    replay_chapters = require_list(replay.get("chapters"), "source replay chapters")
    expected_numbers = list(range(1, EXPECTED_CHAPTERS + 1))
    manifest_numbers = [
        int(require_object(value, f"manifest chapter {index}").get("chapter", -1))
        for index, value in enumerate(manifest_chapters, start=1)
    ]
    replay_numbers = [
        int(require_object(value, f"replay chapter {index}").get("chapter", -1))
        for index, value in enumerate(replay_chapters, start=1)
    ]
    if manifest_numbers != expected_numbers or replay_numbers != expected_numbers:
        raise VerificationError("manifest/replay chapter sequence is not exactly 1 through 116")
    if int(replay.get("chapter_count", -1)) != EXPECTED_CHAPTERS:
        raise VerificationError("source replay chapter-count drift")

    manifest_by_stem: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(manifest_chapters, start=1):
        chapter = require_object(raw, f"manifest chapter {index}")
        stem = str(chapter.get("stem") or "")
        if not stem or stem in manifest_by_stem:
            raise VerificationError(f"manifest has a blank or duplicate stem at chapter {index}")
        manifest_by_stem[stem] = chapter

    inputs = require_list(replay.get("verified_inputs"), "source replay verified_inputs")
    outputs = require_list(replay.get("generated_outputs"), "source replay generated_outputs")
    if len(inputs) != EXPECTED_INPUT_BINDINGS:
        raise VerificationError("source replay input-binding count drift")
    if len(outputs) != EXPECTED_OUTPUTS:
        raise VerificationError("source replay generated-output count drift")
    ordered_inputs, _ = ordered_binding_sha256(inputs, "input binding")
    ordered_outputs, verified_outputs = ordered_binding_sha256(outputs, "output binding")

    output_identities = {
        (Path(str(record["path"])), int(record["bytes"]), str(record["sha256"]).upper())
        for record in verified_outputs
    }
    replay_stems: set[str] = set()
    for index, raw in enumerate(replay_chapters, start=1):
        chapter = require_object(raw, f"replay chapter {index}")
        stem = str(chapter.get("stem") or "")
        if not stem or stem in replay_stems or stem not in manifest_by_stem:
            raise VerificationError(f"replay has a blank, duplicate, or unknown stem at chapter {index}")
        replay_stems.add(stem)
        manifest_chapter = manifest_by_stem[stem]
        if (
            int(chapter.get("chapter", -1)) != int(manifest_chapter.get("chapter", -2))
            or str(chapter.get("title")) != str(manifest_chapter.get("title"))
        ):
            raise VerificationError(f"replay/manifest chapter identity drift for {stem}")
        output_path, output_bytes, output_sha = record_identity(
            chapter.get("output"), f"replay chapter {stem} output"
        )
        portable_identity = (Path(portable_path(output_path)), output_bytes, output_sha)
        if portable_identity not in output_identities:
            raise VerificationError(f"replay chapter {stem} output is absent from generated_outputs")
    if replay_stems != set(manifest_by_stem):
        raise VerificationError("replay and manifest chapter stem sets differ")

    references = require_object(
        replay.get("reference_resolution"), "source replay reference_resolution"
    )
    if int(references.get("unique_targets", -1)) != EXPECTED_UNIQUE_REFERENCE_TARGETS:
        raise VerificationError("source replay unique-reference-target count drift")
    unresolved = require_list(references.get("unresolved_targets"), "unresolved targets")
    if unresolved:
        raise VerificationError(f"source replay retains unresolved targets: {unresolved[:10]}")
    internal = int(references.get("internal_targets", -1))
    permanent = int(references.get("permanent_tag_targets", -1))
    manual = require_list(
        references.get("manual_commit_pinned_targets"), "manual commit-pinned targets"
    )
    if internal < 0 or permanent < 0 or internal + permanent + len(manual) != EXPECTED_UNIQUE_REFERENCE_TARGETS:
        raise VerificationError("reference-resolution category totals do not equal unique targets")

    result = {
        "schema": "stacks-zh-hans-cn-source-replay-verification/v2",
        "expected_source_replay_schema": EXPECTED_REPLAY_SCHEMA,
        "authority_commit": EXPECTED_AUTHORITY_COMMIT,
        "source_replay": {
            "path": "qa/source-replay.json",
            "bytes": REPLAY.stat().st_size,
            "sha256": sha256(REPLAY),
        },
        "manifest": {
            "path": "manifest.json",
            "bytes": verified_manifest["bytes"],
            "sha256": verified_manifest["sha256"],
        },
        "generated_freeze_rebind": verified_freeze_rebind,
        "generated_freeze_chain_audit": verified_freeze_chain,
        "generated_freeze_chain_summary": freeze_chain_summary,
        "chapter_count": EXPECTED_CHAPTERS,
        "verified_input_bindings": EXPECTED_INPUT_BINDINGS,
        "verified_generated_outputs": EXPECTED_OUTPUTS,
        "unique_reference_targets": EXPECTED_UNIQUE_REFERENCE_TARGETS,
        "unresolved_reference_targets": 0,
        "ordered_input_binding_sha256": ordered_inputs,
        "ordered_output_binding_sha256": ordered_outputs,
        "hashes_derived_at_verification_time": True,
        "passed": True,
    }
    atomic_write_json(OUT, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
