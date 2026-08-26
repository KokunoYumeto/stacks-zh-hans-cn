from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PROGRAM_ROOT = ROOT.parent.parent
MANIFEST = ROOT / "manifest.json"
REPLAY = ROOT / "qa" / "source-replay.json"
OUT = ROOT / "qa" / "source-replay-verification-r14.json"
FROZEN_ROOT = ROOT / "frozen-inputs" / "r14"
STACKS_INPUT = PROGRAM_ROOT / "p11" / "zh_hans_cn" / "stacks-sheaves.tex"
STACKS_OUTPUT = ROOT / "src" / "stacks-sheaves.tex"

EXPECTED_REPLAY_SCHEMA = "stacks-zh-hans-cn-source-replay/v1"
EXPECTED_MANIFEST_SCHEMA = "stacks-zh-hans-cn-cumulative/v1"
EXPECTED_MANIFEST_SHA256 = (
    "252B14733A8F85EA675F0F807244814745320094B28642F6A80364CE1A10A019"
)
EXPECTED_PRE_REFRESH_REPLAY_SHA256 = (
    "86DB134B9437A5F4645B153767C3D6125FFBD766C502BBD6FF275AB5A53AB6E0"
)
EXPECTED_SOURCE_REPLAY_SHA256 = (
    "DE58B1ADE1E2BA38380A54727D94504A86E043D373E21C55C13D536BF2E1E475"
)
EXPECTED_PRE_FOLLOWUP_REPLAY_SHA256 = (
    "3A4DEFB77434E7256B52B9E2BC98E4D669649AAEC96DCA293EDA926FC9D7FB26"
)
EXPECTED_CHAPTERS = 112
EXPECTED_INPUT_BINDINGS = 345
EXPECTED_OUTPUTS = 119
EXPECTED_STACKS_OUTPUT_SHA256 = (
    "88D8F6FF4C8D2547372079252934A7C02CB4C5558CC96EA83DDA46DADA7A7634"
)
EXPECTED_STACKS_READER_EMENDATIONS = [
    {
        "old": r"\{Zariski, \etale, smooth, syntomic, fppf\}",
        "new": r"\{Zariski,\linebreak[0] \etale,\linebreak[0] smooth,\linebreak[0] syntomic,\linebreak[0] fppf\}",
        "count": 5,
    },
    {
        "old": "\\{Zariski, \\etale, smooth,\nsyntomic, fppf\\}",
        "new": "\\{Zariski,\\linebreak[0] \\etale,\\linebreak[0] smooth,\n"
        "\\linebreak[0] syntomic,\\linebreak[0] fppf\\}",
        "count": 1,
    },
    {
        "old": r"\{Zar, \etale, smooth, syntomic, fppf\}",
        "new": r"\{Zar,\allowbreak \etale,\allowbreak smooth,\allowbreak syntomic,\allowbreak fppf\}",
        "count": 17,
    },
]
FROZEN_SOURCES = (
    {
        "stem": "spaces-cohomology",
        "chapter": 69,
        "title": "代数空间的上同调",
        "logical_path": "p09/zh_hans_cn/src/spaces-cohomology.tex",
        "bytes": 164154,
        "sha256": "6A474F50EAB5A68956BF5E260531A0F0D6BEEC4DA625F1C11ABA20EDB729738B",
        "generated_sha256": "D27D92E6D2E2DB4A7B511B6E2924CFC848BFA8EA645979128699D3FC243430ED",
    },
    {
        "stem": "spaces-limits",
        "chapter": 70,
        "title": "代数空间的极限",
        "logical_path": "p09/zh_hans_cn/src/spaces-limits.tex",
        "bytes": 190807,
        "sha256": "264C87FA0BB3786F35846F2801432C7F1B1B06703E7FC9EF72CBFDDC5F6B1A65",
        "generated_sha256": "F762D4195B56A28253CF20D47138450493C6D06389F8520088ABF09113791BDB",
    },
    {
        "stem": "spaces-perfect",
        "chapter": 75,
        "title": "空间的导出范畴",
        "logical_path": "p09/zh_hans_cn/src/spaces-perfect.tex",
        "bytes": 271621,
        "sha256": "4C3DC45217520FBBA6CDDCCE8B51DE041DE32F2B19D6FBC8D03DC1AA32F2FBC4",
        "generated_sha256": "AE62D0561A47B88D2F5ABBBF0C057D98CABF7C5804ED8EA40933CB378B776D69",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def verify_record(record: dict[str, object], group: str) -> dict[str, object]:
    path = Path(str(record["path"])).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{group} binding is missing: {path}")
    actual_bytes = path.stat().st_size
    actual_sha256 = sha256(path)
    expected_bytes = int(record["bytes"])
    expected_sha256 = str(record["sha256"]).upper()
    if actual_bytes != expected_bytes or actual_sha256 != expected_sha256:
        raise ValueError(
            f"{group} binding drift at {path}: "
            f"expected {expected_bytes}/{expected_sha256}, "
            f"found {actual_bytes}/{actual_sha256}"
        )
    return {"path": str(path), "bytes": actual_bytes, "sha256": actual_sha256}


def main() -> int:
    if sha256(REPLAY) != EXPECTED_SOURCE_REPLAY_SHA256:
        raise ValueError("refreshed R14 source-replay hash drift")
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if replay.get("schema") != EXPECTED_REPLAY_SCHEMA:
        raise ValueError("source replay schema drift")
    if replay.get("passed") is not True:
        raise ValueError("source replay receipt is not passing")
    if manifest.get("schema") != EXPECTED_MANIFEST_SCHEMA:
        raise ValueError("manifest schema drift")
    if sha256(MANIFEST) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("frozen R14 manifest hash drift")
    manifest_binding = dict(replay["manifest"])
    if Path(str(manifest_binding["path"])).resolve() != MANIFEST.resolve():
        raise ValueError("source replay is bound to an unexpected manifest path")
    verified_manifest = verify_record(manifest_binding, "manifest")

    inputs = list(replay["verified_inputs"])
    outputs = list(replay["generated_outputs"])
    chapters = list(replay["chapters"])
    if int(replay["chapter_count"]) != EXPECTED_CHAPTERS or len(chapters) != EXPECTED_CHAPTERS:
        raise ValueError("source replay chapter-count drift")
    if len(list(manifest["chapters"])) != EXPECTED_CHAPTERS:
        raise ValueError("manifest chapter-count drift")
    if len(inputs) != EXPECTED_INPUT_BINDINGS:
        raise ValueError("source replay input-binding count drift")
    if len(outputs) != EXPECTED_OUTPUTS:
        raise ValueError("source replay generated-output count drift")
    unresolved = list(replay["reference_resolution"].get("unresolved_targets", []))
    if unresolved:
        raise ValueError(f"source replay has unresolved targets: {unresolved[:10]}")

    verified_inputs = [verify_record(record, "input") for record in inputs]
    verified_outputs = [verify_record(record, "output") for record in outputs]
    manifest_by_stem = {str(record["stem"]): record for record in manifest["chapters"]}
    chapter_by_stem = {str(record["stem"]): record for record in chapters}
    substitutions = list(replay.get("r14_frozen_input_substitutions", []))
    substitution_by_stem = {str(record["stem"]): record for record in substitutions}
    expected_stems = {str(spec["stem"]) for spec in FROZEN_SOURCES}
    if len(substitutions) != 3 or set(substitution_by_stem) != expected_stems:
        raise ValueError("unexpected R14 frozen-input substitution set")

    refresh_delta = dict(replay.get("r14_refresh_delta", {}))
    if refresh_delta != {
        "pre_refresh_source_replay_sha256": EXPECTED_PRE_REFRESH_REPLAY_SHA256,
        "unchanged_input_records": 342,
        "substituted_input_records": 3,
        "unchanged_output_records": 118,
        "refreshed_output_records": 1,
        "unchanged_chapter_records": 111,
        "refreshed_chapter_records": 1,
        "all_other_records_byte_identical": True,
    }:
        raise ValueError("R14 source-replay delta statement drift")

    followup_delta = dict(replay.get("r14_zariski_followup_delta", {}))
    if followup_delta != {
        "pre_followup_source_replay_sha256": EXPECTED_PRE_FOLLOWUP_REPLAY_SHA256,
        "unchanged_input_records": 345,
        "unchanged_output_records": 118,
        "refreshed_output_records": 1,
        "unchanged_chapter_records": 111,
        "refreshed_chapter_records": 1,
        "preserved_frozen_input_substitutions": 3,
        "all_other_records_byte_identical": True,
    }:
        raise ValueError("R14 Zariski followup delta statement drift")

    sys.path.insert(0, str(ROOT))
    import compose  # noqa: PLC0415

    verified_substitutions: list[dict[str, object]] = []
    forward_replays: list[dict[str, object]] = []
    for spec in FROZEN_SOURCES:
        stem = str(spec["stem"])
        substitution = dict(substitution_by_stem[stem])
        if int(substitution["chapter"]) != int(spec["chapter"]):
            raise ValueError(f"{stem} substitution chapter drift")
        logical_target = dict(substitution["logical_manifest_target"])
        expected_logical = {
            "path": str(spec["logical_path"]),
            "bytes": int(spec["bytes"]),
            "sha256": str(spec["sha256"]),
        }
        if logical_target != expected_logical:
            raise ValueError(f"{stem} logical target drift")
        if logical_target != dict(manifest_by_stem[stem]["target"]):
            raise ValueError(f"{stem} logical target does not equal manifest")

        frozen_path = (FROZEN_ROOT / Path(str(spec["logical_path"]))).resolve()
        physical_record = dict(substitution["physical_replay_input"])
        if Path(str(physical_record["path"])).resolve() != frozen_path:
            raise ValueError(f"{stem} substitution physical path drift")
        if int(physical_record["bytes"]) != int(spec["bytes"]):
            raise ValueError(f"{stem} substitution byte-count drift")
        if str(physical_record["sha256"]).upper() != str(spec["sha256"]):
            raise ValueError(f"{stem} substitution SHA-256 drift")
        verified_physical = verify_record(physical_record, f"{stem} frozen input")

        logical_path = (PROGRAM_ROOT / str(spec["logical_path"])).resolve()
        physical_occurrences = sum(
            Path(str(record["path"])).resolve() == frozen_path for record in inputs
        )
        logical_occurrences = sum(
            Path(str(record["path"])).resolve() == logical_path for record in inputs
        )
        if physical_occurrences != 1 or logical_occurrences != 0:
            raise ValueError(f"{stem} one-for-one logical/physical substitution failed")

        verified_receipt = verify_record(
            dict(substitution["reconstruction_receipt"]), f"{stem} reconstruction receipt"
        )
        receipt = json.loads(Path(verified_receipt["path"]).read_text(encoding="utf-8"))
        if receipt.get("passed") is not True or receipt.get("unique_hash_resolved_reconstruction") is not True:
            raise ValueError(f"{stem} reconstruction receipt is not uniquely passing")
        if dict(receipt["physical_frozen_replay_input"]) != physical_record:
            raise ValueError(f"{stem} receipt/source-replay physical binding mismatch")
        if dict(receipt["logical_manifest_target"]) != logical_target:
            raise ValueError(f"{stem} receipt/source-replay logical binding mismatch")

        forward, report = compose.transform_standalone(
            frozen_path.read_text(encoding="utf-8"),
            stem=stem,
            chapter=int(spec["chapter"]),
            expected_title=str(spec["title"]),
        )
        generated_path = ROOT / "src" / f"{stem}.tex"
        if forward.encode("utf-8") != generated_path.read_bytes():
            raise ValueError(f"{stem} frozen input does not replay to generated output")
        if sha256(generated_path) != str(spec["generated_sha256"]):
            raise ValueError(f"{stem} generated output identity drift")
        for key, value in report.items():
            if chapter_by_stem[stem].get(key) != value:
                raise ValueError(f"{stem} chapter replay report drift at {key}")
        output_record = next(
            record
            for record in outputs
            if Path(str(record["path"])).resolve() == generated_path.resolve()
        )
        if dict(chapter_by_stem[stem]["output"]) != output_record:
            raise ValueError(f"{stem} chapter/output binding mismatch")
        verified_substitutions.append(
            {
                "stem": stem,
                "chapter": int(spec["chapter"]),
                "logical_manifest_target": logical_target,
                "physical_replay_input": verified_physical,
                "reconstruction_receipt": verified_receipt,
            }
        )
        forward_replays.append(
            {
                "stem": stem,
                "bytes": len(forward.encode("utf-8")),
                "sha256": sha256(generated_path),
                "equals_generated_output": True,
            }
        )

    stacks_forward, stacks_report = compose.transform_standalone(
        STACKS_INPUT.read_text(encoding="utf-8"),
        stem="stacks-sheaves",
        chapter=96,
        expected_title="代数叠上的层",
    )
    if stacks_forward.encode("utf-8") != STACKS_OUTPUT.read_bytes():
        raise ValueError("stacks-sheaves producer input does not replay to generated output")
    if sha256(STACKS_OUTPUT) != EXPECTED_STACKS_OUTPUT_SHA256:
        raise ValueError("stacks-sheaves generated output identity drift")
    if stacks_report["reader_emendations"] != EXPECTED_STACKS_READER_EMENDATIONS:
        raise ValueError("stacks-sheaves reader-emendation sequence drift")
    for key, value in stacks_report.items():
        if chapter_by_stem["stacks-sheaves"].get(key) != value:
            raise ValueError(f"stacks-sheaves chapter replay report drift at {key}")
    stacks_output_record = next(
        record
        for record in outputs
        if Path(str(record["path"])).resolve() == STACKS_OUTPUT.resolve()
    )
    if dict(chapter_by_stem["stacks-sheaves"]["output"]) != stacks_output_record:
        raise ValueError("stacks-sheaves chapter/output binding mismatch")

    result = {
        "schema": "stacks-zh-hans-cn-source-replay-verification/v1",
        "expected_source_replay_schema": EXPECTED_REPLAY_SCHEMA,
        "source_replay": {
            "path": str(REPLAY.resolve()),
            "bytes": REPLAY.stat().st_size,
            "sha256": sha256(REPLAY),
        },
        "manifest": verified_manifest,
        "expected_manifest_sha256": EXPECTED_MANIFEST_SHA256,
        "chapter_count": int(replay["chapter_count"]),
        "verified_input_bindings": len(verified_inputs),
        "verified_generated_outputs": len(verified_outputs),
        "verified_frozen_input_substitutions": verified_substitutions,
        "frozen_input_forward_replays": forward_replays,
        "stacks_sheaves_forward_replay": {
            "bytes": len(stacks_forward.encode("utf-8")),
            "sha256": sha256(STACKS_OUTPUT),
            "reader_emendations": stacks_report["reader_emendations"],
            "equals_generated_output": True,
        },
        "refresh_delta": refresh_delta,
        "zariski_followup_delta": followup_delta,
        "unique_reference_targets": int(replay["reference_resolution"]["unique_targets"]),
        "unresolved_reference_targets": 0,
        "ordered_input_binding_sha256": hashlib.sha256(
            "".join(
                f"{record['path']}\t{record['bytes']}\t{record['sha256']}\n"
                for record in verified_inputs
            ).encode("utf-8")
        ).hexdigest().upper(),
        "ordered_output_binding_sha256": hashlib.sha256(
            "".join(
                f"{record['path']}\t{record['bytes']}\t{record['sha256']}\n"
                for record in verified_outputs
            ).encode("utf-8")
        ).hexdigest().upper(),
        "passed": True,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
