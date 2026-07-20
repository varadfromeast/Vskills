#!/usr/bin/env python3
"""Create a safe draft version-2 Obsidian mental-map directory."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import validation_receipt


class ScaffoldError(RuntimeError):
    """The requested scaffold boundary or destination is invalid."""


GLOB_META_RE = re.compile(r"[*?]")
UNSAFE_FILENAME_CHARACTERS = frozenset('/\\:*?"<>|#^[]')


def git_output(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip()
        raise ScaffoldError(message or "Git command failed")
    return result.stdout.strip()


def absolute_path(value: str, label: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise ScaffoldError(f"{label} must be an explicit absolute path")
    return candidate.resolve()


def validate_project_name(project: str) -> str:
    value = project.strip()
    if not value or value in {".", ".."}:
        raise ScaffoldError("project name must not be empty")
    if value != project or value.endswith("."):
        raise ScaffoldError("project name must not have surrounding whitespace or a trailing dot")
    if (
        "%%" in value
        or any(character in UNSAFE_FILENAME_CHARACTERS for character in value)
        or any(ord(character) < 32 for character in value)
    ):
        raise ScaffoldError(
            "project name must be one Obsidian-safe filename component without "
            "reserved link or filesystem characters"
        )
    return value


def validate_pattern(value: str, label: str) -> str:
    pattern = value.strip()
    if not pattern or "`" in pattern or any(character in pattern for character in "\n\r\0"):
        raise ScaffoldError(f"{label} contains an invalid coverage pattern")
    return pattern


def parse_exclusion(value: str) -> tuple[str, str]:
    pattern, separator, reason = value.partition("=")
    if not separator or not reason.strip():
        raise ScaffoldError("--exclude must use PATTERN=REASON with a non-empty reason")
    clean_reason = reason.strip()
    if any(character in clean_reason for character in "\n\r\0"):
        raise ScaffoldError("--exclude reason must fit on one line")
    return validate_pattern(pattern, "--exclude"), clean_reason


def normalize_repo_pattern(pattern: str) -> str:
    value = pattern.strip()
    return value[2:] if value.startswith("./") else value


def pattern_regex(pattern: str) -> re.Pattern[str]:
    pattern = normalize_repo_pattern(pattern)
    pieces: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                if index + 2 < len(pattern) and pattern[index + 2] == "/":
                    pieces.append("(?:.*/)?")
                    index += 3
                else:
                    pieces.append(".*")
                    index += 2
            else:
                pieces.append("[^/]*")
                index += 1
        elif character == "?":
            pieces.append("[^/]")
            index += 1
        else:
            pieces.append(re.escape(character))
            index += 1
    pieces.append("$")
    return re.compile("".join(pieces))


def matches(path: str, pattern: str) -> bool:
    normalized = normalize_repo_pattern(pattern)
    if not GLOB_META_RE.search(normalized):
        return path == normalized or path.startswith(normalized.rstrip("/") + "/")
    return bool(pattern_regex(normalized).match(path))


def repository_inventory(repo: Path) -> list[str]:
    output = git_output(
        repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z"
    )
    return sorted(path for path in output.split("\0") if path)


def repository_has_dirty_paths(repo: Path) -> bool:
    return bool(
        git_output(
            repo,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        )
    )


def validate_coverage_boundary(
    repo: Path,
    includes: list[str],
    excludes: list[tuple[str, str]],
) -> None:
    inventory = repository_inventory(repo)
    if not inventory:
        raise ScaffoldError("repository inventory is empty")
    for pattern in includes:
        if not any(matches(path, pattern) for path in inventory):
            raise ScaffoldError(f"--include pattern matches nothing: `{pattern}`")
    for pattern, _reason in excludes:
        if not any(matches(path, pattern) for path in inventory):
            raise ScaffoldError(f"--exclude pattern matches nothing: `{pattern}`")

    included = {
        path for path in inventory if any(matches(path, pattern) for pattern in includes)
    }
    excluded = {
        path
        for path in inventory
        if any(matches(path, pattern) for pattern, _reason in excludes)
    }
    unclassified = sorted(set(inventory) - included - excluded)
    if unclassified:
        preview = ", ".join(unclassified[:8])
        suffix = " ..." if len(unclassified) > 8 else ""
        raise ScaffoldError(
            "coverage boundary leaves repository files unclassified; add an Include or "
            f"reasoned Exclude: {preview}{suffix}"
        )
    if not included - excluded:
        raise ScaffoldError("coverage boundary selects no maintained repository files")


def scaffold(
    *,
    repo_value: str,
    vault_value: str,
    map_dir_value: str,
    project_value: str,
    includes: list[str],
    excludes: list[str],
) -> dict[str, object]:
    repo_input = absolute_path(repo_value, "--repo")
    vault = absolute_path(vault_value, "--vault")
    map_dir = absolute_path(map_dir_value, "--map-dir")
    project = validate_project_name(project_value)

    if not repo_input.is_dir():
        raise ScaffoldError(f"repository does not exist: {repo_input}")
    if not vault.is_dir():
        raise ScaffoldError(f"vault does not exist: {vault}")
    if not (vault / ".obsidian").is_dir():
        raise ScaffoldError(
            "vault root must contain .obsidian; pass the exact directory Obsidian opened"
        )
    try:
        map_dir.relative_to(vault)
    except ValueError as error:
        raise ScaffoldError("--map-dir must be inside --vault") from error
    if map_dir == vault:
        raise ScaffoldError("--map-dir must be a project directory below --vault")
    repo = Path(git_output(repo_input, "rev-parse", "--show-toplevel")).resolve()
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
        raise ScaffoldError(
            "--map-dir and --repo must not overlap; map artifacts cannot be "
            "inside, equal to, or contain the mapped repository"
        )
    if map_dir.exists():
        raise ScaffoldError(f"refusing to overwrite existing map directory: {map_dir}")
    revision = git_output(repo, "rev-parse", "HEAD")
    mapped_target = (
        "HEAD + dirty paths" if repository_has_dirty_paths(repo) else "HEAD"
    )
    clean_includes = [validate_pattern(item, "--include") for item in includes]
    if not clean_includes:
        raise ScaffoldError("at least one explicit --include pattern is required")
    clean_excludes = [parse_exclusion(item) for item in excludes]
    validate_coverage_boundary(repo, clean_includes, clean_excludes)

    atlas_name = f"{project} Atlas.md"
    canvas_name = f"{project} Atlas.canvas"
    relationships_canvas_name = f"{project} All Relationships.canvas"
    relationships_canvas_ref = f"Views/{relationships_canvas_name}"
    base_name = f"{project} Blocks.base"
    coverage_name = f"{project} Code Coverage.md"
    quoted_project = json.dumps(project, ensure_ascii=True)
    base_project_expression = f"project == {quoted_project}".replace("'", "''")
    map_vault_relative = map_dir.relative_to(vault).as_posix()
    canvas_link = f"{map_vault_relative}/{canvas_name}"
    relationships_canvas_link = (
        f"{map_vault_relative}/{relationships_canvas_ref}"
    )
    base_link = f"{map_vault_relative}/{base_name}"
    coverage_link = f"{map_vault_relative}/{coverage_name}"

    atlas = f"""---
type: mental-map-atlas
map-version: 2
project: {quoted_project}
mapping-mode: codebase-atlas
revision: {revision}
canvas: {json.dumps(canvas_name)}
relationships-canvas: {json.dumps(relationships_canvas_ref)}
base: {json.dumps(base_name)}
sync-state: .mental-map-state.json
---

# {project} Atlas

Purpose:

Domain boundary:

Quality priorities:

Current risks:

Coverage summary:

Mapped target: {mapped_target}

Unresolved questions:

Start here: [[{canvas_link}]] · [[{relationships_canvas_link}]] · [[{base_link}]] · [[{coverage_link}]]

## Entry-point families

| Family | Representative anchor | Focused view | No-view reason |
| --- | --- | --- | --- |
| TODO: name a public or runnable family | `TODO: exact path :: symbol` | | TODO: link one focused view or justify why none is needed |

## Canvas semantic groups

| Group | Scope key | Question | Members |
| --- | --- | --- | --- |
| TODO: name one coherent architectural scope | todo-scope | How do these orientation blocks cohere? | [[TODO: replace with canonical block links]] |

## Needs review

![[{base_link}#Needs review]]
"""
    base = f"""filters:
  and:
    - 'type == "mental-map-block"'
    - '{base_project_expression}'
views:
  - type: table
    name: All blocks
    order:
      - file.name
      - kind
      - level
      - status
      - confidence
      - reviewed-revision
  - type: table
    name: Needs review
    filters:
      and:
        - 'note["reviewed-revision"] != this.revision'
    order:
      - file.name
      - kind
      - level
      - status
      - confidence
      - reviewed-revision
"""
    include_lines = "\n".join(f"- `{pattern}`" for pattern in clean_includes)
    exclude_lines = "\n".join(
        f"- `{pattern}` -> {reason}" for pattern, reason in clean_excludes
    )
    coverage = f"""---
type: mental-map-coverage
project: {quoted_project}
revision: {revision}
---

# {project} Code Coverage

Include:
{include_lines}

Exclude:
{exclude_lines}
"""

    map_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".mental-map-scaffold.", dir=map_dir.parent)
    )
    try:
        for directory in ("Blocks", "Views", "Flows"):
            (staging / directory).mkdir()
        (staging / atlas_name).write_text(atlas, encoding="utf-8")
        (staging / base_name).write_text(base, encoding="utf-8")
        (staging / coverage_name).write_text(coverage, encoding="utf-8")
        validation_receipt.atomic_write_json(
            staging / canvas_name, {"nodes": [], "edges": []}
        )
        validation_receipt.atomic_write_json(
            staging / relationships_canvas_ref, {"nodes": [], "edges": []}
        )
        os.replace(staging, map_dir)
        validation_receipt.fsync_parent_directory(map_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "created": True,
        "draft": True,
        "repo": str(repo),
        "vault": str(vault),
        "mapDir": str(map_dir),
        "revision": revision,
        "mappedTarget": mapped_target,
        "artifacts": [
            atlas_name,
            canvas_name,
            relationships_canvas_ref,
            base_name,
            coverage_name,
        ],
        "checkpointCreated": False,
        "validationReceiptCreated": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="explicit absolute Git repository path")
    parser.add_argument(
        "--vault", required=True, help="absolute Obsidian vault root containing .obsidian"
    )
    parser.add_argument(
        "--map-dir", required=True, help="new absolute project-map directory inside the vault"
    )
    parser.add_argument("--project", required=True, help="project display name")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="coverage glob; repeat for multiple explicit includes",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="PATTERN=REASON coverage exclusion; repeat as needed",
    )
    args = parser.parse_args()
    try:
        result = scaffold(
            repo_value=args.repo,
            vault_value=args.vault,
            map_dir_value=args.map_dir,
            project_value=args.project,
            includes=args.include,
            excludes=args.exclude,
        )
    except ScaffoldError as error:
        print(json.dumps({"error": str(error), "code": "scaffold-error"}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
