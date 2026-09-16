#!/usr/bin/env python3
"""Validate a canonical developer whitepaper manifest without third-party dependencies."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable
from urllib.parse import urlsplit


ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
COMMIT_RE = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
RELEASE_STATES = {"draft", "published"}
SOURCE_KINDS = {"git", "web", "file"}
ARTICLE_KINDS = {"article", "appendix"}
VERIFICATION_STATES = {"draft", "reviewed", "blocked"}
READER_TEST_STATES = {"unrun", "passed", "failed", "not-applicable"}
CLAIM_KINDS = {"fact", "inference", "recommendation", "unknown"}
CLAIM_STATES = {"proposed", "verified", "blocked"}


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\x00" not in value


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and len(value) <= 120 and bool(ID_RE.fullmatch(value))


def valid_url(value: Any) -> bool:
    if not isinstance(value, str) or "\x00" in value:
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return not (
        path.is_absolute()
        or value == "."
        or ".." in path.parts
        or "\\" in value
        or ":" in value
    )


def unique(values: Iterable[Any]) -> bool:
    seen: list[Any] = []
    for value in values:
        if any(value == previous for previous in seen):
            return False
        seen.append(value)
    return True


class Validator:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root.resolve() if root is not None else None
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checks: list[str] = []

    def error(self, location: str, message: str) -> None:
        self.errors.append(f"{location}: {message}")

    def warning(self, location: str, message: str) -> None:
        self.warnings.append(f"{location}: {message}")

    def require_object(self, value: Any, location: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            self.error(location, "expected an object")
            return {}
        return value

    def require_list(self, value: Any, location: str, *, non_empty: bool = False) -> list[Any]:
        if not isinstance(value, list):
            self.error(location, "expected an array")
            return []
        if non_empty and not value:
            self.error(location, "must not be empty")
        return value

    def check_id(self, value: Any, location: str) -> str:
        if not valid_id(value):
            self.error(location, "expected a lowercase stable ID matching [a-z0-9][a-z0-9._-]*")
            return ""
        return value

    def check_text(self, value: Any, location: str) -> str:
        if not nonempty(value):
            self.error(location, "expected a non-empty string without NUL characters")
            return ""
        return value

    def check_path(self, value: Any, location: str) -> str:
        if not safe_relative(value):
            self.error(location, "expected a safe relative POSIX path")
            return ""
        return value

    def check_file(self, value: Any, location: str, base: Path | None = None) -> None:
        path_value = self.check_path(value, location)
        if not path_value or self.root is None:
            return
        base = base or self.root
        try:
            candidate = (base / PurePosixPath(path_value)).resolve()
            candidate.relative_to(self.root)
        except (OSError, RuntimeError, ValueError):
            self.error(location, "path escapes the validation root or cannot be resolved")
            return
        if not candidate.is_file():
            self.error(location, f"file does not exist: {path_value}")

    def check_directory(self, value: Any, location: str) -> Path | None:
        path_value = "." if value == "." else self.check_path(value, location)
        if not path_value or self.root is None:
            return None
        try:
            candidate = (self.root / PurePosixPath(path_value)).resolve()
            candidate.relative_to(self.root)
        except (OSError, RuntimeError, ValueError):
            self.error(location, "path escapes the validation root or cannot be resolved")
            return None
        if not candidate.is_dir():
            self.error(location, f"directory does not exist: {path_value}")
            return None
        return candidate

    def check_unique_ids(self, items: list[Any], location: str, field: str = "id") -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        ids: list[str] = []
        for index, raw in enumerate(items):
            item = self.require_object(raw, f"{location}[{index}]")
            item_id = self.check_id(item.get(field), f"{location}[{index}].{field}")
            if item_id:
                ids.append(item_id)
                if item_id in result:
                    self.error(f"{location}[{index}].{field}", f"duplicate ID: {item_id}")
                else:
                    result[item_id] = item
        return result

    def validate_source_registry(self, raw_sources: Any) -> dict[str, dict[str, Any]]:
        sources = self.require_list(raw_sources, "sources", non_empty=True)
        result = self.check_unique_ids(sources, "sources")
        for index, raw in enumerate(sources):
            location = f"sources[{index}]"
            source = self.require_object(raw, location)
            source_id = source.get("id")
            if not valid_id(source_id):
                continue
            kind = source.get("kind")
            if kind not in SOURCE_KINDS:
                self.error(f"{location}.kind", "must be git, web, or file")
                continue
            if type(source.get("official")) is not bool:
                self.error(f"{location}.official", "must be a boolean")
            if "repository" in source and not valid_url(source.get("repository")):
                self.error(f"{location}.repository", "must be an HTTP(S) URL without credentials")
            if "url" in source and not valid_url(source.get("url")):
                self.error(f"{location}.url", "must be an HTTP(S) URL without credentials")
            if "accessed" in source and (not isinstance(source.get("accessed"), str) or len(source.get("accessed", "")) < 10):
                self.error(f"{location}.accessed", "must be a date or timestamp string of at least 10 characters")
            if kind == "git" and not valid_url(source.get("repository")):
                self.error(f"{location}.repository", "git sources require repository")
            if kind == "web":
                if not valid_url(source.get("url")):
                    self.error(f"{location}.url", "web sources require url")
                if not isinstance(source.get("accessed"), str) or len(source.get("accessed", "")) < 10:
                    self.error(f"{location}.accessed", "web sources require accessed (at least 10 characters)")
            if kind == "file":
                self.check_path(source.get("path"), f"{location}.path")
        self.checks.append("source registry IDs, kinds and URL/path shapes")
        return result

    def validate_policy(self, raw_policy: Any) -> tuple[dict[str, Any], set[str]]:
        policy = self.require_object(raw_policy, "policy")
        allowed = self.require_list(policy.get("allowed_release_channels"), "policy.allowed_release_channels", non_empty=True)
        allowed_values: list[str] = []
        for index, value in enumerate(allowed):
            if not valid_id(value):
                self.error(f"policy.allowed_release_channels[{index}]", "must be a stable ID")
            else:
                allowed_values.append(value)
        if not unique(allowed_values):
            self.error("policy.allowed_release_channels", "values must be unique")
        included = self.require_list(policy.get("included_release_channels"), "policy.included_release_channels", non_empty=True)
        included_values: list[str] = []
        for index, value in enumerate(included):
            if not valid_id(value):
                self.error(f"policy.included_release_channels[{index}]", "must be a stable ID")
            else:
                included_values.append(value)
        if not unique(included_values):
            self.error("policy.included_release_channels", "values must be unique")
        for channel in included_values:
            if channel not in allowed_values:
                self.error("policy.included_release_channels", f"channel is not allowed: {channel}")
        if policy.get("version_fallback") != "explicit-only":
            self.error("policy.version_fallback", "must be explicit-only; cross-version fallback is not implicit")
        self.check_text(policy.get("default_version"), "policy.default_version")
        required = self.require_list(policy.get("required_appendices", []), "policy.required_appendices")
        for index, value in enumerate(required):
            self.check_id(value, f"policy.required_appendices[{index}]")
        if not unique(required):
            self.error("policy.required_appendices", "values must be unique")
        expected = policy.get("expected_body_groups")
        if expected is not None and (type(expected) is not int or expected < 1):
            self.error("policy.expected_body_groups", "must be a positive integer when specified")
        self.checks.append("release-channel policy and explicit version fallback")
        return policy, set(required)

    def validate_source_lock(
        self,
        lock: dict[str, Any],
        location: str,
        sources: dict[str, dict[str, Any]],
    ) -> str:
        source_id = self.check_id(lock.get("source_id"), f"{location}.source_id")
        if not source_id:
            return ""
        if source_id not in sources:
            self.error(f"{location}.source_id", f"unknown source: {source_id}")
            return source_id
        if not isinstance(lock.get("accessed"), str) or len(lock.get("accessed", "")) < 10:
            self.error(f"{location}.accessed", "must be a date or timestamp string of at least 10 characters")
        source_kind = sources[source_id].get("kind")
        if source_kind == "git":
            self.check_text(lock.get("ref"), f"{location}.ref")
            commit = lock.get("commit")
            if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
                self.error(f"{location}.commit", "git sources require a complete 40 or 64 character commit hash")
        elif "commit" in lock and lock.get("commit") is not None:
            self.warning(f"{location}.commit", "commit is ignored for non-git sources")
        return source_id

    def validate_evidence(
        self,
        raw_evidence: Any,
        location: str,
        source_locks: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        evidence = self.require_list(raw_evidence, location)
        result = self.check_unique_ids(evidence, location)
        for index, raw in enumerate(evidence):
            item_location = f"{location}[{index}]"
            item = self.require_object(raw, item_location)
            evidence_id = item.get("id")
            if not valid_id(evidence_id):
                continue
            source_id = item.get("source_id")
            if source_id is not None:
                source_id = self.check_id(source_id, f"{item_location}.source_id")
                if source_id not in source_locks:
                    self.error(f"{item_location}.source_id", f"source is not locked for this version: {source_id}")
                source_kind = source_locks.get(source_id, {}).get("_source_kind")
                if source_kind == "git" and not nonempty(item.get("path")):
                    self.error(f"{item_location}.path", "git evidence requires a repository path")
                if nonempty(item.get("path")):
                    self.check_path(item.get("path"), f"{item_location}.path")
            elif not valid_url(item.get("url")):
                self.error(f"{item_location}.source_id", "provide source_id or a direct HTTP(S) url")
            if "url" in item and not valid_url(item.get("url")):
                self.error(f"{item_location}.url", "must be an HTTP(S) URL without credentials")
            location_fields = [item.get(field) for field in ("path", "locator", "symbol", "url")]
            if not any(nonempty(value) for value in location_fields):
                self.error(item_location, "evidence requires path, locator, symbol, or url")
            claim_ids = self.require_list(item.get("claim_ids", []), f"{item_location}.claim_ids")
            for claim_index, claim_id in enumerate(claim_ids):
                self.check_id(claim_id, f"{item_location}.claim_ids[{claim_index}]")
            if not unique(claim_ids):
                self.error(f"{item_location}.claim_ids", "values must be unique")
        return result

    def validate_article(
        self,
        raw: Any,
        location: str,
        version_id: str,
        source_locks: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        article = self.require_object(raw, location)
        if article.get("schema_version") != 1:
            self.error(f"{location}.schema_version", "expected article schema version 1")
        article_id = self.check_id(article.get("id"), f"{location}.id")
        self.check_text(article.get("title"), f"{location}.title")
        if article.get("version") != version_id:
            self.error(f"{location}.version", f"must equal containing version {version_id}")
        if article.get("kind") not in ARTICLE_KINDS:
            self.error(f"{location}.kind", "must be article or appendix")
        self.check_text(article.get("type"), f"{location}.type")
        if article.get("normative_level") not in {"normative", "explanatory", "practical", "editorial", "unknown"}:
            self.error(f"{location}.normative_level", "must be normative, explanatory, practical, editorial, or unknown")
        if article.get("verification") not in VERIFICATION_STATES:
            self.error(f"{location}.verification", "must be draft, reviewed, or blocked")
        if article.get("authority") is not None and article.get("authority") not in {"upstream", "document-policy"}:
            self.error(f"{location}.authority", "must be upstream or document-policy when specified")
        self.check_path(article.get("slug"), f"{location}.slug")
        self.check_file(article.get("file"), f"{location}.file", self._content_root)
        diagrams = self.require_list(article.get("diagrams", []), f"{location}.diagrams")
        for diagram_index, diagram in enumerate(diagrams):
            self.check_file(diagram, f"{location}.diagrams[{diagram_index}]", self._asset_root)
        for field in ("audience", "prerequisites", "next_articles", "boundaries", "claim_ids"):
            values = self.require_list(article.get(field, []), f"{location}.{field}")
            for value_index, value in enumerate(values):
                if field in {"prerequisites", "next_articles", "claim_ids"}:
                    self.check_id(value, f"{location}.{field}[{value_index}]")
                else:
                    self.check_text(value, f"{location}.{field}[{value_index}]")
            if not unique(values):
                self.error(f"{location}.{field}", "values must be unique")
        reader_test = article.get("reader_test")
        if reader_test is not None:
            reader_test = self.require_object(reader_test, f"{location}.reader_test")
            if reader_test.get("status") not in READER_TEST_STATES:
                self.error(f"{location}.reader_test.status", "must be unrun, passed, failed, or not-applicable")
            for field in ("snapshot", "result_file"):
                if field in reader_test:
                    self.check_path(reader_test.get(field), f"{location}.reader_test.{field}")
        if article.get("verification") == "reviewed":
            if not isinstance(reader_test, dict) or reader_test.get("status") != "passed":
                self.error(f"{location}.verification", "reviewed articles require reader_test.status=passed")
        evidence = self.validate_evidence(article.get("evidence"), f"{location}.evidence", source_locks)
        article["_evidence_by_id"] = evidence
        return article

    def validate_claims(
        self,
        raw_claims: Any,
        location: str,
        articles_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        claims = self.require_list(raw_claims, location)
        result = self.check_unique_ids(claims, location)
        for index, raw in enumerate(claims):
            item_location = f"{location}[{index}]"
            claim = self.require_object(raw, item_location)
            claim_id = claim.get("id")
            if not valid_id(claim_id):
                continue
            article_id = self.check_id(claim.get("article_id"), f"{item_location}.article_id")
            article = articles_by_id.get(article_id)
            if article is None:
                self.error(f"{item_location}.article_id", f"unknown article: {article_id}")
            if claim.get("kind") not in CLAIM_KINDS:
                self.error(f"{item_location}.kind", "must be fact, inference, recommendation, or unknown")
            self.check_text(claim.get("text"), f"{item_location}.text")
            if claim.get("status") not in CLAIM_STATES:
                self.error(f"{item_location}.status", "must be proposed, verified, or blocked")
            evidence_ids = self.require_list(claim.get("evidence_ids"), f"{item_location}.evidence_ids")
            if claim.get("kind") in {"fact", "inference"} and claim.get("status") == "verified" and not evidence_ids:
                self.error(f"{item_location}.evidence_ids", "verified facts and inferences require evidence")
            if not unique(evidence_ids):
                self.error(f"{item_location}.evidence_ids", "values must be unique")
            if article is not None:
                evidence_by_id = article.get("_evidence_by_id", {})
                for evidence_index, evidence_id in enumerate(evidence_ids):
                    self.check_id(evidence_id, f"{item_location}.evidence_ids[{evidence_index}]")
                    if evidence_id not in evidence_by_id:
                        self.error(f"{item_location}.evidence_ids[{evidence_index}]", f"evidence is not declared by article: {evidence_id}")
                article_claim_ids = article.get("claim_ids", [])
                if claim_id not in article_claim_ids:
                    self.error(f"{item_location}.id", f"claim is not listed in article {article_id}.claim_ids")
        return result

    def validate_version(
        self,
        raw: Any,
        location: str,
        policy: dict[str, Any],
        required_appendices: set[str],
        sources: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        version = self.require_object(raw, location)
        version_id = self.check_text(version.get("id"), f"{location}.id")
        channel = self.check_id(version.get("release_channel"), f"{location}.release_channel")
        allowed_channels = policy.get("allowed_release_channels", [])
        if channel and channel not in allowed_channels:
            self.error(f"{location}.release_channel", f"channel is not allowed: {channel}")
        if version.get("publication_state") not in RELEASE_STATES:
            self.error(f"{location}.publication_state", "must be draft or published")
        revision = version.get("documentation_revision")
        if type(revision) is not int or revision < 1:
            self.error(f"{location}.documentation_revision", "must be a positive integer")
        self._content_root = self.check_directory(version.get("content_root"), f"{location}.content_root")
        asset_root_value = version.get("asset_root")
        if asset_root_value is None:
            self._asset_root = None
        else:
            self._asset_root = self.check_directory(asset_root_value, f"{location}.asset_root")
        locks = self.require_list(version.get("source_locks"), f"{location}.source_locks", non_empty=True)
        source_locks: dict[str, dict[str, Any]] = {}
        for index, raw_lock in enumerate(locks):
            lock_location = f"{location}.source_locks[{index}]"
            lock = self.require_object(raw_lock, lock_location)
            source_id = self.validate_source_lock(lock, lock_location, sources)
            if source_id:
                if source_id in source_locks:
                    self.error(f"{lock_location}.source_id", f"duplicate source lock: {source_id}")
                else:
                    merged = dict(lock)
                    merged["_source_kind"] = sources.get(source_id, {}).get("kind")
                    source_locks[source_id] = merged
        groups = self.require_list(version.get("groups"), f"{location}.groups", non_empty=True)
        groups_by_id = self.check_unique_ids(groups, f"{location}.groups")
        articles = self.require_list(version.get("articles"), f"{location}.articles", non_empty=True)
        articles_by_id = self.check_unique_ids(articles, f"{location}.articles")
        for index, raw_article in enumerate(articles):
            self.validate_article(raw_article, f"{location}.articles[{index}]", version_id, source_locks)
        # Rebuild after validation so cross references use the original IDs even when one item was malformed.
        articles_by_id = {key: value for key, value in articles_by_id.items() if key}
        for article_id, article in articles_by_id.items():
            next_articles = article.get("next_articles", [])
            for index, next_id in enumerate(next_articles):
                if next_id not in articles_by_id:
                    self.error(f"{location}.articles[{article_id}].next_articles[{index}]", f"unknown article: {next_id}")
            for index, prerequisite in enumerate(article.get("prerequisites", [])):
                if prerequisite not in articles_by_id:
                    self.error(f"{location}.articles[{article_id}].prerequisites[{index}]", f"unknown article: {prerequisite}")
        claims_by_id = self.validate_claims(version.get("claims", []), f"{location}.claims", articles_by_id)
        membership: list[str] = []
        appendix_membership: set[str] = set()
        body_group_count = 0
        for index, raw_group in enumerate(groups):
            group_location = f"{location}.groups[{index}]"
            group = self.require_object(raw_group, group_location)
            self.check_id(group.get("id"), f"{group_location}.id")
            self.check_text(group.get("title"), f"{group_location}.title")
            if group.get("kind") not in {"body", "appendix"}:
                self.error(f"{group_location}.kind", "must be body or appendix")
            order = group.get("order")
            if type(order) is not int or order < 0:
                self.error(f"{group_location}.order", "must be a non-negative integer")
            members = self.require_list(group.get("articles"), f"{group_location}.articles", non_empty=True)
            for member_index, member in enumerate(members):
                member_id = self.check_id(member, f"{group_location}.articles[{member_index}]")
                membership.append(member_id)
                if member_id not in articles_by_id:
                    self.error(f"{group_location}.articles[{member_index}]", f"unknown article: {member_id}")
                if group.get("kind") == "appendix":
                    appendix_membership.add(member_id)
            if group.get("kind") == "body":
                body_group_count += 1
        if not unique([member for member in membership if member]):
            duplicates = [value for value, count in Counter(membership).items() if value and count > 1]
            self.error(f"{location}.groups.articles", f"each article must appear once; duplicates: {', '.join(duplicates)}")
        for article_id in sorted(set(articles_by_id) - set(membership)):
            self.error(f"{location}.groups.articles", f"article is missing from navigation: {article_id}")
        for article_id in sorted(set(membership) - set(articles_by_id)):
            self.error(f"{location}.groups.articles", f"navigation references unknown article: {article_id}")
        for article_id, article in articles_by_id.items():
            if article.get("kind") == "appendix" and article_id not in appendix_membership:
                self.error(f"{location}.articles[{article_id}].kind", "appendices must belong to an appendix navigation group")
            if article.get("kind") == "article" and article_id in appendix_membership:
                self.error(f"{location}.articles[{article_id}].kind", "body articles cannot belong to an appendix navigation group")
        for required_id in required_appendices:
            article = articles_by_id.get(required_id)
            if article is None:
                self.error(f"{location}.required_appendices", f"required appendix is missing: {required_id}")
            elif article.get("kind") != "appendix":
                self.error(f"{location}.required_appendices", f"required item is not an appendix: {required_id}")
        expected_groups = policy.get("expected_body_groups")
        if type(expected_groups) is int and expected_groups != body_group_count:
            self.error(f"{location}.groups", f"expected {expected_groups} body groups, found {body_group_count}")
        if version.get("publication_state") == "published":
            for article_id, article in articles_by_id.items():
                if article.get("verification") != "reviewed":
                    self.error(f"{location}.articles[{article_id}].verification", "published versions require reviewed articles")
        self.checks.append(f"version {version_id or '<invalid>'}: source locks, navigation, articles, evidence and claims")
        return version

    def validate(self, data: Any, version_id: str | None = None) -> list[str]:
        manifest = self.require_object(data, "root")
        if manifest.get("schema_version") != 1:
            self.error("schema_version", "expected manifest schema version 1")
        project = self.require_object(manifest.get("project"), "project")
        self.check_id(project.get("id"), "project.id")
        self.check_text(project.get("name"), "project.name")
        if "repository" in project and not valid_url(project.get("repository")):
            self.error("project.repository", "must be an HTTP(S) URL without credentials")
        policy, required_appendices = self.validate_policy(manifest.get("policy"))
        sources = self.validate_source_registry(manifest.get("sources"))
        versions = self.require_list(manifest.get("versions"), "versions", non_empty=True)
        version_map = self.check_unique_ids(versions, "versions")
        version_ids = list(version_map)
        default_version = policy.get("default_version")
        if default_version not in version_map:
            self.error("policy.default_version", f"unknown version: {default_version}")
        if version_id is not None and version_id not in version_map:
            self.error("version", f"unknown version: {version_id}")
        selected = [
            (index, raw)
            for index, raw in enumerate(versions)
            if version_id is None or (isinstance(raw, dict) and raw.get("id") == version_id)
        ]
        for index, raw in selected:
            self.validate_version(raw, f"versions[{index}]", policy, required_appendices, sources)
        self.checks.insert(0, "manifest schema version, project identity and version selection")
        return self.errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default=Path(__file__).resolve().parents[1] / "manifests" / "example.whitepaper.json",
        type=Path,
        help="canonical whitepaper manifest JSON",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository root used to verify content_root, asset_root and article files",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="validate one version only; metadata is still checked for the whole manifest",
    )
    args = parser.parse_args()
    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [f"input: {type(exc).__name__}: {exc}"]}, ensure_ascii=False, indent=2))
        return 2
    validator = Validator(args.root)
    validator.validate(data, args.version)
    result = {
        "ok": not validator.errors,
        "manifest": str(args.path),
        "version": args.version,
        "errors": validator.errors,
        "warnings": validator.warnings,
        "checks_executed": validator.checks,
        "not_checked": [
            "JSON Schema evaluation by an external validator",
            "claim accuracy or evidential support",
            "Markdown/frontmatter parsing",
            "network reachability of source URLs",
            "Mermaid syntax and rendered page behavior",
            "independent reader answers",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if validator.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

