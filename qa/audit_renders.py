from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit("usage: audit_renders.py PAGE_DIR MANIFEST.csv SUMMARY.json EXPECTED_PAGES")
    page_dir = Path(sys.argv[1]).resolve()
    manifest_path = Path(sys.argv[2]).resolve()
    summary_path = Path(sys.argv[3]).resolve()
    expected_pages = int(sys.argv[4])
    pages = sorted(page_dir.glob("page-*.png"))
    if len(pages) != expected_pages:
        raise RuntimeError(f"expected {expected_pages} rendered pages, found {len(pages)}")

    records: list[dict[str, object]] = []
    digits = max(3, len(str(expected_pages)))
    expected_names = [
        f"page-{number:0{digits}d}.png" for number in range(1, expected_pages + 1)
    ]
    actual_names = [path.name for path in pages]
    if actual_names != expected_names:
        raise RuntimeError(
            f"rendered page sequence is not exactly {expected_names[0]} "
            f"through {expected_names[-1]}"
        )

    for page_number, path in enumerate(pages, start=1):
        with Image.open(path) as image:
            width, height = image.size
            mode = image.mode
        records.append(
            {
                "page": page_number,
                "filename": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "width_px": width,
                "height_px": height,
                "mode": mode,
            }
        )

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    ordered_digest = hashlib.sha256()
    for record in records:
        ordered_digest.update(f"{record['page']}\t{record['sha256']}\n".encode("ascii"))
    dimensions = sorted({(int(record["width_px"]), int(record["height_px"])) for record in records})
    summary = {
        "schema": "stacks-zh-hans-cn-render-audit/v1",
        "renderer": {"name": "pdftoppm", "implementation": "Poppler", "version": "24.04.0"},
        "render_dpi": 100,
        "page_count": len(records),
        "expected_page_count": expected_pages,
        "total_bytes": sum(int(record["bytes"]) for record in records),
        "first_file": records[0]["filename"],
        "last_file": records[-1]["filename"],
        "dimensions_px": [list(value) for value in dimensions],
        "ordered_page_hash_binding_sha256": ordered_digest.hexdigest().upper(),
        "manifest": {
            "path": str(manifest_path),
            "bytes": manifest_path.stat().st_size,
            "sha256": sha256(manifest_path),
        },
        "passed": True,
    }
    with summary_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
