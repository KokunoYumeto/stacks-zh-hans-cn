from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Iterator


PUBLICATION_DATE = "2026-08-26"
RELEASE_ID = "2026-08-26-r14"
VERSION = "2026.08.26-r14"
AUTHORITY_COMMIT = "a04446e57ec1fbc252a871afcec7752fb2807b14"
CONCEPT_DOI = "10.5281/zenodo.22060287"
EXPECTED_PREVIOUS_ZENODO_RECORD_ID = 22087759
EXPECTED_CHAPTERS = 112
EXPECTED_PAGES = 5546
EXPECTED_INPUT_BINDINGS = 345
EXPECTED_GENERATED_OUTPUTS = 119
ZIP_TIMESTAMP = (2026, 8, 26, 0, 0, 0)
PUBLIC_FILE_COUNT = 5
RASTER_SUFFIXES = {".jpg", ".jpeg", ".png"}

REQUIRED_QA_RECEIPTS = {
    "source replay": "qa/source-replay.json",
    "independent source-replay verification": "qa/source-replay-verification-r14.json",
    "build receipt": "qa/R14_BUILD_RECEIPT.json",
    "mechanical PDF audit": "qa/pdf-mechanical-112.json",
    "visual PDF audit": "qa/visual-qa-112.json",
    "final prepublication QA": "qa/R14_FINAL_QA.json",
}


class ReleaseInputError(RuntimeError):
    pass


def private_user_fragment() -> bytes:
    return Path.home().name.encode("utf-8")


def sanitize_public_bytes(data: bytes) -> bytes:
    fragment = private_user_fragment()
    replacements = {fragment, fragment.lower(), fragment.upper(), fragment.title()}
    for value in replacements:
        if value:
            data = data.replace(value, b"<USER>")
    return data


def require_public_bytes_clean(data: bytes, label: str) -> None:
    fragment = private_user_fragment()
    if fragment and fragment.lower() in data.lower():
        raise RuntimeError(f"private user-name fragment remains in public payload: {label}")


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
            "R14 packaging preflight failed; packaging did not start. "
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


def validate_preflight(root: Path) -> dict[str, object]:
    root = root.resolve()
    receipt_paths = require_required_receipts(root)
    manifest_path = root / "manifest.json"
    source_pdf = root / "build" / "stacks-zh-hans-cn-partial.pdf"
    static_inputs = [
        manifest_path,
        root / "compose.py",
        root / "build.ps1",
        root / "release" / "make_release_r14.py",
        root / "qa" / "verify_source_replay_r14.py",
        root / "qa" / "audit_pdf.py",
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

    require_versioned_schema(
        source_replay, "stacks-zh-hans-cn-source-replay", "source replay"
    )
    require_versioned_schema(
        replay_verification,
        "stacks-zh-hans-cn-source-replay-verification",
        "independent source-replay verification",
    )
    require_versioned_schema(
        build_receipt, "stacks-zh-hans-cn-r14-build-receipt", "build receipt"
    )
    require_versioned_schema(
        pdf_audit, "stacks-zh-hans-cn-pdf-audit", "mechanical PDF audit"
    )
    require_versioned_schema(
        visual_qa, "stacks-zh-hans-cn-visual-qa", "visual PDF audit"
    )
    require_versioned_schema(
        final_qa, "stacks-zh-hans-cn-r14-final-qa", "final prepublication QA"
    )

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
    if chapter_numbers != sorted(chapter_numbers):
        raise ReleaseInputError("release manifest chapter order is not ascending")

    if source_replay.get("passed") is not True:
        raise ReleaseInputError("source replay is not passing")
    if int(source_replay.get("chapter_count", -1)) != chapter_count:
        raise ReleaseInputError("source replay chapter count differs from the manifest")
    if str(source_replay.get("authority_commit")) != AUTHORITY_COMMIT:
        raise ReleaseInputError("source replay authority commit drift")
    reference = source_replay.get("reference_resolution") or {}
    if list(reference.get("unresolved_targets") or []):
        raise ReleaseInputError("source replay contains unresolved reference targets")

    if replay_verification.get("passed") is not True:
        raise ReleaseInputError("independent source-replay verification is not passing")
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
    }
    drift = {
        key: {"actual": actual, "expected": expected}
        for key, (actual, expected) in replay_numbers.items()
        if actual != expected
    }
    if drift:
        raise ReleaseInputError(f"source-replay verification drift: {drift}")
    validate_bound_record(
        root, replay_verification["source_replay"], "source replay verification.source_replay"
    )
    validate_bound_record(
        root, replay_verification["manifest"], "source replay verification.manifest"
    )

    if build_receipt.get("passed") is not True or str(build_receipt.get("status")) != "PASS":
        raise ReleaseInputError("R14 build receipt is not passing")
    if str(build_receipt.get("release_candidate")) != VERSION:
        raise ReleaseInputError("R14 build receipt release-candidate version drift")
    if str(build_receipt.get("authority_commit")) != AUTHORITY_COMMIT:
        raise ReleaseInputError("R14 build receipt authority drift")
    if int((build_receipt.get("source_bindings") or {}).get("chapter_count", -1)) != chapter_count:
        raise ReleaseInputError("R14 build receipt chapter-count drift")

    page_count = int(pdf_audit.get("pages", -1))
    if page_count != EXPECTED_PAGES:
        raise ReleaseInputError(f"expected {EXPECTED_PAGES} pages, got {page_count}")
    if (
        pdf_audit.get("passed_mechanical") is not True
        or int(pdf_audit.get("expected_pages", -1)) != EXPECTED_PAGES
    ):
        raise ReleaseInputError("final PDF mechanical audit is not passing")
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
        raise ReleaseInputError("R14 build receipt is bound to a different PDF")

    if visual_qa.get("passed_visual") is not True:
        raise ReleaseInputError("final PDF visual audit is not passing")
    visual_pdf = visual_qa.get("pdf") or {}
    if (
        int(visual_pdf.get("pages", -1)) != page_count
        or str(visual_pdf.get("sha256")).upper() != source_pdf_sha
    ):
        raise ReleaseInputError("visual audit is bound to a different PDF")
    if int((visual_qa.get("render_evidence") or {}).get("page_count", -1)) != page_count:
        raise ReleaseInputError("visual audit does not cover every PDF page")
    contact_page_coverage = (visual_qa.get("contact_sheet_evidence") or {}).get(
        "page_coverage"
    )
    if contact_page_coverage not in (page_count, f"1-{page_count} without gaps"):
        raise ReleaseInputError("contact-sheet evidence does not cover every PDF page")

    if final_qa.get("passed") is not True:
        raise ReleaseInputError("R14 final-QA receipt is not passing")
    if final_qa.get("publication_performed") is not False:
        raise ReleaseInputError("R14 final-QA receipt is not prepublication")
    if str(final_qa.get("release_candidate")) != VERSION:
        raise ReleaseInputError("R14 final-QA release-candidate version drift")
    if str(final_qa.get("authority_commit")) != AUTHORITY_COMMIT:
        raise ReleaseInputError("R14 final-QA authority drift")
    if int(final_qa.get("chapter_count", -1)) != chapter_count:
        raise ReleaseInputError("R14 final-QA chapter-count drift")
    final_pdf = final_qa.get("pdf") or {}
    validate_exact_bound_record(
        root,
        final_pdf,
        source_pdf,
        "R14 final-QA.pdf",
    )
    if (
        int(final_pdf.get("pages", -1)) != page_count
        or str(final_pdf.get("sha256")).upper() != source_pdf_sha
        or str(final_pdf.get("page_size")) != "A4"
    ):
        raise ReleaseInputError("R14 final-QA receipt is bound to a different PDF")

    final_build_qa = final_qa.get("build_qa") or {}
    validate_exact_bound_record(
        root,
        final_build_qa,
        receipt_paths["build receipt"],
        "R14 final-QA.build_qa",
    )
    if (
        final_build_qa.get("passed") is not True
        or str(final_build_qa.get("status")) != "PASS"
    ):
        raise ReleaseInputError("R14 final-QA build binding is not passing")

    final_mechanical_qa = final_qa.get("mechanical_qa") or {}
    validate_exact_bound_record(
        root,
        final_mechanical_qa,
        receipt_paths["mechanical PDF audit"],
        "R14 final-QA.mechanical_qa",
    )
    if final_mechanical_qa.get("passed") is not True:
        raise ReleaseInputError("R14 final-QA mechanical binding is not passing")

    final_visual_qa = final_qa.get("visual_qa") or {}
    validate_exact_bound_record(
        root,
        final_visual_qa,
        receipt_paths["visual PDF audit"],
        "R14 final-QA.visual_qa",
    )
    if final_visual_qa.get("passed") is not True:
        raise ReleaseInputError("R14 final-QA visual binding is not passing")

    final_source = final_qa.get("source") or {}
    for key, expected_path in (
        ("manifest", manifest_path),
        ("reader", root / "src" / "reader.tex"),
        ("source_replay", receipt_paths["source replay"]),
    ):
        validate_exact_bound_record(
            root,
            final_source.get(key) or {},
            expected_path,
            f"R14 final-QA.source.{key}",
        )
    validate_exact_bound_record(
        root,
        final_qa.get("source_replay_verification") or {},
        receipt_paths["independent source-replay verification"],
        "R14 final-QA.source_replay_verification",
    )

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
        ("final QA", final_qa),
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
    }


def add_zip_bytes(payloads: dict[str, bytes], arcname: str, data: bytes) -> None:
    normalized = Path(arcname).as_posix()
    if normalized.startswith("/") or ".." in Path(normalized).parts:
        raise RuntimeError(f"unsafe release ZIP entry name: {arcname}")
    if Path(normalized).suffix.lower() in RASTER_SUFFIXES:
        raise RuntimeError(f"raster render/contact evidence must not enter release ZIP: {arcname}")
    public_data = sanitize_public_bytes(data)
    require_public_bytes_clean(public_data, normalized)
    previous = payloads.get(normalized)
    if previous is not None and previous != public_data:
        raise RuntimeError(f"conflicting duplicate release ZIP entry: {normalized}")
    payloads[normalized] = public_data


def add_zip_path(payloads: dict[str, bytes], path: Path, arcname: str) -> None:
    if not path.is_file():
        raise ReleaseInputError(f"release ZIP input is missing: {path}")
    add_zip_bytes(payloads, arcname, path.read_bytes())


def build_zip_payloads(
    context: dict[str, object], readme_data: bytes, metadata_data: bytes
) -> tuple[list[tuple[str, bytes]], list[str]]:
    root = context["root"]
    assert isinstance(root, Path)
    payloads: dict[str, bytes] = {}
    excluded_raster_records: list[str] = []

    add_zip_bytes(payloads, "README.md", readme_data)
    add_zip_bytes(payloads, "publication-metadata.json", metadata_data)
    static_paths = {
        "manifest.json": root / "manifest.json",
        "compose.py": root / "compose.py",
        "build.ps1": root / "build.ps1",
        "release/make_release_r14.py": root / "release" / "make_release_r14.py",
        "qa/source-replay.json": root / "qa" / "source-replay.json",
        "qa/source-replay-verification-r14.json": root
        / "qa"
        / "source-replay-verification-r14.json",
        "qa/R14_BUILD_RECEIPT.json": root / "qa" / "R14_BUILD_RECEIPT.json",
        "qa/verify_source_replay_r14.py": root / "qa" / "verify_source_replay_r14.py",
        "qa/pdf-mechanical-112.json": root / "qa" / "pdf-mechanical-112.json",
        "qa/audit_pdf.py": root / "qa" / "audit_pdf.py",
        "qa/visual-qa-112.json": root / "qa" / "visual-qa-112.json",
        "qa/R14_FINAL_QA.json": root / "qa" / "R14_FINAL_QA.json",
    }
    for arcname, path in static_paths.items():
        add_zip_path(payloads, path, arcname)

    optional_reproducibility_files = [
        "qa/pdffonts-112.txt",
        "qa/create_visual_qa_112.py",
        "qa/prepare_visual_targets_r14.py",
        "qa/audit_full_res_targets_r14.py",
        "qa/create_final_qa_r14.py",
        "qa/audit_renders.py",
        "qa/make_contact_sheets.py",
    ]
    for relative in optional_reproducibility_files:
        path = root / relative
        if path.is_file():
            add_zip_path(payloads, path, relative)

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

    ordered = sorted(payloads.items(), key=lambda pair: pair[0])
    names = [name for name, _ in ordered]
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate release ZIP entry names")
    forbidden = [name for name in names if Path(name).suffix.lower() in RASTER_SUFFIXES]
    if forbidden:
        raise RuntimeError(f"raster files entered the source/evidence ZIP: {forbidden}")
    return ordered, sorted(set(excluded_raster_records))


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
    visual_targets = visual_qa["full_resolution_evidence"]
    chapters_text = "、".join(str(number) for number in chapter_numbers)
    return f"""# Stacks Project 简体中文版（zh-Hans-CN）

这是面向中国大陆读者的阶段性累积版。版本 {VERSION} 收入 {chapter_count} 个完整译章，共 {page_count} 页 A4；它不是试译，也不是全书完成或独立中文认证声明。后续完成的章节将继续加入同一中文出版谱系。

## 当前覆盖

第 {chapters_text} 章。各章标题及其精确来源、目标字节数和 SHA-256 见 manifest.json。

## 来源与重放

英语 authority 固定为 Stacks Project 提交 {AUTHORITY_COMMIT}。累积构建验证全部 {chapter_count} 个译章的 {replay_verification['verified_input_bindings']} 个输入绑定及 {replay_verification['verified_generated_outputs']} 个生成输出；{reference['unique_targets']:,} 个唯一交叉引用目标中，{reference['internal_targets']:,} 个解析到本卷内部，{reference['permanent_tag_targets']:,} 个解析到 Stacks Project 永久标签，另有 {len(reference['manual_commit_pinned_targets'])} 个解析到提交锁定的英语源码，未解析目标为零。正文保持上游公式、标签和引用结构；疑似上游勘误保存在不渲染的 sidecar 中，不悄悄改写本书所绑定的 authority。

可编辑累积源和紧凑重放证据位于 {zip_name}。其中明确不包含逐页 PNG、联系表 JPEG 或全分辨率目标 PNG/JPEG 等大体积可再生成图像树，但保留版本化 QA 收据及其清单、摘要和有序哈希绑定。解压后可从 src/ 重建；compose.py 可重新验证全部输入绑定。

## 版式与 QA

版式采用 A4、11pt、Noto Serif CJK SC、22 mm 对称页边距和适合中文科技文献的行距。全部 {page_count} 页均已重绘并由版本化视觉 QA 收据覆盖；{contact['count']} 张联系表覆盖全部页面，另有 {visual_targets['target_count']} 个警告页、新增章节边界页和控制页以全分辨率检查。未发现裁切、重叠、空白重复页、缺字方框或损坏图表。全部 {fonts['total']} 个字体已嵌入，{pdf_audit['named_destinations']:,} 个命名目标和 {annotations['total']:,} 个链接注释通过机械检查。

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
    visual_targets = visual_qa["full_resolution_evidence"]
    title = f"Stacks Project 简体中文版（zh-Hans-CN）：{chapter_count} 章累积版"
    description_html = (
        f"<p><strong>{html.escape(title)}。</strong></p>"
        f"<p>本版本面向中国大陆读者，当前收录 {chapter_count} 个已经完成生产者检查和 canon 机械重放的完整译章，共 {page_count} 页 A4。"
        "它不是试译，也不是全书完成或独立中文认证声明；后续章节将继续加入同一中文出版谱系。</p>"
        f"<p><strong>覆盖范围：</strong>第 {html.escape(chapters_text)} 章。精确标题与哈希见随附清单。</p>"
        f"<p><strong>来源与方法：</strong>英语 authority 固定为 Stacks Project 提交 <code>{AUTHORITY_COMMIT}</code>。"
        f"公式、标签和引用结构均受重放检查；{reference['unique_targets']:,} 个唯一交叉引用目标全部解析。</p>"
        f"<p><strong>版式与 QA：</strong>A4、11pt、Noto Serif CJK SC、22 mm 对称页边距。全部 {page_count} 页已重绘并由版本化视觉 QA 收据覆盖；"
        f"另有 {visual_targets['target_count']} 个警告页、新增章节边界页和控制页以全分辨率检查。所有字体均嵌入。"
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
        ],
    }


def package_release(context: dict[str, object]) -> dict[str, object]:
    root = context["root"]
    assert isinstance(root, Path)
    release = root / "release"
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
    metadata_path = release / "publication-metadata.json"
    artifact_names = [
        pdf_path.name,
        zip_path.name,
        readme_path.name,
        release_manifest_path.name,
        sums_path.name,
    ]
    if len(artifact_names) != PUBLIC_FILE_COUNT or len(set(artifact_names)) != PUBLIC_FILE_COUNT:
        raise RuntimeError("controlled public inventory must contain five unique files")
    if RELEASE_ID not in sums_path.name:
        raise RuntimeError("checksum filename is not uniquely bound to the R14 release ID")

    readme_data = make_readme(context, zip_path.name).encode("utf-8")
    metadata = make_metadata(context, prefix, artifact_names)
    metadata_data = json_bytes(metadata)
    zip_payloads, excluded_raster_records = build_zip_payloads(
        context, readme_data, metadata_data
    )

    release.mkdir(parents=True, exist_ok=True)
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
    visual_targets = visual_qa["full_resolution_evidence"]
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
        "release_directory": str(release),
        "release_id": RELEASE_ID,
        "version": VERSION,
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
        description="Preflight and deterministically package the zh-Hans-CN R14 release."
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
        result = {
            "schema": "stacks-zh-hans-cn-release-preflight/v1",
            "release_id": RELEASE_ID,
            "version": VERSION,
            "chapter_count": context["chapter_count"],
            "page_count": context["page_count"],
            "pdf_sha256": context["source_pdf_sha256"],
            "all_required_inputs_present": True,
            "packaging_performed": False,
        }
    else:
        result = package_release(context)
    sys.stdout.buffer.write(json_bytes(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
