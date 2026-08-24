from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "qa"
TARGETS = QA / "VISUAL_TARGETS_8C54DFF4.json"
PAGE_DIR = QA / "visual" / "full-res-8C54DFF4"
MANIFEST = QA / "visual" / "FULL_RES_MANIFEST_8C54DFF4.csv"
SUMMARY = QA / "visual" / "FULL_RES_SUMMARY_8C54DFF4.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    selected = [int(page) for page in targets["selected_pages"]]
    expected_names = [f"page-{page:04d}.png" for page in selected]
    actual_paths = sorted(PAGE_DIR.glob("page-*.png"))
    actual_names = [path.name for path in actual_paths]
    if actual_names != expected_names:
        missing = sorted(set(expected_names) - set(actual_names))
        extra = sorted(set(actual_names) - set(expected_names))
        raise RuntimeError(f"full-resolution target sequence mismatch: missing={missing}, extra={extra}")

    records: list[dict[str, object]] = []
    for page, path in zip(selected, actual_paths, strict=True):
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            mode = image.mode
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

    with MANIFEST.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    ordered_digest = hashlib.sha256()
    for record in records:
        ordered_digest.update(f"{record['page']}\t{record['sha256']}\n".encode("ascii"))
    dimensions = sorted({(int(record["width_px"]), int(record["height_px"])) for record in records})
    summary = {
        "schema": "stacks-zh-hans-cn-full-resolution-target-audit/v1",
        "pdf_sha256": targets["pdf_sha256"],
        "renderer": {"name": "pdftoppm", "implementation": "Poppler", "version": "24.04.0"},
        "render_dpi": 200,
        "selected_page_count": len(records),
        "selected_pages": selected,
        "total_bytes": sum(int(record["bytes"]) for record in records),
        "dimensions_px": [list(value) for value in dimensions],
        "ordered_page_hash_binding_sha256": ordered_digest.hexdigest().upper(),
        "manifest": {
            "path": "qa/visual/FULL_RES_MANIFEST_8C54DFF4.csv",
            "bytes": MANIFEST.stat().st_size,
            "sha256": sha256(MANIFEST),
        },
        "passed": True,
    }
    SUMMARY.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
