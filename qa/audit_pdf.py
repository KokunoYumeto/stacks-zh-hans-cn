from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def dereference(value):
    return value.get_object() if isinstance(value, IndirectObject) else value


def object_key(value) -> str:
    if isinstance(value, IndirectObject):
        return f"{value.idnum}:{value.generation}"
    return f"direct:{id(value)}"


def rectangle_values(value) -> list[float] | None:
    value = dereference(value)
    if not isinstance(value, ArrayObject) or len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: audit_pdf.py INPUT.pdf OUTPUT.json EXPECTED_PAGES")
    pdf_path = Path(sys.argv[1]).resolve()
    output_path = Path(sys.argv[2]).resolve()
    expected_pages = int(sys.argv[3])
    reader = PdfReader(str(pdf_path), strict=False)
    if reader.is_encrypted:
        raise RuntimeError("release PDF is encrypted")

    page_sizes: Counter[tuple[float, float]] = Counter()
    rotations: Counter[int] = Counter()
    annotation_subtypes: Counter[str] = Counter()
    annotations = 0
    malformed_rectangles: list[dict[str, object]] = []
    zero_area_rectangles: list[dict[str, object]] = []
    out_of_page_rectangles: list[dict[str, object]] = []
    content_stream_bytes: list[int] = []
    text_chars_by_page: list[int] = []
    cjk_by_page: list[int] = []
    extracted_text_parts: list[str] = []
    extraction_errors: list[dict[str, object]] = []
    font_records: dict[str, dict[str, object]] = {}

    for page_number, page in enumerate(reader.pages, start=1):
        media = page.mediabox
        width = float(media.right) - float(media.left)
        height = float(media.top) - float(media.bottom)
        page_sizes[(round(width, 4), round(height, 4))] += 1
        rotations[int(page.get("/Rotate", 0) or 0)] += 1

        contents = page.get_contents()
        if contents is None:
            content_stream_bytes.append(0)
        else:
            try:
                content_stream_bytes.append(len(contents.get_data()))
            except Exception:
                content_stream_bytes.append(-1)

        try:
            text = page.extract_text() or ""
        except Exception as error:
            text = ""
            extraction_errors.append({"page": page_number, "error": repr(error)})
        extracted_text_parts.append(text)
        text_chars_by_page.append(len(text))
        cjk_by_page.append(sum("\u4e00" <= char <= "\u9fff" for char in text))

        resources = dereference(page.get("/Resources", {}))
        fonts = dereference(resources.get("/Font", {})) if isinstance(resources, DictionaryObject) else {}
        if isinstance(fonts, DictionaryObject):
            for resource_name, font_ref in fonts.items():
                key = object_key(font_ref)
                font = dereference(font_ref)
                descriptor = dereference(font.get("/FontDescriptor", {})) if isinstance(font, DictionaryObject) else {}
                descendants = dereference(font.get("/DescendantFonts", [])) if isinstance(font, DictionaryObject) else []
                if isinstance(descendants, ArrayObject) and descendants:
                    descendant = dereference(descendants[0])
                    if isinstance(descendant, DictionaryObject):
                        descendant_descriptor = dereference(descendant.get("/FontDescriptor", {}))
                        if isinstance(descendant_descriptor, DictionaryObject):
                            descriptor = descendant_descriptor
                embedded = False
                if isinstance(descriptor, DictionaryObject):
                    embedded = any(name in descriptor for name in ("/FontFile", "/FontFile2", "/FontFile3"))
                record = font_records.setdefault(
                    key,
                    {
                        "resource_names": set(),
                        "base_font": str(font.get("/BaseFont", "")) if isinstance(font, DictionaryObject) else "",
                        "subtype": str(font.get("/Subtype", "")) if isinstance(font, DictionaryObject) else "",
                        "embedded": embedded,
                        "to_unicode": bool(isinstance(font, DictionaryObject) and font.get("/ToUnicode")),
                        "pages": set(),
                    },
                )
                record["resource_names"].add(str(resource_name))
                record["pages"].add(page_number)

        annots = dereference(page.get("/Annots", []))
        if isinstance(annots, ArrayObject):
            for annot_ref in annots:
                annot = dereference(annot_ref)
                if not isinstance(annot, DictionaryObject):
                    continue
                annotations += 1
                subtype = str(annot.get("/Subtype", ""))
                annotation_subtypes[subtype] += 1
                rect = rectangle_values(annot.get("/Rect"))
                if rect is None:
                    malformed_rectangles.append({"page": page_number, "subtype": subtype})
                    continue
                x0, y0, x1, y1 = rect
                if x1 <= x0 or y1 <= y0:
                    zero_area_rectangles.append({"page": page_number, "rect": rect, "subtype": subtype})
                epsilon = 0.01
                if (
                    x0 < float(media.left) - epsilon
                    or y0 < float(media.bottom) - epsilon
                    or x1 > float(media.right) + epsilon
                    or y1 > float(media.top) + epsilon
                ):
                    out_of_page_rectangles.append({"page": page_number, "rect": rect, "subtype": subtype})

    extracted_text = "\n".join(extracted_text_parts)
    root = reader.trailer["/Root"]
    root_object = dereference(root)
    serializable_fonts = []
    for key, record in sorted(font_records.items()):
        serializable_fonts.append(
            {
                "object": key,
                "resource_names": sorted(record["resource_names"]),
                "base_font": record["base_font"],
                "subtype": record["subtype"],
                "embedded": record["embedded"],
                "to_unicode": record["to_unicode"],
                "first_page": min(record["pages"]),
                "last_page": max(record["pages"]),
            }
        )
    page_labels = getattr(reader, "page_labels", None)
    result = {
        "schema": "stacks-zh-hans-cn-pdf-audit/v1",
        "pdf": {"path": str(pdf_path), "bytes": pdf_path.stat().st_size, "sha256": sha256(pdf_path)},
        "pages": len(reader.pages),
        "expected_pages": expected_pages,
        "page_sizes_points": [
            {"width": width, "height": height, "count": count}
            for (width, height), count in sorted(page_sizes.items())
        ],
        "rotations": {str(rotation): count for rotation, count in sorted(rotations.items())},
        "page_labels": page_labels,
        "metadata": {str(key): str(value) for key, value in (reader.metadata or {}).items()},
        "encrypted": reader.is_encrypted,
        "named_destinations": len(reader.named_destinations),
        "annotations": {
            "total": annotations,
            "subtypes": dict(annotation_subtypes),
            "malformed_rectangles": malformed_rectangles,
            "zero_area_rectangles": zero_area_rectangles,
            "out_of_page_rectangles": out_of_page_rectangles,
        },
        "fonts": {
            "total": len(serializable_fonts),
            "embedded": sum(record["embedded"] for record in serializable_fonts),
            "with_to_unicode": sum(record["to_unicode"] for record in serializable_fonts),
            "records": serializable_fonts,
        },
        "accessibility": {
            "struct_tree_root": bool(isinstance(root_object, DictionaryObject) and root_object.get("/StructTreeRoot")),
            "mark_info": bool(isinstance(root_object, DictionaryObject) and root_object.get("/MarkInfo")),
        },
        "text_extraction": {
            "characters": len(extracted_text),
            "cjk_unified_ideographs": sum("\u4e00" <= char <= "\u9fff" for char in extracted_text),
            "replacement_characters": extracted_text.count("\ufffd"),
            "literal_double_question_pairs": extracted_text.count("??"),
            "errors": extraction_errors,
            "characters_by_page": text_chars_by_page,
            "cjk_by_page": cjk_by_page,
        },
        "content_stream_bytes": content_stream_bytes,
        "passed_mechanical": (
            len(reader.pages) == expected_pages
            and not reader.is_encrypted
            and not malformed_rectangles
            and not zero_area_rectangles
            and not out_of_page_rectangles
            and not extraction_errors
            and all(record["embedded"] for record in serializable_fonts)
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed_mechanical": result["passed_mechanical"],
        "pages": result["pages"],
        "named_destinations": result["named_destinations"],
        "annotations": result["annotations"],
        "fonts_total": result["fonts"]["total"],
        "fonts_embedded": result["fonts"]["embedded"],
        "fonts_with_to_unicode": result["fonts"]["with_to_unicode"],
        "text_extraction": {key: value for key, value in result["text_extraction"].items() if key not in {"characters_by_page", "cjk_by_page"}},
    }, ensure_ascii=False, indent=2))
    return 0 if result["passed_mechanical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
