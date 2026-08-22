from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    if len(sys.argv) != 5:
        raise SystemExit("usage: make_contact_sheets.py PAGE_DIR SHEET_DIR MANIFEST.csv EXPECTED_PAGES")
    page_dir = Path(sys.argv[1]).resolve()
    sheet_dir = Path(sys.argv[2]).resolve()
    manifest_path = Path(sys.argv[3]).resolve()
    expected_pages = int(sys.argv[4])
    pages = sorted(page_dir.glob("page-*.png"))
    if len(pages) != expected_pages:
        raise RuntimeError(f"expected {expected_pages} rendered pages, found {len(pages)}")
    sheet_dir.mkdir(parents=True, exist_ok=True)
    columns, rows = 4, 5
    tile_width, tile_height = 300, 424
    gutter, label_height = 12, 24
    font = ImageFont.load_default(size=16)
    records: list[dict[str, object]] = []
    for sheet_index in range(0, len(pages), columns * rows):
        subset = pages[sheet_index : sheet_index + columns * rows]
        canvas = Image.new(
            "RGB",
            (
                gutter + columns * (tile_width + gutter),
                gutter + rows * (tile_height + label_height + gutter),
            ),
            "#d8d8d8",
        )
        draw = ImageDraw.Draw(canvas)
        page_numbers = []
        for offset, page_path in enumerate(subset):
            page_number = int(page_path.stem.split("-")[-1])
            page_numbers.append(page_number)
            row, column = divmod(offset, columns)
            x = gutter + column * (tile_width + gutter)
            y = gutter + row * (tile_height + label_height + gutter)
            with Image.open(page_path) as image:
                image = image.convert("RGB")
                image.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
                paste_x = x + (tile_width - image.width) // 2
                paste_y = y + label_height + (tile_height - image.height) // 2
                canvas.paste(image, (paste_x, paste_y))
            draw.text((x + 4, y + 2), f"PDF {page_number}", fill="black", font=font)
        sheet_number = sheet_index // (columns * rows) + 1
        sheet_path = sheet_dir / f"sheet-{sheet_number:03d}-pages-{page_numbers[0]:03d}-{page_numbers[-1]:03d}.jpg"
        canvas.save(sheet_path, format="JPEG", quality=92, optimize=True)
        records.append(
            {
                "sheet": sheet_number,
                "first_page": page_numbers[0],
                "last_page": page_numbers[-1],
                "path": str(sheet_path),
                "bytes": sheet_path.stat().st_size,
                "sha256": sha256(sheet_path),
            }
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print(f"pages={len(pages)} sheets={len(records)} manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
