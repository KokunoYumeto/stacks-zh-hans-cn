from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "qa"
PDF = ROOT / "build" / "stacks-zh-hans-cn-partial.pdf"
TARGETS = QA / "VISUAL_TARGETS_8E1ADB8F.json"
PAGE_DIR = QA / "visual" / "full-res-8E1ADB8F"
MANIFEST = QA / "visual" / "FULL_RES_MANIFEST_8E1ADB8F.csv"
SUMMARY = QA / "visual" / "FULL_RES_SUMMARY_8E1ADB8F.json"

EXPECTED_PDF_SHA256 = "8E1ADB8FA5576317A9153F5ECD8ADC1163233F36E496E39F2380AA0A2DAF55A6"
EXPECTED_PDF_BYTES = 32_610_849
EXPECTED_PAGES = 5_546
EXPECTED_TARGETS = 148
EXPECTED_TARGETS_SHA256 = "CB2724820D724F8216ED3E2630283F7A3079529DF6579647CEB2EC520C9AFAD4"
EXPECTED_DPI = 200
EXPECTED_DIMENSIONS = (1_654, 2_339)
EXPECTED_MODE = "RGB"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def file_record(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": relative(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def validate_static_inputs() -> tuple[dict[str, Any], list[int]]:
    if not PDF.is_file():
        raise FileNotFoundError(PDF)
    if PDF.stat().st_size != EXPECTED_PDF_BYTES:
        raise RuntimeError("R14 PDF byte count drift")
    pdf_hash = sha256(PDF)
    if pdf_hash != EXPECTED_PDF_SHA256:
        raise RuntimeError(f"R14 PDF identity drift: {pdf_hash}")
    if sha256(TARGETS) != EXPECTED_TARGETS_SHA256:
        raise RuntimeError("R14 visual-target receipt identity drift")

    targets = load_json(TARGETS)
    if targets.get("schema") != "stacks-zh-hans-cn-visual-targets/v2":
        raise RuntimeError("unexpected visual-target schema")
    if str(targets.get("pdf_sha256", "")).upper() != EXPECTED_PDF_SHA256:
        raise RuntimeError("visual targets bind another PDF")
    if int(targets.get("pdf_bytes", -1)) != EXPECTED_PDF_BYTES:
        raise RuntimeError("visual-target PDF byte count drift")
    if int(targets.get("page_count", -1)) != EXPECTED_PAGES:
        raise RuntimeError("visual-target page count drift")

    selected = [int(page) for page in targets.get("selected_pages", [])]
    if int(targets.get("selected_page_count", -1)) != EXPECTED_TARGETS:
        raise RuntimeError("visual-target declared count drift")
    if len(selected) != EXPECTED_TARGETS:
        raise RuntimeError("visual-target list count drift")
    if selected != sorted(set(selected)):
        raise RuntimeError("visual-target pages are not unique and strictly increasing")
    if not selected or selected[0] < 1 or selected[-1] > EXPECTED_PAGES:
        raise RuntimeError("visual-target page lies outside the R14 PDF")
    return targets, selected


def expected_filenames(selected: list[int]) -> list[str]:
    return [f"page-{page:04d}.png" for page in selected]


def audit_images(selected: list[int]) -> list[dict[str, object]]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - operational dependency check
        raise RuntimeError("Pillow is required for the full-resolution image audit") from exc

    expected_names = expected_filenames(selected)
    actual_paths = sorted(PAGE_DIR.glob("page-*.png"), key=lambda path: path.name)
    actual_names = [path.name for path in actual_paths]
    if actual_names != expected_names:
        missing = sorted(set(expected_names) - set(actual_names))
        extra = sorted(set(actual_names) - set(expected_names))
        raise RuntimeError(
            "full-resolution target sequence mismatch: "
            f"missing={missing}, extra={extra}"
        )

    records: list[dict[str, object]] = []
    for page, path in zip(selected, actual_paths, strict=True):
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            mode = image.mode
        if (width, height) != EXPECTED_DIMENSIONS:
            raise RuntimeError(
                f"unexpected 200-dpi dimensions for page {page}: {width}x{height}"
            )
        if mode != EXPECTED_MODE:
            raise RuntimeError(f"unexpected image mode for page {page}: {mode}")
        records.append(
            {
                "page": page,
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "width_px": width,
                "height_px": height,
                "mode": mode,
            }
        )
    return records


def write_outputs(targets: dict[str, Any], selected: list[int], records: list[dict[str, object]]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["page", "filename", "bytes", "sha256", "width_px", "height_px", "mode"]
    with MANIFEST.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    ordered_digest = hashlib.sha256()
    for record in records:
        ordered_digest.update(f"{record['page']}\t{record['sha256']}\n".encode("ascii"))

    summary = {
        "schema": "stacks-zh-hans-cn-full-resolution-target-audit/v2",
        "pdf": file_record(PDF),
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "page_count": EXPECTED_PAGES,
        "renderer": {
            "name": "pdftoppm",
            "implementation": "Poppler",
            "render_contract": "A4 PNG at 200 dpi; 1654 x 2339 RGB pixels",
        },
        "render_dpi": EXPECTED_DPI,
        "render_directory": relative(PAGE_DIR),
        "selected_page_count": len(records),
        "selected_pages": selected,
        "total_bytes": sum(int(record["bytes"]) for record in records),
        "dimensions_px": [list(EXPECTED_DIMENSIONS)],
        "mode": EXPECTED_MODE,
        "ordered_page_hash_binding_sha256": ordered_digest.hexdigest().upper(),
        "targets": file_record(TARGETS),
        "manifest": file_record(MANIFEST),
        "passed": True,
    }
    if summary["targets"]["sha256"] != EXPECTED_TARGETS_SHA256:
        raise RuntimeError("visual-target receipt changed during the audit")
    if str(targets["pdf_sha256"]).upper() != summary["pdf_sha256"]:
        raise RuntimeError("visual-target/PDF binding changed during the audit")
    SUMMARY.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(summary, ensure_ascii=False))


def dry_run(selected: list[int]) -> int:
    names = expected_filenames(selected)
    actual = sorted(PAGE_DIR.glob("page-*.png"), key=lambda path: path.name) if PAGE_DIR.is_dir() else []
    result = {
        "dry_run": True,
        "static_inputs_valid": True,
        "writes_performed": False,
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "page_count": EXPECTED_PAGES,
        "target_count": EXPECTED_TARGETS,
        "render_contract": {
            "directory": relative(PAGE_DIR),
            "first_expected_file": names[0],
            "last_expected_file": names[-1],
            "dpi": EXPECTED_DPI,
            "dimensions_px": list(EXPECTED_DIMENSIONS),
            "mode": EXPECTED_MODE,
        },
        "actual_target_file_count": len(actual),
        "ready_for_full_audit": [path.name for path in actual] == names,
        "would_write": [relative(MANIFEST), relative(SUMMARY)],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit the exact 148 R14 200-dpi visual targets without rendering them."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate immutable inputs and print the render/output contract without writing",
    )
    args = parser.parse_args()

    targets, selected = validate_static_inputs()
    if args.dry_run:
        return dry_run(selected)
    records = audit_images(selected)
    write_outputs(targets, selected, records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
