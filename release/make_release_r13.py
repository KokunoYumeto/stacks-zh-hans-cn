from __future__ import annotations

import hashlib
import html
import json
import shutil
import sys
import zipfile
from pathlib import Path


PUBLICATION_DATE = "2026-08-25"
VERSION = "2026.08.25-r13"
AUTHORITY_COMMIT = "a04446e57ec1fbc252a871afcec7752fb2807b14"
CONCEPT_DOI = "10.5281/zenodo.22060287"
EXPECTED_CHAPTERS = 105
EXPECTED_PAGES = 4877
EXPECTED_PDF_SHA256 = "8C54DFF495B1642EB94828B192FFDF8A49A157E80FFE3CECC997356DB79A28FD"


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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def file_record(path: Path) -> dict[str, object]:
    return {"filename": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def zip_add_bytes(archive: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname, date_time=(2026, 8, 25, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def resolve_program_path(program_root: Path, relative: str) -> Path:
    path = (program_root / relative.replace("/", "\\")).resolve()
    if program_root != path and program_root not in path.parents:
        raise RuntimeError(f"release input escapes program root: {relative}")
    return path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: make_release_r13.py CANON_ROOT")
    root = Path(sys.argv[1]).resolve()
    program_root = root.parent.parent
    release = root / "release"
    release.mkdir(parents=True, exist_ok=True)

    manifest = load_json(root / "manifest.json")
    source_replay = load_json(root / "qa" / "source-replay.json")
    replay_verification_path = root / "qa" / "source-replay-verification-r13.json"
    replay_verification = load_json(replay_verification_path)
    pdf_audit_path = root / "qa" / "pdf-mechanical-105.json"
    visual_qa_path = root / "qa" / "visual-qa-105.json"
    final_qa_path = root / "qa" / "R13_FINAL_QA.json"
    pdf_audit = load_json(pdf_audit_path)
    visual_qa = load_json(visual_qa_path)
    final_qa = load_json(final_qa_path)
    chapters = list(manifest["chapters"])
    chapter_count = len(chapters)
    page_count = int(pdf_audit["pages"])
    chapter_numbers = [int(chapter["chapter"]) for chapter in chapters]

    if manifest["authority"]["commit"] != AUTHORITY_COMMIT:
        raise RuntimeError("release manifest authority drift")
    if chapter_count != EXPECTED_CHAPTERS:
        raise RuntimeError(f"expected {EXPECTED_CHAPTERS} chapters, got {chapter_count}")
    if page_count != EXPECTED_PAGES:
        raise RuntimeError(f"expected {EXPECTED_PAGES} pages, got {page_count}")
    if source_replay.get("passed") is not True or int(source_replay["chapter_count"]) != chapter_count:
        raise RuntimeError("source replay is not a passing replay of every admitted chapter")
    if replay_verification.get("passed") is not True or int(replay_verification["verified_input_bindings"]) != 324:
        raise RuntimeError("independent source-replay verification is not passing")
    if int(replay_verification["unresolved_reference_targets"]) != 0:
        raise RuntimeError("unresolved source-reference targets remain")
    if pdf_audit.get("passed_mechanical") is not True or int(pdf_audit["expected_pages"]) != page_count:
        raise RuntimeError("final PDF mechanical audit is not passing")
    if visual_qa.get("passed_visual") is not True or int(visual_qa["pdf"]["pages"]) != page_count:
        raise RuntimeError("final PDF visual audit is not passing")
    if final_qa.get("passed") is not True or final_qa.get("publication_performed") is not False:
        raise RuntimeError("R13 final-QA receipt is not a passing prepublication receipt")

    source_pdf = root / "build" / "stacks-zh-hans-cn-partial.pdf"
    source_pdf_sha = sha256(source_pdf)
    if source_pdf_sha != EXPECTED_PDF_SHA256:
        raise RuntimeError("unexpected final PDF identity")
    if source_pdf_sha != str(pdf_audit["pdf"]["sha256"]).upper():
        raise RuntimeError("build PDF differs from the mechanically audited PDF")
    if source_pdf_sha != str(visual_qa["pdf"]["sha256"]).upper():
        raise RuntimeError("build PDF differs from the visually audited PDF")

    prefix = f"Stacks_Project_zh-Hans-CN_Cumulative_{chapter_count}_Chapters_{PUBLICATION_DATE}"
    pdf_path = release / f"00_{prefix}.pdf"
    zip_path = release / f"01_{prefix}_Source_and_Evidence.zip"
    readme_path = release / f"02_{prefix}_README.md"
    release_manifest_path = release / f"03_{prefix}_RELEASE_MANIFEST.json"
    sums_path = release / f"04_SHA256SUMS_{PUBLICATION_DATE}.txt"
    metadata_path = release / "publication-metadata.json"
    artifact_names = [pdf_path.name, zip_path.name, readme_path.name, release_manifest_path.name, sums_path.name]

    shutil.copyfile(source_pdf, pdf_path)
    if sha256(source_pdf) != sha256(pdf_path):
        raise RuntimeError("stable release PDF copy differs from the verified build PDF")

    reference = source_replay["reference_resolution"]
    fonts = pdf_audit["fonts"]
    annotations = pdf_audit["annotations"]
    extraction = pdf_audit["text_extraction"]
    visual_targets = visual_qa["full_resolution_evidence"]
    chapters_text = "、".join(str(number) for number in chapter_numbers)
    readme = f"""# Stacks Project 简体中文版（zh-Hans-CN）

这是面向中国大陆读者的阶段性累积版。当前版本收入 {chapter_count} 个完整译章，共 {page_count} 页 A4；它不是试译，也不是全书完成或独立中文认证声明。后续完成的章节将继续加入同一中文出版谱系。

## 当前覆盖

第 {chapters_text} 章。各章标题及其精确来源、目标字节数和 SHA-256 见 `manifest.json`。

## 来源与重放

英语 authority 固定为 Stacks Project 提交 `{AUTHORITY_COMMIT}`。累积构建验证全部 {chapter_count} 个译章的 324 个输入绑定及 112 个生成输出；{reference['unique_targets']:,} 个唯一交叉引用目标中，{reference['internal_targets']:,} 个解析到本卷内部，{reference['permanent_tag_targets']:,} 个解析到 Stacks Project 永久标签，另有 {len(reference['manual_commit_pinned_targets'])} 个解析到提交锁定的英语源码，未解析目标为零。正文保持上游公式、标签和引用结构；疑似上游勘误保存在不渲染的 sidecar 中，不悄悄改写本书所绑定的 authority。

可编辑累积源和紧凑重放证据位于 `{zip_path.name}`。其中不包含逐页 PNG、联系表 JPEG 或 200-dpi 目标 PNG 等大体积可再生成文件，但保留它们的逐文件清单、摘要和有序哈希绑定。解压后可从 `src/` 重建；完整任务树中的 `compose.py` 还可重新验证全部输入绑定。

## 版式与 QA

版式采用 A4、11pt、Noto Serif CJK SC、22 mm 对称页边距和适合中文科技文献的行距。全部 {page_count} 页均以 Poppler 24.04.0 重绘，并通过 {visual_qa['contact_sheet_evidence']['count']} 张联系表逐页检查；另有 {visual_targets['target_count']} 个警告页、新增章节边界页和控制页以 200 dpi 检查。未发现裁切、重叠、空白重复页、缺字方框或损坏图表。全部 {fonts['total']} 个字体已嵌入，{pdf_audit['named_destinations']:,} 个命名目标和 {annotations['total']:,} 个链接注释通过机械检查。

不利证据：PDF 尚未带结构标签；{fonts['total'] - fonts['with_to_unicode']} 个旧式数学/Xy-pic 字体子集没有 ToUnicode；提取文本保留 {extraction['literal_double_question_pairs']} 处字面量 `??` 源占位符，但 TeX 和来源重放均无未解析引用；本版本不主张独立中文语言认证。这些限制没有阻断确定性构建、QA 或发布准备。

## 语言边界、许可与非隶属

locale 是 `zh-Hans-CN`，不代表新加坡简体中文，也不代表台湾、香港或澳门的繁体中文本地化。日本语版和韩语版是独立版本和独立 DOI 谱系。

原作与本衍生版依 GNU Free Documentation License 1.2 或其后版本发布，无不变章节、封面文字或封底文字；许可证全文收入 PDF。本版本与 Stacks Project 没有官方隶属或认可关系。

稳定中文概念 DOI：<https://doi.org/{CONCEPT_DOI}>。
"""
    readme_path.write_text(readme, encoding="utf-8", newline="\n")

    title = f"Stacks Project 简体中文版（zh-Hans-CN）：{chapter_count} 章累积版"
    description_html = (
        f"<p><strong>{html.escape(title)}。</strong></p>"
        f"<p>本版本面向中国大陆读者，当前收录 {chapter_count} 个已经完成生产者检查和 canon 机械重放的完整译章，共 {page_count} 页 A4。"
        "它不是试译，也不是全书完成或独立中文认证声明；后续章节将继续加入同一中文出版谱系。</p>"
        f"<p><strong>覆盖范围：</strong>第 {html.escape(chapters_text)} 章。精确标题与哈希见随附清单。</p>"
        f"<p><strong>来源与方法：</strong>英语 authority 固定为 Stacks Project 提交 <code>{AUTHORITY_COMMIT}</code>。"
        f"公式、标签和引用结构均受重放检查；{reference['unique_targets']:,} 个唯一交叉引用目标全部解析。"
        "疑似上游勘误保存在不渲染的 sidecar 中，不悄悄改写绑定的英语 authority。</p>"
        f"<p><strong>版式与 QA：</strong>A4、11pt、Noto Serif CJK SC、22 mm 对称页边距。全部 {page_count} 页已重绘并逐页检查；"
        f"另有 {visual_targets['target_count']} 个警告页、新增章节边界页和控制页以 200 dpi 检查。未发现裁切、重叠、缺字方框或损坏图表。所有字体均嵌入。"
        f"已知可访问性限制：PDF 尚未带结构标签，{fonts['total'] - fonts['with_to_unicode']} 个旧式数学/Xy-pic 字体子集没有 ToUnicode。</p>"
        "<p><strong>语言边界：</strong>locale 是 <code>zh-Hans-CN</code>，不代表新加坡简体中文，也不代表台湾、香港或澳门的繁体中文本地化。</p>"
        "<p><strong>许可与非隶属：</strong>原作与本衍生版依 GNU Free Documentation License 1.2 或其后版本发布，"
        "无不变章节、封面文字或封底文字。本版本与 Stacks Project 没有官方隶属或认可关系。</p>"
    )
    metadata = {
        "schema": "stacks-zh-hans-cn-publication-metadata/v3",
        "version": VERSION,
        "publication_date": PUBLICATION_DATE,
        "title": title,
        "english_subtitle": f"Stacks Project in Mainland Simplified Chinese: Cumulative Edition, {chapter_count} Chapters",
        "description_html": description_html,
        "authors": [
            {"name": "The Stacks Project Authors", "role": "upstream authors"},
            {"name": "OpenAI 5.6 Sol", "role": "Simplified Chinese translation producer"},
        ],
        "keywords": ["Stacks Project", "algebraic geometry", "Simplified Chinese", "zh-Hans-CN", "mathematics", "mathematical translation", "scheme theory", "homological algebra"],
        "language": "zho",
        "license": "GNU Free Documentation License 1.2 or later",
        "authority_commit": AUTHORITY_COMMIT,
        "chapter_count": chapter_count,
        "chapters": chapter_numbers,
        "page_count": page_count,
        "status": "producer_cumulative_uncertified",
        "publication_prepared": True,
        "publication_performed": False,
        "github_status": "reinstated; narrow Chinese canon publication enabled",
        "zenodo_concept_doi": CONCEPT_DOI,
        "publication_policy": "one cumulative Chinese lineage on each repository; Japanese and Korean are separate",
        "prefix": prefix,
        "artifact_names_in_public_order": artifact_names,
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    include_files: list[tuple[Path, str]] = [
        (readme_path, "RELEASE_README.md"),
        (metadata_path, "publication-metadata.json"),
        (root / "README.md", "README.md"),
        (root / "manifest.json", "manifest.json"),
        (root / "compose.py", "compose.py"),
        (root / "build.ps1", "build.ps1"),
        (root / "release" / "make_release_r13.py", "release/make_release_r13.py"),
        (root / "qa" / "source-replay.json", "qa/source-replay.json"),
        (replay_verification_path, "qa/source-replay-verification-r13.json"),
        (root / "qa" / "verify_source_replay_r13.py", "qa/verify_source_replay_r13.py"),
        (pdf_audit_path, "qa/pdf-mechanical-105.json"),
        (root / "qa" / "audit_pdf.py", "qa/audit_pdf.py"),
        (root / "qa" / "pdffonts-105.txt", "qa/pdffonts-105.txt"),
        (visual_qa_path, "qa/visual-qa-105.json"),
        (root / "qa" / "VISUAL_QA_8C54DFF4.md", "qa/VISUAL_QA_8C54DFF4.md"),
        (root / "qa" / "create_visual_qa_105.py", "qa/create_visual_qa_105.py"),
        (root / "qa" / "WARNING_PAGE_MAP_8C54DFF4.json", "qa/WARNING_PAGE_MAP_8C54DFF4.json"),
        (root / "qa" / "VISUAL_TARGETS_8C54DFF4.json", "qa/VISUAL_TARGETS_8C54DFF4.json"),
        (root / "qa" / "prepare_visual_targets_r13.py", "qa/prepare_visual_targets_r13.py"),
        (root / "qa" / "audit_full_res_targets_r13.py", "qa/audit_full_res_targets_r13.py"),
        (root / "qa" / "audit_renders.py", "qa/audit_renders.py"),
        (root / "qa" / "make_contact_sheets.py", "qa/make_contact_sheets.py"),
        (root / "qa" / "visual" / "RENDER_MANIFEST_8C54DFF4.csv", "qa/visual/RENDER_MANIFEST_8C54DFF4.csv"),
        (root / "qa" / "visual" / "RENDER_SUMMARY_8C54DFF4.json", "qa/visual/RENDER_SUMMARY_8C54DFF4.json"),
        (root / "qa" / "visual" / "CONTACT_SHEETS_8C54DFF4.csv", "qa/visual/CONTACT_SHEETS_8C54DFF4.csv"),
        (root / "qa" / "visual" / "FULL_RES_MANIFEST_8C54DFF4.csv", "qa/visual/FULL_RES_MANIFEST_8C54DFF4.csv"),
        (root / "qa" / "visual" / "FULL_RES_SUMMARY_8C54DFF4.json", "qa/visual/FULL_RES_SUMMARY_8C54DFF4.json"),
        (final_qa_path, "qa/R13_FINAL_QA.json"),
        (root / "qa" / "create_final_qa_r13.py", "qa/create_final_qa_r13.py"),
        (root / "build" / "stacks-zh-hans-cn-partial.aux", "build/stacks-zh-hans-cn-partial.aux"),
        (root / "build" / "stacks-zh-hans-cn-partial.bbl", "build/stacks-zh-hans-cn-partial.bbl"),
        (root / "build" / "stacks-zh-hans-cn-partial.blg", "build/stacks-zh-hans-cn-partial.blg"),
        (root / "build" / "stacks-zh-hans-cn-partial.fls", "build/stacks-zh-hans-cn-partial.fls"),
        (root / "build" / "stacks-zh-hans-cn-partial.log", "build/stacks-zh-hans-cn-partial.log"),
        (root / "build" / "stacks-zh-hans-cn-partial.out", "build/stacks-zh-hans-cn-partial.out"),
        (root / "build" / "stacks-zh-hans-cn-partial.toc", "build/stacks-zh-hans-cn-partial.toc"),
        (root / "qa" / "build-r13-recovery-pass-a.stdout.txt", "qa/build-r13-recovery-pass-a.stdout.txt"),
        (root / "qa" / "build-r13-recovery-pass-a.stderr.txt", "qa/build-r13-recovery-pass-a.stderr.txt"),
        (root / "qa" / "build-r13-recovery-pass-b.stdout.txt", "qa/build-r13-recovery-pass-b.stdout.txt"),
        (root / "qa" / "build-r13-recovery-pass-b.stderr.txt", "qa/build-r13-recovery-pass-b.stderr.txt"),
        (root / "qa" / "build-r13-recovery-pass-c.stdout.txt", "qa/build-r13-recovery-pass-c.stdout.txt"),
        (root / "qa" / "build-r13-recovery-pass-c.stderr.txt", "qa/build-r13-recovery-pass-c.stderr.txt"),
        (root.parent / "control" / "INTEGRATION_CH111_CH112_20260823_R7.json", "control/INTEGRATION_CH111_CH112_20260823_R7.json"),
        (root.parent / "control" / "INTEGRATION_CH113_CH114_20260823_R8.json", "control/INTEGRATION_CH113_CH114_20260823_R8.json"),
        (root.parent / "control" / "INTEGRATION_CH86_CH87_20260823_R9.json", "control/INTEGRATION_CH86_CH87_20260823_R9.json"),
        (root.parent / "control" / "INTEGRATION_CH99_20260823_R10.json", "control/INTEGRATION_CH99_20260823_R10.json"),
        (root.parent / "control" / "INTEGRATION_CH100_CH109_CH110_CH115_CH116_INDEX_20260824_R12.json", "control/INTEGRATION_CH100_CH109_CH110_CH115_CH116_INDEX_20260824_R12.json"),
        (root.parent / "control" / "R10_P11_CH099_EVIDENCE_CORRECTION.json", "control/R10_P11_CH099_EVIDENCE_CORRECTION.json"),
        (root.parent / "control" / "INTEGRATION_30_CHAPTERS_20260824_R13.json", "control/INTEGRATION_30_CHAPTERS_20260824_R13.json"),
        (root.parent / "control" / "DEPENDENCY_ZH_DELTA_WITNESS_RECONCILIATION_20260824_R13.json", "control/DEPENDENCY_ZH_DELTA_WITNESS_RECONCILIATION_20260824_R13.json"),
        (root.parent / "control" / "EXISTING_TARGET_RECONCILIATION_CH35_CH39_CH42_20260824_R13.json", "control/EXISTING_TARGET_RECONCILIATION_CH35_CH39_CH42_20260824_R13.json"),
    ]
    for chapter in chapters:
        intake = resolve_program_path(program_root, str(chapter["intake"]["path"]))
        include_files.append((intake, f"control/{intake.name}"))
    for source in sorted((root / "src").glob("*"), key=lambda path: path.name):
        if source.is_file():
            include_files.append((source, f"src/{source.name}"))
    include_files.sort(key=lambda pair: pair[1])
    arcnames = [arcname for _, arcname in include_files]
    if len(arcnames) != len(set(arcnames)):
        raise RuntimeError("duplicate release ZIP entry names")
    missing = [str(path) for path, _ in include_files if not path.is_file()]
    if missing:
        raise RuntimeError(f"release inputs missing: {missing}")

    zip_payloads: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(zip_path, "w", allowZip64=True) as archive:
        for source, arcname in include_files:
            data = sanitize_public_bytes(source.read_bytes())
            require_public_bytes_clean(data, arcname)
            zip_payloads.append((arcname, data))
            zip_add_bytes(archive, arcname, data)
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        names = archive.namelist()
        if bad is not None:
            raise RuntimeError(f"ZIP integrity failure at {bad}")
        if names != arcnames:
            raise RuntimeError("ZIP entry sequence differs from the deterministic release inventory")
        for name in names:
            require_public_bytes_clean(archive.read(name), f"ZIP entry {name}")

    artifact_records = [file_record(pdf_path), file_record(zip_path), file_record(readme_path)]
    release_manifest = {
        "schema": "stacks-zh-hans-cn-release/v3",
        "version": VERSION,
        "publication_date": PUBLICATION_DATE,
        "locale": "zh-Hans-CN",
        "status": "producer_cumulative_uncertified",
        "publication_prepared": True,
        "publication_performed": False,
        "authority_commit": AUTHORITY_COMMIT,
        "zenodo_concept_doi": CONCEPT_DOI,
        "chapter_count": chapter_count,
        "chapters": chapter_numbers,
        "page_count": page_count,
        "source_replay_passed": True,
        "source_replay_verified_inputs": replay_verification["verified_input_bindings"],
        "source_replay_verified_outputs": replay_verification["verified_generated_outputs"],
        "source_replay_unresolved_targets": replay_verification["unresolved_reference_targets"],
        "pdf_mechanical_passed": True,
        "pdf_visual_passed": True,
        "all_pages_visually_inspected": True,
        "full_resolution_targets_inspected": visual_targets["target_count"],
        "zip_entry_count": len(include_files),
        "zip_uncompressed_bytes": sum(len(data) for _, data in zip_payloads),
        "final_qa": {
            "path": "qa/R13_FINAL_QA.json",
            "bytes": final_qa_path.stat().st_size,
            "sha256": sha256(final_qa_path),
        },
        "artifacts": artifact_records,
    }
    release_manifest_path.write_text(json.dumps(release_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    artifact_records.append(file_record(release_manifest_path))
    sums_path.write_text("".join(f"{record['sha256']}  {record['filename']}\n" for record in artifact_records), encoding="ascii", newline="\n")
    artifact_records.append(file_record(sums_path))

    for artifact in (pdf_path, zip_path, readme_path, release_manifest_path, sums_path, metadata_path):
        require_public_bytes_clean(artifact.read_bytes(), artifact.name)
    sums_lines = sums_path.read_text(encoding="ascii").splitlines()
    if len(sums_lines) != 4:
        raise RuntimeError("checksum inventory must bind the four preceding release artifacts")
    for record, line in zip(artifact_records[:4], sums_lines, strict=True):
        if line != f"{record['sha256']}  {record['filename']}":
            raise RuntimeError("checksum inventory drift")

    result = {
        "release_directory": str(release),
        "version": VERSION,
        "chapter_count": chapter_count,
        "page_count": page_count,
        "zip_entry_count": len(include_files),
        "zip_uncompressed_bytes": sum(len(data) for _, data in zip_payloads),
        "publication_performed": False,
        "artifacts": artifact_records,
        "publication_metadata": file_record(metadata_path),
    }
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
