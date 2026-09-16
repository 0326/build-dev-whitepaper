#!/usr/bin/env python3
"""Validate the minimal evaluation set for build-dev-whitepaper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def add(errors: list[str], location: str, message: str) -> None:
    errors.append(f"{location}: {message}")


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and chr(0) not in value


def stable_id(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= 120 and bool(ID_RE.fullmatch(value))


def validate(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["root: expected an object"]
    if data.get("skill_name") != "build-dev-whitepaper":
        add(errors, "skill_name", "must be build-dev-whitepaper")
    evals = data.get("evals")
    if not isinstance(evals, list) or not evals:
        add(errors, "evals", "must be a non-empty array")
        return errors

    ids: list[str] = []
    for index, item in enumerate(evals):
        location = f"evals[{index}]"
        if not isinstance(item, dict):
            add(errors, location, "expected an object")
            continue
        eval_id = item.get("id")
        if type(eval_id) is int and eval_id >= 1:
            ids.append(str(eval_id))
        elif not stable_id(eval_id):
            add(errors, f"{location}.id", "must be a positive integer or stable ID")
        else:
            ids.append(eval_id)
        for field in ("prompt", "expected_output"):
            if not nonempty_string(item.get(field)):
                add(errors, f"{location}.{field}", "must be a non-empty string")
        files = item.get("files", [])
        if not isinstance(files, list):
            add(errors, f"{location}.files", "must be an array")
        else:
            for file_index, file_path in enumerate(files):
                field_location = f"{location}.files[{file_index}]"
                if not nonempty_string(file_path):
                    add(errors, field_location, "must be a non-empty string")
                else:
                    path = Path(file_path)
                    if path.is_absolute() or ".." in path.parts or chr(92) in file_path:
                        add(errors, field_location, "must be a safe relative path")
        expectations = item.get("expectations")
        if not isinstance(expectations, list) or not expectations:
            add(errors, f"{location}.expectations", "must be a non-empty array")
        else:
            seen: set[str] = set()
            for expectation_index, expectation in enumerate(expectations):
                expectation_location = f"{location}.expectations[{expectation_index}]"
                if isinstance(expectation, str):
                    expectation_id = None
                    expectation_text = expectation
                elif isinstance(expectation, dict):
                    expectation_id = expectation.get("id")
                    expectation_text = expectation.get("text", expectation.get("expectation"))
                    if not stable_id(expectation_id):
                        add(errors, f"{expectation_location}.id", "must be a stable ID")
                else:
                    expectation_id = None
                    expectation_text = None
                if not nonempty_string(expectation_text):
                    add(errors, f"{expectation_location}.text", "must be a non-empty string")
                duplicate_key = expectation_id or expectation_text
                if duplicate_key in seen:
                    add(errors, expectation_location, "duplicate expectation")
                elif duplicate_key is not None:
                    seen.add(duplicate_key)
    if len(ids) != len(set(ids)):
        add(errors, "evals.id", "IDs must be unique")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default=Path(__file__).resolve().parents[1] / "evals" / "evals.json",
        type=Path,
    )
    args = parser.parse_args()
    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [f"input: {type(exc).__name__}: {exc}"]}, ensure_ascii=False, indent=2))
        return 2
    errors = validate(data)
    result = {
        "ok": not errors,
        "skill_name": data.get("skill_name") if isinstance(data, dict) else None,
        "eval_count": len(data.get("evals", [])) if isinstance(data, dict) and isinstance(data.get("evals"), list) else 0,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

