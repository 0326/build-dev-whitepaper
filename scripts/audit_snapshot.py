#!/usr/bin/env python3
"""Read-only structural audit of an exported whitepaper snapshot (Python 3.9+)."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import urlsplit


class Audit:
    def __init__(self):
        self.errors = []
        self.skipped = []
        self.checked = []

    def error(self, location, message):
        self.errors.append({"location": location, "message": message})

    def obj(self, value, location):
        if not isinstance(value, dict):
            self.error(location, "Expected an object.")
            return {}
        return value

    def array(self, value, location):
        if not isinstance(value, list):
            self.error(location, "Expected an array.")
            return []
        return value

    def string(self, value, location):
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            self.error(location, "Expected a nonempty string without NUL characters.")
            return ""
        return value

    def strings(self, value, location):
        result = []
        for i, item in enumerate(self.array(value, location)):
            text = self.string(item, f"{location}[{i}]")
            if text:
                result.append(text)
        return result

    def choice(self, value, choices, location):
        if not isinstance(value, str) or value not in choices:
            self.error(location, "Expected one of: " + ", ".join(choices))

    def unique(self, values, location):
        for value, count in Counter(values).items():
            if count > 1:
                self.error(location, f"Duplicate value: {value}")

    def relative(self, value, location):
        value = self.string(value, location)
        if not value:
            return None
        path = PurePosixPath(value)
        if (path.is_absolute() or ".." in path.parts or "\\" in value
                or ":" in value or value == "."):
            self.error(location, "Expected a safe relative POSIX file path.")
            return None
        return path

    def file(self, root, value, location):
        relative = self.relative(value, location)
        if relative is None or root is None:
            return None
        try:
            path = (root / relative).resolve()
            path.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            self.error(location, "Path escapes its root or cannot be resolved.")
            return None
        if not path.is_file():
            self.error(location, f"File does not exist: {value}")
        return str(path)

    def git(self, repo, arguments, location):
        env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0",
                   GIT_OPTIONAL_LOCKS="0")
        try:
            result = subprocess.run(["git", "-C", str(repo), *arguments],
                                    capture_output=True, text=True, timeout=10, env=env)
        except (OSError, subprocess.TimeoutExpired):
            self.error(location, "Local Git check could not run or timed out.")
            return None
        if result.returncode:
            self.error(location, "Local Git object/ref check failed; required data may be absent.")
            return None
        return result.stdout.strip()


def audit_snapshot(data, base, upstreams):
    audit = Audit()
    data = audit.obj(data, "snapshot")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        audit.error("schema_version", "Expected schema version 1.")
    audit.string(data.get("project"), "project")
    version = audit.string(data.get("version"), "version")
    policy = audit.obj(data.get("policy"), "policy")
    channels = audit.strings(policy.get("allowed_release_channels"), "policy.allowed_release_channels")
    if not channels:
        audit.error("policy.allowed_release_channels", "At least one project-defined channel is required.")
    audit.choice(data.get("release_channel"), channels, "release_channel")
    audit.choice(data.get("publication_state"), ["draft", "published"], "publication_state")
    required = audit.strings(policy.get("required_appendices", []), "policy.required_appendices")
    expected_groups = policy.get("expected_body_groups")
    if expected_groups is not None and (type(expected_groups) is not int or expected_groups < 1):
        audit.error("policy.expected_body_groups", "Expected a positive integer when specified.")

    roots = audit.obj(data.get("roots"), "roots")
    resolved_roots = {}
    for name in ("content", "assets"):
        value = audit.string(roots.get(name), f"roots.{name}")
        try:
            resolved_roots[name] = (base / value).resolve() if value else None
        except (OSError, RuntimeError, ValueError):
            audit.error(f"roots.{name}", "Cannot resolve this root.")
            resolved_roots[name] = None
    content_root = resolved_roots["content"]
    if content_root is not None and not content_root.is_dir():
        audit.error("roots.content", "Content root is not a directory.")

    sources = {}
    for i, raw in enumerate(audit.array(data.get("sources"), "sources")):
        loc = f"sources[{i}]"
        source = audit.obj(raw, loc)
        source_id = audit.string(source.get("id"), loc + ".id")
        if not source_id:
            continue
        if source_id in sources:
            audit.error(loc + ".id", "Duplicate source ID.")
            continue
        sources[source_id] = source
        repository = audit.string(source.get("repository"), loc + ".repository")
        try:
            url = urlsplit(repository)
            valid_url = url.scheme in ("https", "http") and url.hostname and not url.username and not url.password
        except ValueError:
            valid_url = False
        if not valid_url:
            audit.error(loc + ".repository", "Expected a canonical HTTP(S) repository URL without credentials.")
        ref = audit.string(source.get("ref"), loc + ".ref")
        commit = audit.string(source.get("commit"), loc + ".commit")
        if not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", commit):
            audit.error(loc + ".commit", "Expected a complete verified Git commit hash.")
            continue
        if source_id not in upstreams:
            audit.skipped.append({"source": source_id, "check": "commit, ref binding and evidence paths; no local checkout supplied"})
            continue
        repo = upstreams[source_id]
        actual = audit.git(repo, ["rev-parse", "--verify", "--end-of-options", commit + "^{commit}"], loc + ".commit")
        if actual is not None and actual.lower() != commit.lower():
            audit.error(loc + ".commit", "Resolved commit differs from the declared commit.")
        bound = audit.git(repo, ["rev-parse", "--verify", "--end-of-options", ref + "^{commit}"], loc + ".ref") if ref else None
        if bound is not None and bound.lower() != commit.lower():
            audit.error(loc + ".ref", "Ref resolves to a different commit.")
        if actual and bound and actual.lower() == bound.lower() == commit.lower():
            audit.checked.append(f"Pinned commit and ref binding: {source_id}")
    for source_id in upstreams:
        if source_id not in sources:
            audit.error("--upstream", f"Unknown source ID: {source_id}")

    articles = {}
    slugs, files, evidence_checked = [], [], set()
    for i, raw in enumerate(audit.array(data.get("articles"), "articles")):
        loc = f"articles[{i}]"
        article = audit.obj(raw, loc)
        article_id = audit.string(article.get("id"), loc + ".id")
        if article_id in articles:
            audit.error(loc + ".id", "Duplicate article ID.")
        if article_id:
            articles[article_id] = article
        slug = audit.string(article.get("slug"), loc + ".slug")
        if slug:
            slugs.append(slug)
        audit.string(article.get("title"), loc + ".title")
        article_version = audit.string(article.get("version"), loc + ".version")
        if article_version != version:
            audit.error(loc + ".version", "Article metadata differs from the snapshot version.")
        audit.choice(article.get("verification"), ["draft", "reviewed"], loc + ".verification")
        if data.get("publication_state") == "published" and article.get("verification") != "reviewed":
            audit.error(loc + ".verification", "Published snapshots require reviewed articles.")
        audit.choice(article.get("authority"), ["upstream", "document-policy"], loc + ".authority")
        file_path = audit.file(content_root, article.get("file"), loc + ".file")
        if file_path:
            files.append(file_path)
        for j, diagram in enumerate(audit.array(article.get("diagrams"), loc + ".diagrams")):
            audit.file(resolved_roots["assets"], diagram, f"{loc}.diagrams[{j}]")
        evidence = audit.array(article.get("sources"), loc + ".sources")
        if article.get("authority") == "upstream" and not evidence:
            audit.error(loc + ".sources", "Upstream claims require at least one declared evidence path.")
        for j, raw_reference in enumerate(evidence):
            ref_loc = f"{loc}.sources[{j}]"
            reference = audit.obj(raw_reference, ref_loc)
            source_id = audit.string(reference.get("source"), ref_loc + ".source")
            relative = audit.relative(reference.get("path"), ref_loc + ".path")
            if source_id not in sources:
                audit.error(ref_loc + ".source", "Unknown evidence source.")
                continue
            commit = sources[source_id].get("commit", "")
            if (source_id not in upstreams or relative is None or not isinstance(commit, str)
                    or not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", commit)):
                continue
            key = (source_id, str(relative))
            if key in evidence_checked:
                continue
            evidence_checked.add(key)
            kind = audit.git(upstreams[source_id], ["cat-file", "-t", f"{commit}:{relative}"], ref_loc)
            if kind is not None and kind != "blob":
                audit.error(ref_loc, "Evidence path is not a file at the pinned commit.")
            elif kind == "blob":
                audit.checked.append(f"Pinned evidence file: {source_id}:{relative}")
    if not articles:
        audit.error("articles", "At least one article is required.")
    audit.unique(slugs, "articles.slug")
    audit.unique(files, "articles.file")

    group_ids, navigation, appendix_ids = [], [], set()
    body_count = 0
    for i, raw in enumerate(audit.array(data.get("groups"), "groups")):
        loc = f"groups[{i}]"
        group = audit.obj(raw, loc)
        group_id = audit.string(group.get("id"), loc + ".id")
        if group_id:
            group_ids.append(group_id)
        audit.string(group.get("title"), loc + ".title")
        audit.choice(group.get("kind"), ["body", "appendix"], loc + ".kind")
        members = audit.strings(group.get("articles"), loc + ".articles")
        if not members:
            audit.error(loc + ".articles", "Navigation groups must not be empty.")
        navigation.extend(members)
        if group.get("kind") == "appendix":
            appendix_ids.update(members)
        elif group.get("kind") == "body":
            body_count += 1
    audit.unique(group_ids, "groups.id")
    audit.unique(navigation, "groups.articles")
    for article_id in sorted(set(navigation) - set(articles)):
        audit.error("groups.articles", f"Unknown article: {article_id}")
    for article_id in sorted(set(articles) - set(navigation)):
        audit.error("groups.articles", f"Article missing from navigation: {article_id}")
    for article_id in sorted(set(required) - appendix_ids):
        audit.error("policy.required_appendices", f"Required appendix missing: {article_id}")
    if type(expected_groups) is int and expected_groups > 0 and body_count != expected_groups:
        audit.error("policy.expected_body_groups", f"Expected {expected_groups} body groups, found {body_count}.")
    audit.checked.insert(0, "Snapshot metadata, declared policy, navigation, article and diagram files")
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Temporary audit JSON exported from actual content metadata")
    parser.add_argument("--upstream", action="append", default=[], metavar="SOURCE_ID=CHECKOUT",
                        help="Enable fixed-commit evidence checks using a local Git checkout")
    args = parser.parse_args()
    upstreams = {}
    for mapping in args.upstream:
        source_id, separator, path = mapping.partition("=")
        if not separator or not source_id or not path or source_id in upstreams:
            parser.error("Each --upstream must have a unique SOURCE_ID=CHECKOUT mapping.")
        upstreams[source_id] = Path(path).expanduser()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        audit = audit_snapshot(data, args.input.resolve().parent, upstreams)
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        audit = Audit()
        audit.error("input", f"Cannot load or resolve audit input: {type(exc).__name__}")
    result = {
        "ok": not audit.errors,
        "errors": audit.errors,
        "checks_executed": audit.checked,
        "skipped": audit.skipped,
        "not_checked": ["source ownership", "claim accuracy or evidential support", "Markdown/frontmatter parsing",
                        "network links", "diagram syntax or generated asset freshness", "example execution",
                        "page rendering and interactions"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if audit.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
