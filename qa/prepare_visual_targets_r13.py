from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "qa"
PDF = ROOT / "build" / "stacks-zh-hans-cn-partial.pdf"
LOG = ROOT / "build" / "stacks-zh-hans-cn-partial.log"
MANIFEST = ROOT / "manifest.json"
OLD_RELEASE = (
    ROOT
    / "release"
    / "03_Stacks_Project_zh-Hans-CN_Cumulative_75_Chapters_2026-08-24_RELEASE_MANIFEST.json"
)
EXPECTED_PDF_SHA256 = "8C54DFF495B1642EB94828B192FFDF8A49A157E80FFE3CECC997356DB79A28FD"
BODY_PHYSICAL_PAGE_OFFSET = 39


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def warning_records(log_text: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    last_tex_page: int | None = None
    body = False
    warning_patterns = (
        r"Overfull \\hbox",
        r"Underfull \\hbox",
        r"Overfull \\vbox",
        r"Underfull \\vbox",
        r"Missing character",
        r"undefined references|Reference .* undefined",
        r"undefined citations|Citation .* undefined",
    )
    warning_re = re.compile("|".join(f"(?:{item})" for item in warning_patterns))
    shipout_re = re.compile(r"(?<![A-Za-z0-9])\[(\d+)\](?![A-Za-z0-9])")
    for line_number, line in enumerate(log_text.splitlines(), start=1):
        if re.fullmatch(r"Chapter 1", line.strip()):
            body = True
            last_tex_page = None
        for match in shipout_re.finditer(line):
            last_tex_page = int(match.group(1))
        if warning_re.search(line):
            pdf_page = None
            if last_tex_page is not None:
                pdf_page = last_tex_page + (BODY_PHYSICAL_PAGE_OFFSET if body else 0)
            records.append(
                {
                    "line": line_number,
                    "body": body,
                    "tex_page": last_tex_page,
                    "pdf_page": pdf_page,
                    "text": line.strip(),
                }
            )
    return records


def main() -> int:
    pdf_hash = sha256(PDF)
    if pdf_hash != EXPECTED_PDF_SHA256:
        raise RuntimeError(f"unexpected PDF identity: {pdf_hash}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    old_release = json.loads(OLD_RELEASE.read_text(encoding="utf-8"))
    chapter_numbers = [int(item["chapter"]) for item in manifest["chapters"]]
    old_chapters = {int(number) for number in old_release["chapters"]}
    new_chapters = [number for number in chapter_numbers if number not in old_chapters]

    reader = PdfReader(PDF)
    page_count = len(reader.pages)
    starts: dict[int, int] = {}
    for name, destination in reader.named_destinations.items():
        match = re.fullmatch(r"chapter\.(\d+)", name)
        if match:
            starts[int(match.group(1))] = reader.get_destination_page_number(destination) + 1
    if set(starts) != set(chapter_numbers):
        raise RuntimeError("numeric chapter destinations differ from manifest chapters")
    ordered = sorted(starts.items(), key=lambda item: item[1])
    ranges: dict[str, dict[str, int]] = {}
    for index, (chapter, start) in enumerate(ordered):
        end = ordered[index + 1][1] - 1 if index + 1 < len(ordered) else page_count
        ranges[str(chapter)] = {"start": start, "end": end}

    log_text = LOG.read_text(encoding="utf-8", errors="replace")
    warnings = warning_records(log_text)
    mapped_box_pages = sorted(
        {
            int(record["pdf_page"])
            for record in warnings
            if record["pdf_page"] is not None
            and re.search(r"(?:Overfull|Underfull) \\[hv]box", str(record["text"]))
        }
    )
    unmapped = [record for record in warnings if record["pdf_page"] is None]
    warning_map = {
        "schema": "stacks-zh-hans-cn-warning-page-map/v2",
        "pdf_sha256": pdf_hash,
        "log_sha256": sha256(LOG),
        "body_physical_page_offset": BODY_PHYSICAL_PAGE_OFFSET,
        "records": warnings,
        "unique_mapped_box_warning_pdf_pages": mapped_box_pages,
        "unmapped_count": len(unmapped),
    }
    warning_path = QA / "WARNING_PAGE_MAP_8C54DFF4.json"
    warning_path.write_text(
        json.dumps(warning_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    new_boundaries = sorted(
        {
            page
            for chapter in new_chapters
            for page in (ranges[str(chapter)]["start"], ranges[str(chapter)]["end"])
        }
    )
    fixed_pages = [1, 2, 39, 40, 68, 69, page_count]
    selected_pages = sorted(set(fixed_pages + mapped_box_pages + new_boundaries))
    targets = {
        "schema": "stacks-zh-hans-cn-visual-targets/v1",
        "pdf_sha256": pdf_hash,
        "page_count": page_count,
        "manifest_chapter_count": len(chapter_numbers),
        "chapter_ranges": ranges,
        "prior_release_chapter_count": len(old_chapters),
        "new_chapters": new_chapters,
        "new_chapter_boundary_pages": new_boundaries,
        "box_warning_pages": mapped_box_pages,
        "fixed_front_and_terminal_pages": fixed_pages,
        "selected_pages": selected_pages,
        "selected_page_count": len(selected_pages),
    }
    targets_path = QA / "VISUAL_TARGETS_8C54DFF4.json"
    targets_path.write_text(
        json.dumps(targets, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"warning_map": str(warning_path), "targets": targets}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
