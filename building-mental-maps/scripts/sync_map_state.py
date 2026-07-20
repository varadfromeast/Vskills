#!/usr/bin/env python3
"""Inspect and checkpoint deterministic mental-map synchronization state.

The state file is a cursor, not part of the mental-map model. ``status`` is
read-only. ``checkpoint`` atomically records the exact target reported by
``status`` and requires a validation receipt bound to that exact target and map.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import validation_receipt

from validate_mental_map import (
    Reporter,
    clean_code_item,
    extract_list_after,
    matches,
    parse_frontmatter,
    repo_files,
    split_exclusion,
)


SCHEMA_VERSION = 1
DEFAULT_STATE_NAME = ".mental-map-state.json"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class SyncStateError(RuntimeError):
    """A deterministic state snapshot could not be produced."""


class FingerprintMismatch(SyncStateError):
    """The checkpoint target changed after status was inspected."""


@dataclass(frozen=True)
class CoverageScope:
    path: Path
    note_sha256: str
    contract_sha256: str
    includes: tuple[str, ...]
    excludes: tuple[tuple[str, str], ...]
    selected: tuple[str, ...]
    inventory_strategy: str
    warnings: tuple[str, ...]


def prefixed_sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def run_git(repo: Path, arguments: list[str], *, check: bool = True) -> bytes:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=False,
    )
    if check and result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise SyncStateError(message or f"git {' '.join(arguments)} failed")
    return result.stdout if result.returncode == 0 else b""


def resolve_repo(path: str | Path) -> tuple[Path, bool]:
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_dir():
        raise SyncStateError(f"repository does not exist: {candidate}")
    top_level = run_git(candidate, ["rev-parse", "--show-toplevel"], check=False)
    if not top_level:
        return candidate, False
    return Path(os.fsdecode(top_level).strip()).resolve(), True


def resolve_coverage(map_dir: Path, value: str | None) -> Path:
    if value:
        try:
            return validation_receipt.resolve_map_path(
                map_dir,
                value,
                default_name=None,
                label="coverage note",
                allowed_suffixes={".md"},
                require_file=True,
            )
        except validation_receipt.ValidationReceiptError as error:
            raise SyncStateError(str(error)) from error

    candidates: list[Path] = []
    for path in sorted(map_dir.rglob("*.md")):
        try:
            candidate = validation_receipt.resolve_map_path(
                map_dir,
                path.relative_to(map_dir),
                default_name=None,
                label="auto-detected coverage note",
                allowed_suffixes={".md"},
                require_file=True,
            )
        except validation_receipt.ValidationReceiptError as error:
            raise SyncStateError(str(error)) from error
        text = candidate.read_text(encoding="utf-8", errors="replace")
        frontmatter, _body = parse_frontmatter(text)
        if frontmatter.get("type") == "mental-map-coverage":
            candidates.append(candidate)
    if len(candidates) != 1:
        raise SyncStateError(
            "coverage note must be supplied when the map directory does not "
            "contain exactly one mental-map-coverage note"
        )
    return candidates[0]


def load_coverage_scope(repo: Path, coverage_path: Path) -> CoverageScope:
    note_bytes = coverage_path.read_bytes()
    text = note_bytes.decode("utf-8", errors="replace")
    frontmatter, body = parse_frontmatter(text)
    if frontmatter.get("type") != "mental-map-coverage":
        raise SyncStateError(f"{coverage_path.name}: type must be mental-map-coverage")

    includes = tuple(
        sorted(
            set(
                clean_code_item(item)
                for item in extract_list_after("Include:", body)
            )
        )
    )
    excludes = tuple(
        sorted(
            set(
                split_exclusion(item)
                for item in extract_list_after("Exclude:", body)
            )
        )
    )
    if not includes:
        raise SyncStateError(f"{coverage_path.name}: Include must select maintained code")
    for pattern, reason in excludes:
        if not reason:
            raise SyncStateError(
                f"{coverage_path.name}: exclusion needs '-> reason': `{pattern}`"
            )

    reporter = Reporter()
    inventory = repo_files(repo, reporter)
    included = {
        path
        for path in inventory
        if any(matches(path, pattern) for pattern in includes)
    }
    if not included:
        raise SyncStateError("coverage Include patterns match no repository files")
    for pattern in includes:
        if not any(matches(path, pattern) for path in inventory):
            raise SyncStateError(f"coverage Include pattern matches nothing: `{pattern}`")

    excluded = {
        path
        for path in inventory
        if any(matches(path, pattern) for pattern, _reason in excludes)
    }
    unclassified = sorted(set(inventory) - included - excluded)
    if unclassified:
        preview = ", ".join(f"`{path}`" for path in unclassified[:8])
        remainder = len(unclassified) - 8
        suffix = f" (and {remainder} more)" if remainder > 0 else ""
        raise SyncStateError(
            "coverage boundary leaves repository files unclassified: "
            f"{preview}{suffix}; match every tracked/nonignored path with "
            "Include or a reasoned Exclude"
        )
    selected = tuple(sorted(included - excluded))
    if not selected:
        raise SyncStateError(
            "coverage boundary selects no maintained repository files after Exclude"
        )
    contract = {
        "include": list(includes),
        "exclude": [list(item) for item in excludes],
    }
    strategy = "filesystem" if reporter.warnings else "git"
    return CoverageScope(
        path=coverage_path,
        note_sha256=prefixed_sha256(note_bytes),
        contract_sha256=prefixed_sha256(canonical_bytes(contract)),
        includes=includes,
        excludes=excludes,
        selected=selected,
        inventory_strategy=strategy,
        warnings=tuple(reporter.warnings),
    )


def entry_digest(kind: str, executable_bits: int, content_sha256: str) -> str:
    return prefixed_sha256(
        canonical_bytes(
            {
                "kind": kind,
                "executableBits": executable_bits,
                "contentSha256": content_sha256,
            }
        )
    )


def stable_file_digest(path: Path) -> str:
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode):
            data = os.fsencode(os.readlink(path))
            kind = "symlink"
            executable_bits = 0
            content_sha256 = prefixed_sha256(data)
        elif stat.S_ISREG(before.st_mode):
            hasher = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(chunk)
            after = path.lstat()
            before_key = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            after_key = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            if before_key != after_key:
                raise SyncStateError(f"file changed while hashing: {path}")
            return entry_digest(
                "file",
                stat.S_IMODE(before.st_mode) & 0o111,
                f"sha256:{hasher.hexdigest()}",
            )
        else:
            raise SyncStateError(f"unsupported in-scope file type: {path}")
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
        ):
            raise SyncStateError(f"symlink changed while hashing: {path}")
        return entry_digest(kind, executable_bits, content_sha256)
    except FileNotFoundError as error:
        raise SyncStateError(f"file disappeared while hashing: {path}") from error
    except OSError as error:
        raise SyncStateError(f"cannot hash {path}: {error}") from error


def build_manifest(repo: Path, paths: tuple[str, ...]) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for relative in paths:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise SyncStateError(f"unsafe repository path in inventory: {relative}")
        manifest[relative] = stable_file_digest(repo / pure)
    return manifest


def manifest_fingerprint(manifest: dict[str, str]) -> str:
    return prefixed_sha256(canonical_bytes(manifest))


def normalize_remote(value: str) -> str:
    value = value.strip()
    scp_match = re.match(r"^(?:[^@/]+@)?([^:/]+):(.+)$", value)
    if scp_match and "://" not in value:
        host, path = scp_match.groups()
        return f"{host.casefold()}/{path.rstrip('/').removesuffix('.git')}"
    parsed = urlsplit(value)
    if parsed.scheme:
        host = (parsed.hostname or "").casefold()
        port = f":{parsed.port}" if parsed.port else ""
        path = parsed.path.rstrip("/").removesuffix(".git")
        if host:
            return f"{host}{port}{path}"
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return value.rstrip("/").removesuffix(".git")


def repository_metadata(repo: Path, is_git: bool) -> tuple[dict[str, Any], str | None, str | None, list[str]]:
    fallbacks: list[str] = []
    if not is_git:
        identity = prefixed_sha256(f"filesystem\0{repo}".encode("utf-8"))
        fallbacks.append("git-metadata-unavailable")
        return {
            "kind": "filesystem",
            "identity": identity,
            "root": str(repo),
            "remotes": [],
        }, None, None, fallbacks

    head_bytes = run_git(repo, ["rev-parse", "--verify", "HEAD"], check=False)
    tree_bytes = run_git(repo, ["rev-parse", "--verify", "HEAD^{tree}"], check=False)
    head = head_bytes.decode("ascii").strip() if head_bytes else None
    tree = tree_bytes.decode("ascii").strip() if tree_bytes else None
    if not head or not tree:
        fallbacks.append("unborn-git-head")

    remote_names = run_git(repo, ["remote"], check=False).decode(
        "utf-8", errors="replace"
    ).splitlines()
    remotes: list[str] = []
    for name in sorted(set(remote_names)):
        values = run_git(repo, ["remote", "get-url", "--all", name], check=False)
        remotes.extend(
            normalize_remote(item)
            for item in values.decode("utf-8", errors="replace").splitlines()
            if item.strip()
        )
    remotes = sorted(set(remotes))
    if remotes:
        identity_material = {"kind": "git-remotes", "remotes": remotes}
    else:
        common_dir = run_git(repo, ["rev-parse", "--git-common-dir"]).decode(
            "utf-8", errors="replace"
        ).strip()
        common_path = Path(common_dir)
        if not common_path.is_absolute():
            common_path = repo / common_path
        identity_material = {
            "kind": "git-common-dir",
            "path": str(common_path.resolve()),
        }
    identity = prefixed_sha256(canonical_bytes(identity_material))
    return {
        "kind": "git",
        "identity": identity,
        "root": str(repo),
        "remotes": remotes,
    }, head, tree, fallbacks


def git_working_tree(repo: Path, head: str | None) -> tuple[bool | None, str]:
    masked = []
    raw_flags = run_git(repo, ["ls-files", "-v", "-z"])
    for record in raw_flags.decode(
        "utf-8", errors="surrogateescape"
    ).split("\0"):
        if not record:
            continue
        tag, separator, path = record.partition(" ")
        if separator and (tag == "S" or tag.islower()):
            masked.append(path)
    if masked:
        preview = ", ".join(masked[:8])
        suffix = f" (and {len(masked) - 8} more)" if len(masked) > 8 else ""
        raise SyncStateError(
            "Git index masks working-tree changes with assume-unchanged or "
            f"skip-worktree: {preview}{suffix}; clear those flags before mapping"
        )

    if head is None:
        index_entries = run_git(repo, ["ls-files", "--stage", "-z"])
        unstaged_diff = run_git(
            repo,
            [
                "diff",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                "--",
            ],
        )
        raw_untracked = run_git(
            repo, ["ls-files", "--others", "--exclude-standard", "-z"]
        )
        untracked = sorted(
            item
            for item in raw_untracked.decode(
                "utf-8", errors="surrogateescape"
            ).split("\0")
            if item
        )
        payload = {
            "indexEntries": prefixed_sha256(index_entries),
            "unstagedDiff": prefixed_sha256(unstaged_diff),
            "untracked": {
                item: stable_file_digest(repo / PurePosixPath(item))
                for item in untracked
            },
        }
        return None, prefixed_sha256(canonical_bytes(payload))

    staged_diff = run_git(
        repo,
        [
            "diff",
            "--cached",
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            head,
            "--",
        ],
    )
    unstaged_diff = run_git(
        repo,
        [
            "diff",
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--no-textconv",
            "--no-renames",
            "--",
        ],
    )
    raw_untracked = run_git(
        repo, ["ls-files", "--others", "--exclude-standard", "-z"]
    )
    untracked = sorted(
        item
        for item in raw_untracked.decode("utf-8", errors="surrogateescape").split("\0")
        if item
    )
    untracked_manifest = {
        item: stable_file_digest(repo / PurePosixPath(item)) for item in untracked
    }
    payload = {
        "stagedDiff": prefixed_sha256(staged_diff),
        "unstagedDiff": prefixed_sha256(unstaged_diff),
        "untracked": untracked_manifest,
    }
    return bool(staged_diff or unstaged_diff or untracked), prefixed_sha256(
        canonical_bytes(payload)
    )


def filesystem_working_tree(manifest: dict[str, str]) -> tuple[None, str]:
    return None, prefixed_sha256(canonical_bytes(manifest))


def coverage_display_path(map_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(map_dir).as_posix()
    except ValueError:
        return str(path)


def reject_outputs_inside_scope(
    repo: Path,
    paths: list[Path],
    scope: CoverageScope,
) -> None:
    """Reject map outputs that would change the repository target they describe."""

    for path in paths:
        try:
            relative = path.resolve(strict=False).relative_to(repo).as_posix()
        except ValueError:
            continue
        included = any(matches(relative, pattern) for pattern in scope.includes)
        excluded = any(
            matches(relative, pattern) for pattern, _reason in scope.excludes
        )
        if scope.inventory_strategy == "git":
            ignored = subprocess.run(
                ["git", "-C", str(repo), "check-ignore", "--quiet", "--", relative],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode == 0
            if ignored:
                continue
        elif not included or excluded:
            continue
        raise SyncStateError(
            "mental-map output would alter the repository target: "
            f"{relative}; move the map outside the repository"
        )


def target_fingerprint(target: dict[str, Any]) -> str:
    material = {
        "repoIdentity": target["repository"]["identity"],
        "head": target["head"],
        "tree": target["tree"],
        "coverageContract": target["coverage"]["contractSha256"],
        "coverageNote": target["coverage"]["noteSha256"],
        "workingTree": target["workingTree"]["fingerprint"],
        "manifest": target["manifestFingerprint"],
    }
    return prefixed_sha256(canonical_bytes(material))


def capture_target(
    repo_value: str | Path,
    map_dir: Path,
    coverage_value: str | None,
    state_path: Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    repo, is_git = resolve_repo(repo_value)
    overlaps = False
    try:
        map_dir.relative_to(repo)
    except ValueError:
        pass
    else:
        overlaps = True
    try:
        repo.relative_to(map_dir)
    except ValueError:
        pass
    else:
        overlaps = True
    if overlaps:
        raise SyncStateError(
            "map directory and repository must not overlap; move the map "
            "outside the repository"
        )
    coverage_path = resolve_coverage(map_dir, coverage_value)
    coverage_before = coverage_path.read_bytes()
    scope = load_coverage_scope(repo, coverage_path)
    output_paths = [
        path
        for path in map_dir.rglob("*")
        if path.is_file()
        and path.suffix.casefold() in validation_receipt.MAP_ARTIFACT_SUFFIXES
    ]
    if state_path is not None:
        output_paths.append(state_path)
    output_paths.append(map_dir / validation_receipt.DEFAULT_RECEIPT_NAME)
    reject_outputs_inside_scope(repo, output_paths, scope)
    repository, head, tree, fallbacks = repository_metadata(repo, is_git)
    manifest = build_manifest(repo, scope.selected)
    if is_git:
        dirty, working_fingerprint = git_working_tree(repo, head)
        head_after = run_git(repo, ["rev-parse", "--verify", "HEAD"], check=False)
        if head and head_after.decode("ascii").strip() != head:
            raise SyncStateError("HEAD changed while capturing target state")
    else:
        dirty, working_fingerprint = filesystem_working_tree(manifest)
    if coverage_path.read_bytes() != coverage_before:
        raise SyncStateError("coverage note changed while capturing target state")
    fallbacks.extend(
        "inventory-filesystem-fallback" for _warning in scope.warnings
    )

    target: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "repository": repository,
        "head": head,
        "tree": tree,
        "coverage": {
            "path": coverage_display_path(map_dir, coverage_path),
            "noteSha256": scope.note_sha256,
            "contractSha256": scope.contract_sha256,
            "include": list(scope.includes),
            "exclude": [list(item) for item in scope.excludes],
        },
        "inventoryStrategy": scope.inventory_strategy,
        "workingTree": {
            "dirty": dirty,
            "fingerprint": working_fingerprint,
        },
        "files": manifest,
        "manifestFingerprint": manifest_fingerprint(manifest),
    }
    target["targetFingerprint"] = target_fingerprint(target)
    return target, sorted(set(fallbacks))


def state_error(state: Any) -> str | None:
    if not isinstance(state, dict):
        return "state-root-is-not-an-object"
    if state.get("schema") != SCHEMA_VERSION:
        return "unsupported-state-schema"
    repository = state.get("repository")
    coverage = state.get("coverage")
    working_tree = state.get("workingTree")
    files = state.get("files")
    if not isinstance(repository, dict) or not SHA256_RE.match(
        str(repository.get("identity", ""))
    ):
        return "invalid-repository-identity"
    if not isinstance(coverage, dict) or not SHA256_RE.match(
        str(coverage.get("contractSha256", ""))
    ):
        return "invalid-coverage-contract"
    if not isinstance(working_tree, dict) or not SHA256_RE.match(
        str(working_tree.get("fingerprint", ""))
    ):
        return "invalid-working-tree-fingerprint"
    if not isinstance(files, dict):
        return "invalid-file-manifest"
    for path, digest in files.items():
        pure = PurePosixPath(path) if isinstance(path, str) else None
        if (
            pure is None
            or pure.is_absolute()
            or ".." in pure.parts
            or not SHA256_RE.match(str(digest))
        ):
            return "invalid-file-manifest-entry"
    if state.get("manifestFingerprint") != manifest_fingerprint(files):
        return "manifest-fingerprint-mismatch"
    if not SHA256_RE.match(str(state.get("targetFingerprint", ""))):
        return "invalid-target-fingerprint"
    try:
        if state.get("targetFingerprint") != target_fingerprint(state):
            return "target-fingerprint-mismatch"
    except (KeyError, TypeError):
        return "incomplete-state"
    return None


def load_state(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, ["state-missing"]
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, ["state-invalid-json"]
    error = state_error(state)
    if error:
        return None, [error]
    return state, []


def resolve_state_path(
    map_dir: Path, state_value: str | Path | None
) -> Path:
    try:
        return validation_receipt.resolve_sidecar_path(
            map_dir,
            state_value,
            default_name=DEFAULT_STATE_NAME,
            label="sync state",
            forbidden_paths=(
                map_dir / validation_receipt.DEFAULT_RECEIPT_NAME,
            ),
        )
    except validation_receipt.ValidationReceiptError as error:
        raise SyncStateError(str(error)) from error


def changed_paths(
    baseline: dict[str, str] | None, target: dict[str, str]
) -> dict[str, list[str]]:
    if baseline is None:
        added = sorted(target)
        return {"added": added, "modified": [], "deleted": [], "all": added}
    added = sorted(set(target) - set(baseline))
    deleted = sorted(set(baseline) - set(target))
    modified = sorted(
        path
        for path in set(target) & set(baseline)
        if target[path] != baseline[path]
    )
    return {
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "all": sorted([*added, *modified, *deleted]),
    }


def baseline_history_fallbacks(repo: Path, baseline: dict[str, Any], target: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    baseline_head = baseline.get("head")
    target_head = target.get("head")
    if not baseline_head or not target_head or target["repository"]["kind"] != "git":
        return reasons
    exists = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{baseline_head}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if not exists:
        return ["baseline-git-commit-unavailable-using-manifest"]
    ancestor = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", baseline_head, target_head],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if not ancestor:
        reasons.append("baseline-not-ancestor-using-manifest")
    return reasons


def build_status(
    repo_value: str | Path,
    map_dir_value: str | Path,
    coverage_value: str | None = None,
    state_value: str | Path | None = None,
) -> dict[str, Any]:
    map_dir = Path(map_dir_value).expanduser().resolve()
    if not map_dir.is_dir():
        raise SyncStateError(f"map directory does not exist: {map_dir}")
    state_path = resolve_state_path(map_dir, state_value)
    target, target_fallbacks = capture_target(
        repo_value, map_dir, coverage_value, state_path
    )
    baseline, state_reasons = load_state(state_path)
    reasons = [*state_reasons, *target_fallbacks]
    comparable = baseline is not None
    trusted = baseline is not None
    if baseline is not None:
        if baseline["repository"]["identity"] != target["repository"]["identity"]:
            trusted = False
            comparable = False
            reasons.append("repository-identity-changed")
        if baseline["coverage"]["contractSha256"] != target["coverage"]["contractSha256"]:
            trusted = False
            reasons.append("coverage-contract-changed")
        if baseline.get("inventoryStrategy") != target.get("inventoryStrategy"):
            trusted = False
            reasons.append("inventory-strategy-changed")
        repo = Path(target["repository"]["root"])
        reasons.extend(baseline_history_fallbacks(repo, baseline, target))

    baseline_files = baseline["files"] if comparable and baseline else None
    changes = changed_paths(baseline_files, target["files"])
    return {
        "schema": SCHEMA_VERSION,
        "statePath": str(state_path),
        "trusted": trusted,
        "comparisonAvailable": comparable,
        "fallbackReasons": sorted(set(reasons)),
        "changedPaths": changes,
        "baseline": None
        if baseline is None
        else {
            "head": baseline.get("head"),
            "tree": baseline.get("tree"),
            "targetFingerprint": baseline.get("targetFingerprint"),
        },
        "target": target,
        "targetFingerprint": target["targetFingerprint"],
    }


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    validation_receipt.atomic_write_json(path, value)


def checkpoint_context(status_report: dict[str, Any]) -> dict[str, Any]:
    target = status_report["target"]
    return {
        "targetFingerprint": status_report["targetFingerprint"],
        "coverageContractSha256": target["coverage"]["contractSha256"],
        "coverageNoteSha256": target["coverage"]["noteSha256"],
        "changedPaths": status_report["changedPaths"]["all"],
        "statusContext": validation_receipt.status_context_from_report(
            status_report
        ),
    }


def verify_status_receipt(
    map_dir: Path,
    receipt_path: Path,
    state_path: Path,
    status_report: dict[str, Any],
) -> None:
    context = checkpoint_context(status_report)
    validation_receipt.verify_receipt(
        map_dir,
        Path(__file__).resolve().parent,
        target_fingerprint=context["targetFingerprint"],
        coverage_contract_sha256=context["coverageContractSha256"],
        changed_paths=context["changedPaths"],
        status_context=context["statusContext"],
        receipt_path=receipt_path,
        forbidden_paths=(state_path,),
    )


def reject_receipt_inside_scope(
    receipt_path: Path, status_report: dict[str, Any]
) -> None:
    target = status_report["target"]
    repo = Path(target["repository"]["root"])
    coverage = target["coverage"]
    scope = CoverageScope(
        path=Path(str(coverage["path"])),
        note_sha256=str(coverage["noteSha256"]),
        contract_sha256=str(coverage["contractSha256"]),
        includes=tuple(str(item) for item in coverage["include"]),
        excludes=tuple(
            (str(item[0]), str(item[1])) for item in coverage["exclude"]
        ),
        selected=tuple(target["files"]),
        inventory_strategy=str(target["inventoryStrategy"]),
        warnings=(),
    )
    reject_outputs_inside_scope(repo, [receipt_path], scope)


def checkpoint(
    repo_value: str | Path,
    map_dir_value: str | Path,
    coverage_value: str | None = None,
    state_value: str | Path | None = None,
    receipt_value: str | Path | None = None,
    *,
    require_fingerprint: str,
) -> dict[str, Any]:
    map_dir = Path(map_dir_value).expanduser().resolve()
    if not map_dir.is_dir():
        raise SyncStateError(f"map directory does not exist: {map_dir}")
    state_path = resolve_state_path(map_dir, state_value)
    try:
        receipt_path = validation_receipt.resolve_sidecar_path(
            map_dir,
            receipt_value,
            default_name=validation_receipt.DEFAULT_RECEIPT_NAME,
            label="validation receipt",
            forbidden_paths=(state_path,),
        )
    except validation_receipt.ValidationReceiptError as error:
        raise SyncStateError(str(error)) from error
    status_report = build_status(
        repo_value, map_dir, coverage_value, state_path
    )
    actual = status_report["targetFingerprint"]
    if require_fingerprint != actual:
        raise FingerprintMismatch(
            f"target fingerprint changed: expected {require_fingerprint}, got {actual}"
        )
    try:
        reject_receipt_inside_scope(receipt_path, status_report)
        verify_status_receipt(
            map_dir, receipt_path, state_path, status_report
        )
    except validation_receipt.ValidationReceiptError as error:
        raise SyncStateError(str(error)) from error

    final_status = build_status(repo_value, map_dir, coverage_value, state_path)
    final_actual = final_status["targetFingerprint"]
    if require_fingerprint != final_actual:
        raise FingerprintMismatch(
            "target fingerprint changed during checkpoint: "
            f"expected {require_fingerprint}, got {final_actual}"
        )
    if checkpoint_context(status_report) != checkpoint_context(final_status):
        raise FingerprintMismatch(
            "baseline or trust context changed during checkpoint"
        )
    try:
        reject_receipt_inside_scope(receipt_path, final_status)
        verify_status_receipt(map_dir, receipt_path, state_path, final_status)
    except validation_receipt.ValidationReceiptError as error:
        raise SyncStateError(str(error)) from error

    atomic_write_json(state_path, final_status["target"])
    return {
        "schema": SCHEMA_VERSION,
        "checkpointed": True,
        "statePath": str(state_path),
        "targetFingerprint": final_actual,
        "validationReceipt": str(receipt_path),
        "previouslyTrusted": final_status["trusted"],
        "fallbackReasons": final_status["fallbackReasons"],
    }


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", required=True, help="repository root or a path inside it")
    parser.add_argument("--map-dir", required=True, help="project map directory in the vault")
    parser.add_argument(
        "--coverage",
        help="coverage note path, relative to map-dir; auto-detected when unique",
    )
    parser.add_argument(
        "--state",
        help=f"state file path; defaults to <map-dir>/{DEFAULT_STATE_NAME}",
    )


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status", help="report target and delta as JSON")
    add_common_arguments(status_parser)
    checkpoint_parser = subparsers.add_parser(
        "checkpoint", help="atomically save the current target state"
    )
    add_common_arguments(checkpoint_parser)
    checkpoint_parser.add_argument(
        "--require-fingerprint",
        "--expected-fingerprint",
        dest="require_fingerprint",
        required=True,
        help="write only when the current target has this status fingerprint",
    )
    checkpoint_parser.add_argument(
        "--receipt",
        help=(
            "validation receipt path; defaults to "
            f"<map-dir>/{validation_receipt.DEFAULT_RECEIPT_NAME}"
        ),
    )
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        if args.command == "status":
            result = build_status(args.repo, args.map_dir, args.coverage, args.state)
        else:
            result = checkpoint(
                args.repo,
                args.map_dir,
                args.coverage,
                args.state,
                args.receipt,
                require_fingerprint=args.require_fingerprint,
            )
    except FingerprintMismatch as error:
        print(json.dumps({"error": str(error), "code": "fingerprint-mismatch"}))
        return 3
    except SyncStateError as error:
        print(json.dumps({"error": str(error), "code": "state-error"}))
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
