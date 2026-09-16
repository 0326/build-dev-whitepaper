#!/usr/bin/env python3
"""Score a structured build-dev-whitepaper evaluation run.

The runner deliberately does not infer quality from output keywords. An Agent
harness or an independent reviewer records expectation-level decisions and
evidence; this script validates that record and produces a reproducible
scorecard for candidate/baseline comparisons.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from validate_evals import validate as validate_catalog
except ImportError:  # pragma: no cover - useful when copied as a standalone script
    validate_catalog = None


ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
STATUSES = {"pass", "fail", "blocked", "not-run"}
EVIDENCE_KINDS = {"artifact", "output", "review", "test", "source"}
VARIANT_KEYS = {"with_skill", "without_skill", "old_skill", "candidate", "baseline"}


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\x00" not in value


def stable_id(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= 120 and bool(ID_RE.fullmatch(value))


def safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        return False
    path = Path(value)
    return not (path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value)


def case_key(value: Any) -> str:
    if type(value) is int and value > 0:
        return str(value)
    if stable_id(value):
        return value
    return ""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def expectation_entries(case: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for index, raw in enumerate(case.get("expectations", []), start=1):
        if isinstance(raw, str):
            entries.append({"id": f"e{index}", "text": raw})
        elif isinstance(raw, dict):
            expectation_id = raw.get("id") or f"e{index}"
            text = raw.get("text") or raw.get("expectation") or ""
            entries.append({"id": str(expectation_id), "text": str(text)})
    return entries


def catalog_cases(catalog: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(catalog, dict) or not isinstance(catalog.get("evals"), list):
        return {}, ["catalog.evals: expected a non-empty array"]
    result: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(catalog["evals"]):
        if not isinstance(case, dict):
            errors.append(f"catalog.evals[{index}]: expected an object")
            continue
        key = case_key(case.get("id"))
        if not key:
            errors.append(f"catalog.evals[{index}].id: expected a positive integer or stable ID")
            continue
        if key in result:
            errors.append(f"catalog.evals[{index}].id: duplicate case ID: {key}")
        else:
            result[key] = case
    return result, errors


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def number(value: Any, location: str, errors: list[str], *, integer: bool = False) -> float | int | None:
    if integer:
        valid = type(value) is int and value >= 0
    else:
        valid = (type(value) in {int, float}) and value >= 0
    if not valid:
        errors.append(f"{location}: expected a non-negative {'integer' if integer else 'number'}")
        return None
    return value


def normalize_metrics(raw: Any, location: str, errors: list[str]) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        errors.append(f"{location}: expected an object")
        return {}
    metrics: dict[str, Any] = {}
    if "duration_ms" in raw:
        value = number(raw["duration_ms"], f"{location}.duration_ms", errors)
        if value is not None:
            metrics["duration_ms"] = value
    if "tool_calls" in raw:
        value = number(raw["tool_calls"], f"{location}.tool_calls", errors, integer=True)
        if value is not None:
            metrics["tool_calls"] = value
    tokens = raw.get("tokens")
    if tokens is not None:
        if not isinstance(tokens, dict):
            errors.append(f"{location}.tokens: expected an object")
        else:
            normalized_tokens: dict[str, int] = {}
            for field in ("input", "output", "total"):
                if field in tokens:
                    value = number(tokens[field], f"{location}.tokens.{field}", errors, integer=True)
                    if value is not None:
                        normalized_tokens[field] = int(value)
            if "total" not in normalized_tokens and {"input", "output"} <= normalized_tokens.keys():
                normalized_tokens["total"] = normalized_tokens["input"] + normalized_tokens["output"]
            metrics["tokens"] = normalized_tokens
    return metrics


def validate_evidence(raw: Any, location: str, errors: list[str]) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        errors.append(f"{location}: expected an array")
        return []
    evidence: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        item_location = f"{location}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_location}: expected an object")
            continue
        kind = item.get("kind")
        locator = item.get("locator")
        if kind not in EVIDENCE_KINDS:
            errors.append(f"{item_location}.kind: must be one of {', '.join(sorted(EVIDENCE_KINDS))}")
        if not nonempty(locator):
            errors.append(f"{item_location}.locator: must be a non-empty locator")
        if "excerpt" in item and not isinstance(item.get("excerpt"), str):
            errors.append(f"{item_location}.excerpt: must be a string when specified")
        if kind in EVIDENCE_KINDS and nonempty(locator):
            record = {"kind": kind, "locator": locator}
            if nonempty(item.get("excerpt")):
                record["excerpt"] = item["excerpt"]
            evidence.append(record)
    return evidence


def summarize_case(
    case: dict[str, Any],
    raw_result: Any,
    location: str,
    *,
    allow_partial: bool,
) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    expected = expectation_entries(case)
    expected_by_index = {index: item for index, item in enumerate(expected, start=1)}
    if not isinstance(raw_result, dict):
        return (
            {
                "case_id": case.get("id"),
                "status": "error",
                "expected_expectations": len(expected),
                "passed_expectations": 0,
                "pass_rate": 0.0,
                "evidence_coverage": 0.0,
                "failure_reasons": ["case result must be an object"],
                "expectations": [],
                "metrics": {},
                "ok": False,
            },
            [f"{location}: expected an object"],
            warnings,
        )

    result_case_id = case_key(raw_result.get("case_id"))
    if result_case_id != case_key(case.get("id")):
        errors.append(f"{location}.case_id: does not match catalog case {case.get('id')}")
    metrics_errors: list[str] = []
    metrics = normalize_metrics(raw_result.get("metrics"), f"{location}.metrics", metrics_errors)
    # Accept the compact top-level metric form as an input convenience.
    compact_metrics = {key: raw_result[key] for key in ("duration_ms", "tool_calls", "tokens") if key in raw_result}
    if compact_metrics:
        compact = normalize_metrics(compact_metrics, f"{location}.metrics", metrics_errors)
        metrics.update(compact)
    errors.extend(metrics_errors)
    if "output_artifact" in raw_result and not safe_relative(raw_result.get("output_artifact")):
        errors.append(f"{location}.output_artifact: must be a safe relative path")
    if "error" in raw_result and raw_result.get("error") is not None and not isinstance(raw_result.get("error"), str):
        errors.append(f"{location}.error: must be a string when specified")

    raw_expectations = raw_result.get("expectation_results")
    if raw_expectations is None:
        raw_expectations = raw_result.get("expectations")
    if not isinstance(raw_expectations, list):
        errors.append(f"{location}.expectation_results: expected an array")
        raw_expectations = []

    by_index: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(raw_expectations):
        item_location = f"{location}.expectation_results[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_location}: expected an object")
            continue
        expectation_index = item.get("expectation_index")
        if type(expectation_index) is not int or expectation_index < 1:
            errors.append(f"{item_location}.expectation_index: expected a positive integer")
            continue
        if expectation_index in by_index:
            errors.append(f"{item_location}.expectation_index: duplicate index {expectation_index}")
            continue
        if expectation_index not in expected_by_index:
            errors.append(f"{item_location}.expectation_index: unknown expectation {expectation_index}")
            continue
        status = item.get("status")
        if status not in STATUSES:
            errors.append(f"{item_location}.status: must be pass, fail, blocked, or not-run")
            continue
        reason = item.get("reason")
        if not nonempty(reason):
            errors.append(f"{item_location}.reason: must be a non-empty explanation")
            reason = ""
        evidence_errors: list[str] = []
        evidence = validate_evidence(item.get("evidence", []), f"{item_location}.evidence", evidence_errors)
        errors.extend(evidence_errors)
        if status in {"pass", "fail"} and not evidence:
            errors.append(f"{item_location}.evidence: pass/fail results require at least one evidence locator")
        by_index[expectation_index] = {
            "id": expected_by_index[expectation_index]["id"],
            "text": expected_by_index[expectation_index]["text"],
            "status": status,
            "reason": reason,
            "evidence": evidence,
        }

    missing = sorted(set(expected_by_index) - set(by_index))
    if missing and not allow_partial:
        errors.append(f"{location}.expectation_results: missing expectation indexes {missing}")
    if missing:
        warnings.append(f"{location}: incomplete expectations {missing}")

    ordered_expectations: list[dict[str, Any]] = []
    for index, expected_item in expected_by_index.items():
        if index in by_index:
            item = dict(by_index[index])
        else:
            item = {
                "id": expected_item["id"],
                "text": expected_item["text"],
                "status": "not-run",
                "reason": "No result was recorded for this expectation.",
                "evidence": [],
            }
        item["expectation_index"] = index
        ordered_expectations.append(item)

    passed = sum(item["status"] == "pass" for item in ordered_expectations)
    evidence_count = sum(bool(item["evidence"]) for item in ordered_expectations)
    failures = [
        {
            "expectation_index": item["expectation_index"],
            "expectation": item["text"],
            "status": item["status"],
            "reason": item["reason"],
            "evidence": item["evidence"],
        }
        for item in ordered_expectations
        if item["status"] != "pass"
    ]
    if any(item["status"] == "fail" for item in ordered_expectations):
        status = "failed"
    elif any(item["status"] == "blocked" for item in ordered_expectations):
        status = "blocked"
    elif any(item["status"] == "not-run" for item in ordered_expectations):
        status = "incomplete"
    else:
        status = "passed"
    total = len(expected)
    summary = {
        "case_id": case.get("id"),
        "status": status,
        "expected_expectations": total,
        "passed_expectations": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "evidence_covered": evidence_count,
        "evidence_coverage": round(evidence_count / total, 4) if total else 0.0,
        "failure_reasons": failures,
        "expectations": ordered_expectations,
        "metrics": metrics,
        "error": raw_result.get("error") if nonempty(raw_result.get("error")) else None,
        "output_artifact": raw_result.get("output_artifact") if nonempty(raw_result.get("output_artifact")) else None,
        "ok": status == "passed" and not errors,
    }
    return summary, errors, warnings


def sum_metric(case_summaries: list[dict[str, Any]], field: str) -> int | float:
    return sum(case.get("metrics", {}).get(field, 0) or 0 for case in case_summaries)


def sum_tokens(case_summaries: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"input": 0, "output": 0, "total": 0}
    present = {key: False for key in totals}
    for case in case_summaries:
        tokens = case.get("metrics", {}).get("tokens", {})
        if isinstance(tokens, dict):
            for key in totals:
                if key in tokens:
                    totals[key] += int(tokens[key])
                    present[key] = True
    if not present["total"] and present["input"] and present["output"]:
        totals["total"] = totals["input"] + totals["output"]
        present["total"] = True
    return {key: value for key, value in totals.items() if present[key]}


def summarize_variant(
    name: str,
    raw_variant: Any,
    cases: dict[str, dict[str, Any]],
    *,
    allow_partial: bool,
    only_case: str | None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(raw_variant, dict):
        return {"name": name, "gates": name in {"with_skill", "candidate"}, "ok": False, "errors": ["variant must be an object"]}, [f"variants.{name}: expected an object"], warnings
    raw_cases = raw_variant.get("cases")
    if not isinstance(raw_cases, list):
        return {"name": name, "gates": bool(raw_variant.get("gates", name in {"with_skill", "candidate"})), "ok": False, "errors": ["cases must be an array"]}, [f"variants.{name}.cases: expected an array"], warnings

    expected_cases = cases
    if only_case is not None:
        expected_cases = {only_case: cases[only_case]} if only_case in cases else {}
        if only_case not in cases:
            errors.append(f"--case: unknown catalog case {only_case}")
    by_case: dict[str, Any] = {}
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            errors.append(f"variants.{name}.cases[{index}]: expected an object")
            continue
        key = case_key(raw_case.get("case_id"))
        if not key:
            errors.append(f"variants.{name}.cases[{index}].case_id: expected a positive integer or stable ID")
            continue
        if key in by_case:
            errors.append(f"variants.{name}.cases[{index}].case_id: duplicate case {key}")
        else:
            by_case[key] = raw_case
        if key not in cases:
            errors.append(f"variants.{name}.cases[{index}].case_id: unknown catalog case {key}")

    missing_cases = sorted(set(expected_cases) - set(by_case))
    if missing_cases and not allow_partial:
        errors.append(f"variants.{name}.cases: missing catalog cases {missing_cases}")
    if missing_cases:
        warnings.append(f"variants.{name}: incomplete cases {missing_cases}")

    case_summaries: list[dict[str, Any]] = []
    for key, case in expected_cases.items():
        summary, case_errors, case_warnings = summarize_case(
            case,
            by_case.get(key),
            f"variants.{name}.cases[{key}]",
            allow_partial=allow_partial,
        )
        case_summaries.append(summary)
        errors.extend(case_errors)
        warnings.extend(case_warnings)

    expected_case_count = len(expected_cases)
    passed_cases = sum(case["status"] == "passed" for case in case_summaries)
    expected_expectations = sum(case["expected_expectations"] for case in case_summaries)
    passed_expectations = sum(case["passed_expectations"] for case in case_summaries)
    evidence_covered = sum(case["evidence_covered"] for case in case_summaries)
    if not nonempty(raw_variant.get("label")):
        errors.append(f"variants.{name}.label: must be a non-empty label")
    if "skill_revision" in raw_variant and not nonempty(raw_variant.get("skill_revision")):
        errors.append(f"variants.{name}.skill_revision: must be a non-empty string when specified")
    gates = raw_variant.get("gates")
    if type(gates) is not bool:
        errors.append(f"variants.{name}.gates: must be a boolean")
        gates = False
    summary = {
        "name": name,
        "label": raw_variant.get("label") if nonempty(raw_variant.get("label")) else name,
        "gates": gates,
        "skill_revision": raw_variant.get("skill_revision") if nonempty(raw_variant.get("skill_revision")) else None,
        "complete": not missing_cases and all(case["status"] != "incomplete" for case in case_summaries),
        "expected_cases": expected_case_count,
        "reported_cases": len(by_case),
        "passed_cases": passed_cases,
        "case_pass_rate": round(passed_cases / expected_case_count, 4) if expected_case_count else 0.0,
        "expected_expectations": expected_expectations,
        "passed_expectations": passed_expectations,
        "pass_rate": round(passed_expectations / expected_expectations, 4) if expected_expectations else 0.0,
        "evidence_covered": evidence_covered,
        "evidence_coverage": round(evidence_covered / expected_expectations, 4) if expected_expectations else 0.0,
        "metrics": {
            "duration_ms": sum_metric(case_summaries, "duration_ms"),
            "tool_calls": sum_metric(case_summaries, "tool_calls"),
            "tokens": sum_tokens(case_summaries),
        },
        "cases": case_summaries,
        "failures": [
            {"case_id": case["case_id"], "status": case["status"], "reasons": case["failure_reasons"]}
            for case in case_summaries
            if case["status"] != "passed" or case.get("error")
        ],
        "errors": errors.copy(),
        "ok": not errors and all(case["ok"] for case in case_summaries),
    }
    return summary, errors, warnings


def delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    candidate_metrics = candidate.get("metrics", {})
    baseline_metrics = baseline.get("metrics", {})
    candidate_tokens = candidate_metrics.get("tokens", {})
    baseline_tokens = baseline_metrics.get("tokens", {})
    return {
        "pass_rate_delta": round(candidate.get("pass_rate", 0) - baseline.get("pass_rate", 0), 4),
        "case_pass_rate_delta": round(candidate.get("case_pass_rate", 0) - baseline.get("case_pass_rate", 0), 4),
        "evidence_coverage_delta": round(candidate.get("evidence_coverage", 0) - baseline.get("evidence_coverage", 0), 4),
        "duration_ms_delta": candidate_metrics.get("duration_ms", 0) - baseline_metrics.get("duration_ms", 0),
        "tool_calls_delta": candidate_metrics.get("tool_calls", 0) - baseline_metrics.get("tool_calls", 0),
        "tokens_total_delta": candidate_tokens.get("total", 0) - baseline_tokens.get("total", 0),
    }


def run(catalog_path: Path, run_path: Path, *, allow_partial: bool = False, only_case: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        catalog = load_json(catalog_path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"catalog: {type(exc).__name__}: {exc}"], "warnings": []}
    if validate_catalog is not None:
        catalog_errors = validate_catalog(catalog)
        errors.extend(f"catalog: {error}" for error in catalog_errors)
    cases, case_errors = catalog_cases(catalog)
    errors.extend(case_errors)
    try:
        run_data = load_json(run_path)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"run: {type(exc).__name__}: {exc}"], "warnings": warnings}
    if not isinstance(run_data, dict):
        return {"ok": False, "errors": ["run: expected an object"], "warnings": warnings}
    if run_data.get("schema_version") != 1:
        errors.append("run.schema_version: expected 1")
    run_id = run_data.get("run_id")
    if not stable_id(run_id):
        errors.append("run.run_id: expected a lowercase stable ID")
    if "created_at" in run_data and (not isinstance(run_data.get("created_at"), str) or len(run_data.get("created_at", "")) < 10):
        errors.append("run.created_at: must be a timestamp string of at least 10 characters")
    if "model" in run_data and not nonempty(run_data.get("model")):
        errors.append("run.model: must be a non-empty string when specified")
    variants = run_data.get("variants")
    if not isinstance(variants, dict) or not variants:
        errors.append("run.variants: expected a non-empty object")
        variants = {}
    catalog_meta = run_data.get("catalog")
    catalog_info: dict[str, Any] = {
        "path": str(catalog_path),
        "sha256": sha256_file(catalog_path),
    }
    if catalog_meta is not None:
        if not isinstance(catalog_meta, dict):
            errors.append("run.catalog: expected an object")
        else:
            if not safe_relative(catalog_meta.get("path")):
                errors.append("run.catalog.path: must be a safe relative path")
            else:
                catalog_info["declared_path"] = catalog_meta["path"]
            declared_sha = catalog_meta.get("sha256")
            if not isinstance(declared_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_sha):
                errors.append("run.catalog.sha256: expected a 64-character SHA-256 hex digest")
            elif declared_sha.lower() != catalog_info["sha256"]:
                errors.append("run.catalog.sha256: does not match the supplied catalog")
    variant_summaries: dict[str, Any] = {}
    for name, raw_variant in variants.items():
        if not stable_id(name):
            errors.append(f"run.variants.{name}: variant name must be a stable ID")
            continue
        summary, variant_errors, variant_warnings = summarize_variant(
            name,
            raw_variant,
            cases,
            allow_partial=allow_partial,
            only_case=only_case,
        )
        variant_summaries[name] = summary
        errors.extend(variant_errors)
        warnings.extend(variant_warnings)
    gates = {name: summary for name, summary in variant_summaries.items() if summary.get("gates")}
    if not gates:
        warnings.append("no gating variant declared; report is comparative only")
    comparison: dict[str, Any] = {}
    candidate = variant_summaries.get("with_skill") or variant_summaries.get("candidate")
    if candidate:
        for baseline_name in ("without_skill", "old_skill", "baseline"):
            baseline = variant_summaries.get(baseline_name)
            if baseline:
                comparison[baseline_name] = delta(candidate, baseline)
    gate_passed = bool(gates) and all(summary.get("ok") for summary in gates.values())
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": run_data.get("created_at") if nonempty(run_data.get("created_at")) else None,
        "catalog": catalog_info,
        "model": run_data.get("model") if nonempty(run_data.get("model")) else None,
        "variants": variant_summaries,
        "comparison": comparison,
        "gate_passed": gate_passed,
        "errors": errors,
        "warnings": warnings,
        "not_checked": [
            "whether the recorded expectation decisions are substantively correct",
            "official-source accuracy of the generated article",
            "independent reader identity or reviewer independence",
            "Markdown rendering and external link reachability",
        ],
        "ok": not errors and gate_passed,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="structured evaluation run JSON")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "evals" / "evals.json",
        help="evaluation catalog JSON",
    )
    parser.add_argument("--case", dest="only_case", help="score one catalog case (useful for local iteration)")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="allow missing cases/expectations in an exploratory report; gating still fails",
    )
    parser.add_argument("--json-out", type=Path, help="also write the scorecard JSON to this path")
    args = parser.parse_args()
    report = run(args.cases, args.run, allow_partial=args.allow_partial, only_case=args.only_case)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(serialized + "\n", encoding="utf-8")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

