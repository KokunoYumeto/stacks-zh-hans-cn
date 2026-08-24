from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REPLAY = ROOT / "qa" / "source-replay.json"
OUT = ROOT / "qa" / "source-replay-verification-r13.json"
EXPECTED_CHAPTERS = 105
EXPECTED_INPUT_BINDINGS = 324
EXPECTED_OUTPUTS = 112


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
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    inputs = list(replay["verified_inputs"])
    outputs = list(replay["generated_outputs"])
    if replay.get("passed") is not True:
        raise ValueError("source replay receipt is not passing")
    if int(replay["chapter_count"]) != EXPECTED_CHAPTERS:
        raise ValueError("source replay chapter-count drift")
    if len(inputs) != EXPECTED_INPUT_BINDINGS:
        raise ValueError("source replay input-binding count drift")
    if len(outputs) != EXPECTED_OUTPUTS:
        raise ValueError("source replay generated-output count drift")
    unresolved = list(replay["reference_resolution"].get("unresolved_targets", []))
    if unresolved:
        raise ValueError(f"source replay has unresolved targets: {unresolved[:10]}")

    verified_inputs = [verify_record(record, "input") for record in inputs]
    verified_outputs = [verify_record(record, "output") for record in outputs]
    result = {
        "schema": "stacks-zh-hans-cn-source-replay-verification/v1",
        "source_replay": {
            "path": str(REPLAY),
            "bytes": REPLAY.stat().st_size,
            "sha256": sha256(REPLAY),
        },
        "chapter_count": int(replay["chapter_count"]),
        "verified_input_bindings": len(verified_inputs),
        "verified_generated_outputs": len(verified_outputs),
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
