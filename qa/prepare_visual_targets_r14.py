from __future__ import annotations

import bisect
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
PRIOR_RELEASE = (
    ROOT
    / "release"
    / "03_Stacks_Project_zh-Hans-CN_Cumulative_105_Chapters_2026-08-25_RELEASE_MANIFEST.json"
)

EXPECTED_PDF_SHA256 = "8E1ADB8FA5576317A9153F5ECD8ADC1163233F36E496E39F2380AA0A2DAF55A6"
EXPECTED_LOG_SHA256 = "A2D3C9639A7974A6C94432FF0FBFDE91D6FEC09EFB1DFBDBE07E872AA4741A01"
EXPECTED_MANIFEST_SHA256 = "252B14733A8F85EA675F0F807244814745320094B28642F6A80364CE1A10A019"
EXPECTED_PAGE_COUNT = 5_546
EXPECTED_CHAPTER_COUNT = 112
EXPECTED_NEW_CHAPTERS = [10, 32, 74, 75, 76, 77, 78]

EXPECTED_PRIOR_RELEASE_SHA256 = "1094083D2B588DB9596D56C79BA9E37B832BAD3C6B3CAAFAF24682AC14570828"
EXPECTED_PRIOR_VERSION = "2026.08.25-r13"
EXPECTED_PRIOR_CHAPTER_COUNT = 105
EXPECTED_PRIOR_PAGE_COUNT = 4_877
EXPECTED_PRIOR_PDF_SHA256 = "8C54DFF495B1642EB94828B192FFDF8A49A157E80FFE3CECC997356DB79A28FD"

OUTPUT_STEM = EXPECTED_PDF_SHA256[:8]
WARNING_PATH = QA / f"WARNING_PAGE_MAP_{OUTPUT_STEM}.json"
TARGETS_PATH = QA / f"VISUAL_TARGETS_{OUTPUT_STEM}.json"

CHAPTER_DESTINATION_RE = re.compile(r"chapter\.(\d+)")
BOX_WARNING_RE = re.compile(r"(?:Overfull|Underfull) \\[hv]box")
# TeX sometimes splits a shipout marker as "[123" at end of line and "]" on
# the next line, so a terminal digit sequence is a valid marker preimage too.
SHIPOUT_RE = re.compile(r"(?<![A-Za-z0-9])\[(\d+)(?=\]|\s|$)")
ROMAN_RE = re.compile(r"[ivxlcdm]+")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def roman_to_int(value: str) -> int:
    if not ROMAN_RE.fullmatch(value):
        raise ValueError(f"not a lowercase Roman numeral: {value!r}")
    numerals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    previous = 0
    for character in reversed(value):
        current = numerals[character]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total


def chapter_ranges(
    reader: PdfReader, chapter_numbers: list[int]
) -> tuple[dict[str, dict[str, int]], int]:
    starts: dict[int, int] = {}
    for name, destination in reader.named_destinations.items():
        match = CHAPTER_DESTINATION_RE.fullmatch(name)
        if match:
            chapter = int(match.group(1))
            physical_page = reader.get_destination_page_number(destination) + 1
            if chapter in starts:
                raise RuntimeError(f"duplicate numeric chapter destination: {chapter}")
            starts[chapter] = physical_page

    if set(starts) != set(chapter_numbers):
        missing = sorted(set(chapter_numbers) - set(starts))
        extra = sorted(set(starts) - set(chapter_numbers))
        raise RuntimeError(
            f"numeric chapter destinations differ from manifest: missing={missing}, extra={extra}"
        )

    ordered = sorted(starts.items(), key=lambda item: item[1])
    if [chapter for chapter, _ in ordered] != chapter_numbers:
        raise RuntimeError("chapter destination physical order differs from manifest order")
    if len({start for _, start in ordered}) != len(ordered):
        raise RuntimeError("two chapter destinations resolve to the same physical page")

    page_count = len(reader.pages)
    ranges: dict[str, dict[str, int]] = {}
    for index, (chapter, start) in enumerate(ordered):
        end = ordered[index + 1][1] - 1 if index + 1 < len(ordered) else page_count
        if not 1 <= start <= end <= page_count:
            raise RuntimeError(f"invalid physical range for Chapter {chapter}: {start}-{end}")
        ranges[str(chapter)] = {"start": start, "end": end}
    return ranges, ordered[0][1]


def page_counter_maps(
    reader: PdfReader, first_chapter_page: int
) -> tuple[dict[int, int], dict[int, int]]:
    labels = reader.page_labels
    if len(labels) != len(reader.pages):
        raise RuntimeError("PDF page-label count differs from physical page count")

    front: dict[int, int] = {}
    body: dict[int, int] = {}
    for physical_page, label in enumerate(labels, start=1):
        if physical_page < first_chapter_page:
            if label and ROMAN_RE.fullmatch(label):
                counter = roman_to_int(label)
                if counter in front:
                    raise RuntimeError(f"duplicate front-matter page counter {counter}")
                front[counter] = physical_page
        elif label.isdigit():
            counter = int(label)
            if counter in body:
                raise RuntimeError(f"duplicate body page counter {counter}")
            body[counter] = physical_page

    if body.get(1) != first_chapter_page:
        raise RuntimeError(
            "Chapter 1 destination does not agree with the PDF numeric page-label origin"
        )
    if not front or min(front) != 1 or max(front.values()) != first_chapter_page - 1:
        raise RuntimeError("front-matter Roman page labels do not span to Chapter 1")
    return front, body


def warning_records(
    log_text: str, front_pages: dict[int, int], body_pages: dict[int, int]
) -> list[dict[str, object]]:
    # Reuse the fail-closed shipout parser that binds the complete expected
    # physical-page sequence from both ends.  A simple bracket scan is unsafe:
    # diagnostic text can contain bracketed numbers that look like shipout
    # counters (and did so twice in the final R14 log).
    from refresh_build_receipts_r14 import shipout_records as ordered_shipout_records

    lines = log_text.splitlines()
    warnings: list[dict[str, object]] = []
    body = False

    line_starts: list[int] = []
    offset = 0
    for value in log_text.splitlines(keepends=True):
        line_starts.append(offset)
        offset += len(value)
    shipouts = ordered_shipout_records(log_text, line_starts)
    # One physical front-matter leaf deliberately has no Roman page label, so
    # the label maps need not contain one entry per physical page.  Their
    # greatest physical page still binds the complete PDF extent.
    expected_page_count = max([*front_pages.values(), *body_pages.values()])
    if len(shipouts) != expected_page_count:
        raise RuntimeError(
            "ordered log shipout count differs from the PDF page-label maps: "
            f"{len(shipouts)} != {expected_page_count}"
        )

    for line_number, line in enumerate(lines, start=1):
        if re.fullmatch(r"Chapter 1", line.strip()):
            body = True
        if BOX_WARNING_RE.search(line):
            warnings.append(
                {
                    "line": line_number,
                    "offset": line_starts[line_number - 1],
                    "body": body,
                    "text": line.strip(),
                }
            )

    shipout_offsets = [int(record["offset"]) for record in shipouts]
    for warning in warnings:
        insertion = bisect.bisect_right(shipout_offsets, int(warning.pop("offset")))
        previous = shipouts[insertion - 1] if insertion else None
        following = shipouts[insertion] if insertion < len(shipouts) else None
        previous_physical = int(previous["physical_page"]) if previous is not None else None
        following_physical = int(following["physical_page"]) if following is not None else None

        # Box diagnostics are emitted while TeX is assembling the page that is
        # shipped next.  Falling back to the previous shipout is only needed for
        # a diagnostic after the final shipout.
        if following_physical is not None:
            physical_page = following_physical
            method = "following_shipout_from_unique_ordered_log_sequence"
        elif previous_physical is not None:
            physical_page = previous_physical
            method = "terminal_fallback_previous_shipout_from_unique_ordered_log_sequence"
        else:
            physical_page = None
            method = "unmapped"

        warning.update(
            {
                "previous_shipout_tex_page": (
                    int(previous["tex_page"]) if previous is not None else None
                ),
                "previous_shipout_physical_page": previous_physical,
                "following_shipout_tex_page": (
                    int(following["tex_page"]) if following is not None else None
                ),
                "following_shipout_physical_page": following_physical,
                "pdf_page": physical_page,
                "mapping_method": method,
            }
        )

    return warnings


def main() -> int:
    identities = {
        "pdf": sha256(PDF),
        "log": sha256(LOG),
        "manifest": sha256(MANIFEST),
        "prior_release_manifest": sha256(PRIOR_RELEASE),
    }
    expected_identities = {
        "pdf": EXPECTED_PDF_SHA256,
        "log": EXPECTED_LOG_SHA256,
        "manifest": EXPECTED_MANIFEST_SHA256,
        "prior_release_manifest": EXPECTED_PRIOR_RELEASE_SHA256,
    }
    if identities != expected_identities:
        raise RuntimeError(
            f"input identity mismatch: actual={identities}, expected={expected_identities}"
        )

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    chapter_numbers = [int(item["chapter"]) for item in manifest["chapters"]]
    if len(chapter_numbers) != EXPECTED_CHAPTER_COUNT or len(set(chapter_numbers)) != len(
        chapter_numbers
    ):
        raise RuntimeError("current manifest is not the expected 112-chapter unique sequence")

    prior = json.loads(PRIOR_RELEASE.read_text(encoding="utf-8"))
    prior_chapters = [int(number) for number in prior["chapters"]]
    prior_pdf_artifacts = [
        item
        for item in prior["artifacts"]
        if str(item.get("filename", "")).lower().endswith(".pdf")
    ]
    if (
        prior.get("version") != EXPECTED_PRIOR_VERSION
        or int(prior.get("chapter_count", -1)) != EXPECTED_PRIOR_CHAPTER_COUNT
        or len(prior_chapters) != EXPECTED_PRIOR_CHAPTER_COUNT
        or len(set(prior_chapters)) != EXPECTED_PRIOR_CHAPTER_COUNT
        or int(prior.get("page_count", -1)) != EXPECTED_PRIOR_PAGE_COUNT
        or len(prior_pdf_artifacts) != 1
        or str(prior_pdf_artifacts[0].get("sha256", "")).upper()
        != EXPECTED_PRIOR_PDF_SHA256
    ):
        raise RuntimeError("prior release is not the exact R13 105-chapter state")

    new_chapters = [chapter for chapter in chapter_numbers if chapter not in set(prior_chapters)]
    if new_chapters != EXPECTED_NEW_CHAPTERS:
        raise RuntimeError(
            f"R14 chapter delta differs from assignment: {new_chapters} != {EXPECTED_NEW_CHAPTERS}"
        )

    reader = PdfReader(PDF)
    page_count = len(reader.pages)
    if page_count != EXPECTED_PAGE_COUNT:
        raise RuntimeError(f"unexpected page count: {page_count}")

    ranges, first_chapter_page = chapter_ranges(reader, chapter_numbers)
    front_counter_pages, body_counter_pages = page_counter_maps(reader, first_chapter_page)

    warnings = warning_records(
        LOG.read_text(encoding="utf-8", errors="replace"),
        front_counter_pages,
        body_counter_pages,
    )
    unmapped = [record for record in warnings if record["pdf_page"] is None]
    if unmapped:
        raise RuntimeError(f"{len(unmapped)} box warnings could not be mapped to physical pages")
    box_warning_pages = sorted({int(record["pdf_page"]) for record in warnings})

    warning_map = {
        "schema": "stacks-zh-hans-cn-warning-page-map/v3",
        "pdf_sha256": identities["pdf"],
        "log_sha256": identities["log"],
        "page_count": page_count,
        "first_chapter_physical_page": first_chapter_page,
        "mapping_basis": (
            "TeX shipout counters resolved through PDF Roman/numeric page labels; "
            "no fixed physical-page offset"
        ),
        "records": warnings,
        "record_count": len(warnings),
        "unique_mapped_box_warning_pdf_pages": box_warning_pages,
        "unique_mapped_box_warning_pdf_page_count": len(box_warning_pages),
        "unmapped_count": 0,
    }
    WARNING_PATH.write_text(
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

    frontmatter_pages = list(range(2, first_chapter_page))
    if not frontmatter_pages:
        raise RuntimeError("expected numbered front matter before Chapter 1")
    middle_left = frontmatter_pages[(len(frontmatter_pages) - 1) // 2]
    middle_right = frontmatter_pages[len(frontmatter_pages) // 2]
    fixed_pages = sorted(
        {
            1,
            frontmatter_pages[0],
            middle_left,
            middle_right,
            frontmatter_pages[-1],
            first_chapter_page,
            page_count,
        }
    )
    selected_pages = sorted(set(fixed_pages + box_warning_pages + new_boundaries))

    targets = {
        "schema": "stacks-zh-hans-cn-visual-targets/v2",
        "pdf_sha256": identities["pdf"],
        "pdf_bytes": PDF.stat().st_size,
        "page_count": page_count,
        "manifest": {
            "path": MANIFEST.relative_to(ROOT).as_posix(),
            "sha256": identities["manifest"],
            "chapter_count": len(chapter_numbers),
            "chapters": chapter_numbers,
        },
        "prior_release": {
            "path": PRIOR_RELEASE.relative_to(ROOT).as_posix(),
            "sha256": identities["prior_release_manifest"],
            "version": prior["version"],
            "chapter_count": prior["chapter_count"],
            "page_count": prior["page_count"],
            "chapters": prior_chapters,
            "pdf_sha256": EXPECTED_PRIOR_PDF_SHA256,
        },
        "chapter_range_basis": "numeric PDF named destinations; no fixed offset",
        "chapter_ranges": ranges,
        "new_chapters": new_chapters,
        "new_chapter_boundary_pages": new_boundaries,
        "warning_page_map": {
            "path": WARNING_PATH.relative_to(ROOT).as_posix(),
            "bytes": WARNING_PATH.stat().st_size,
            "sha256": sha256(WARNING_PATH),
            "record_count": len(warnings),
            "unique_page_count": len(box_warning_pages),
        },
        "box_warning_pages": box_warning_pages,
        "fixed_control_pages": {
            "cover": [1],
            "frontmatter": sorted(
                {frontmatter_pages[0], middle_left, middle_right, frontmatter_pages[-1]}
            ),
            "chapter_1_seam": [first_chapter_page],
            "terminal": [page_count],
            "all": fixed_pages,
        },
        "selected_pages": selected_pages,
        "selected_page_count": len(selected_pages),
    }
    TARGETS_PATH.write_text(
        json.dumps(targets, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(
        json.dumps(
            {
                "status": "PASS",
                "targets_path": str(TARGETS_PATH),
                "targets_bytes": TARGETS_PATH.stat().st_size,
                "targets_sha256": sha256(TARGETS_PATH),
                "selected_page_count": len(selected_pages),
                "box_warning_page_count": len(box_warning_pages),
                "new_chapter_boundary_page_count": len(new_boundaries),
                "warning_map_path": str(WARNING_PATH),
                "warning_map_sha256": sha256(WARNING_PATH),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
