#!/usr/bin/env python3
"""Validate a model-first Obsidian codebase atlas.

The validator intentionally checks only deterministic claims: note shape,
wikilink resolution, diagram/model consistency, concrete anchors, and optional
whole-codebase ownership coverage. Semantic block quality remains a review task.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import validation_receipt


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
CONNECT_RE = re.compile(
    r"^-\s+\[(implemented|planned|detail-only)\]\s+"
    r"\[\[([^\]]+)\]\]\s*->\s*(\S.*)$"
)
NODE_RE = re.compile(r'^\s*(\w+)\s*\["([^"]+)"\]\s*$')
SOLID_EDGE_RE = re.compile(r"^\s*(\w+)\s*-->\|([^|]+)\|\s*(\w+)\s*$")
PLANNED_EDGE_RE = re.compile(
    r'^\s*(\w+)\s*-\.\s*(?:"([^"]+)"|([^.]\S.*?))?\s*\.->\s*(\w+)\s*$'
)
PARTICIPANT_RE = re.compile(r"^\s*participant\s+(\w+)\s+as\s+(.+?)\s*$")
MESSAGE_RE = re.compile(
    r"^\s*(\w+)\s*(?:->>|-->>|->|-->|-\)|--\)|-x|--x)\s*"
    r"(\w+)\s*:\s*(\S.*)$"
)
QUESTION_RE = re.compile(
    r"\b(?:how|what|where|when|why|which|who|does|do|can|should|is|are)\b",
    re.IGNORECASE,
)
GLOB_META_RE = re.compile(r"[*?[]")
ANCHOR_SYMBOL_RE = re.compile(r"^[\w$-]+(?:\.[\w$-]+)*$", re.UNICODE)

VALID_KINDS = {
    "actor",
    "system",
    "external-system",
    "runtime",
    "store",
    "responsibility",
}
VALID_LEVELS = {"context", "runtime", "responsibility"}
VALID_STATUSES = {"implemented", "planned", "deprecated"}
VALID_CONFIDENCES = {"accounted", "traced", "deeply-inspected"}
SYNC_STATE_SCHEMA_VERSION = 1
EVIDENCE_REFERENCE_RE = re.compile(
    r"(?:\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b|"
    r"\b(?:ADR|PRD)[- _]?\d+\b|\b(?:issue|ticket|PR)\s*#?\d+\b|"
    r"(?<!\w)#\d+\b|/(?:issues|pull)/\d+\b|"
    r"\[[^\]]+\]\([^)]+\)|(?:^|[\s`(])(?:[\w.-]+/)+[\w.-]+\.md(?:[\s`) ]|$))",
    re.IGNORECASE,
)
RESERVED_BLOCK_TITLE_TOKENS = (
    "/",
    "\\",
    ":",
    "*",
    "?",
    '"',
    "<",
    ">",
    "|",
    "#",
    "^",
    "[",
    "]",
    "%%",
)
VALID_VIEW_TYPES = {
    "context",
    "runtime",
    "responsibility",
    "journey",
    "contract",
    "data",
    "state",
    "deployment",
    "drill-down",
    "cross-cutting",
    "change-impact",
}
ENTRY_POINT_HEADERS = (
    "family",
    "representative anchor",
    "focused view",
    "no-view reason",
)
CANVAS_GROUP_HEADERS = ("group", "scope key", "question", "members")
CANVAS_SCOPE_KEY_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD)\b|<[^>]+>|replace\s+this", re.IGNORECASE)
EXCLUDED_REPO_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


@dataclass
class Reporter:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mapped_files: int = 0
    excluded_files: int = 0
    unresolved_files: int = 0

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


@dataclass
class Block:
    title: str
    path: Path
    frontmatter: dict[str, str]
    text: str
    parent: str | None
    footprints: list[str]
    anchors: list[str]
    evidence: list[str]
    relationships: dict[str, set[tuple[str, str]]]
    model_links: list[tuple[str, str]]


@dataclass
class DiagramFacts:
    nodes: dict[str, str] = field(default_factory=dict)
    solid_edges: set[tuple[str, str, str]] = field(default_factory=set)
    planned_edges: set[tuple[str, str, str]] = field(default_factory=set)
    internal_link_ids: set[str] = field(default_factory=set)
    planned_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class EntryPointFamily:
    name: str
    anchor: str
    focused_view: str
    no_view_reason: str
    row_number: int


@dataclass(frozen=True)
class CanvasSemanticGroup:
    name: str
    scope_key: str
    question: str
    members: tuple[str, ...]
    row_number: int


@dataclass(frozen=True)
class GitRevisionContext:
    head: str
    object_format: str
    oid_length: int


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    data: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data, text[end + 4 :]


def yaml_surface_errors(text: str, *, require_top_level_scalars: bool) -> list[str]:
    """Check the intentionally small YAML surface without an external parser.

    The mental-map contract uses flat Markdown frontmatter and a conservative
    subset of Bases YAML. This catches structural mistakes that the scalar
    extractor would otherwise silently ignore; it is not intended to implement
    the full YAML language.
    """

    errors: list[str] = []
    stack: list[tuple[str, int]] = []
    pairs = {"]": "[", "}": "{"}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if "\t" in line:
            errors.append(f"line {line_number} contains a tab")
        stripped = line.strip()
        if (
            require_top_level_scalars
            and stripped
            and not stripped.startswith("#")
            and not line.startswith((" ", "\t"))
            and not re.match(r"^[A-Za-z0-9_-]+\s*:", line)
        ):
            errors.append(
                f"line {line_number} is not a top-level `key: value` scalar"
            )

        quote: str | None = None
        escaped = False
        index = 0
        while index < len(line):
            character = line[index]
            if quote == '"':
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quote = None
                index += 1
                continue
            if quote == "'":
                if character == "'":
                    if index + 1 < len(line) and line[index + 1] == "'":
                        index += 2
                        continue
                    quote = None
                index += 1
                continue
            if character == "#":
                break
            if character in {"'", '"'}:
                previous = line[index - 1] if index else ""
                if index == 0 or previous.isspace() or previous in ":,[{-":
                    quote = character
            elif character in {"[", "{"}:
                stack.append((character, line_number))
            elif character in pairs:
                if not stack or stack[-1][0] != pairs[character]:
                    errors.append(
                        f"line {line_number} has unmatched `{character}`"
                    )
                else:
                    stack.pop()
            index += 1
        if quote is not None:
            errors.append(f"line {line_number} has an unterminated quote")
    if stack:
        opener, line_number = stack[-1]
        errors.append(f"line {line_number} has unclosed `{opener}`")
    return errors


def validate_markdown_frontmatter_surface(
    path: Path, text: str, reporter: Reporter
) -> None:
    if not text.startswith("---\n"):
        return
    end = text.find("\n---", 4)
    if end == -1:
        reporter.error(f"{path.name}: invalid frontmatter: missing closing `---`")
        return
    source = text[4:end]
    for detail in yaml_surface_errors(source, require_top_level_scalars=True):
        message = f"{path.name}: invalid frontmatter YAML: {detail}"
        if message not in reporter.errors:
            reporter.error(message)


def clean_wikilink(raw: str) -> str:
    target = wikilink_target(raw)
    name = PurePosixPath(target).name
    return name[:-3] if name.endswith(".md") else name


def wikilink_target(raw: str) -> str:
    """Return a wikilink target without discarding its path or extension."""

    return raw.split("|", 1)[0].split("#", 1)[0].strip()


def extract_list_after(label: str, text: str) -> list[str]:
    lines = text.splitlines()
    items: list[str] = []
    active = False
    for line in lines:
        if line.strip() == label:
            active = True
            continue
        if not active:
            continue
        if line.startswith("- "):
            items.append(line[2:].strip())
            continue
        if not line.strip() and not items:
            continue
        if items or line.strip():
            break
    return items


def extract_scalar(label: str, text: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(label)}[ \t]*(\S.*)$", text)
    return match.group(1).strip() if match else None


def clean_code_item(item: str) -> str:
    value = item.strip()
    if value.startswith("`") and value.endswith("`"):
        value = value[1:-1]
    return value.strip()


def split_markdown_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def parse_entry_point_inventory(
    atlas_path: Path,
    atlas_text: str,
    reporter: Reporter,
) -> list[EntryPointFamily]:
    """Parse the required, deliberately small atlas inventory table."""

    _frontmatter, body = parse_frontmatter(atlas_text)
    heading_matches = list(
        re.finditer(r"(?mi)^##[ \t]+Entry-point families[ \t]*$", body)
    )
    if len(heading_matches) != 1:
        reporter.error(
            f"{atlas_path.name}: map-version 2 needs exactly one "
            "`## Entry-point families` section"
        )
        return []

    heading = heading_matches[0]
    following = body[heading.end() :]
    next_h2 = re.search(r"(?m)^##[ \t]+", following)
    section = following[: next_h2.start()] if next_h2 else following
    numbered_lines = [
        (body[: heading.end()].count("\n") + offset + 1, line)
        for offset, line in enumerate(section.splitlines(), start=1)
        if line.strip()
    ]
    if len(numbered_lines) < 3:
        reporter.error(
            f"{atlas_path.name}: Entry-point families needs its header, "
            "separator, and at least one inventory row"
        )
        return []

    header_line_number, header_line = numbered_lines[0]
    header = split_markdown_table_row(header_line)
    normalized_header = tuple(cell.casefold() for cell in (header or []))
    if normalized_header != ENTRY_POINT_HEADERS:
        reporter.error(
            f"{atlas_path.name}:{header_line_number}: Entry-point families table "
            "must use `Family | Representative anchor | Focused view | "
            "No-view reason`"
        )
        return []

    separator_line_number, separator_line = numbered_lines[1]
    separator = split_markdown_table_row(separator_line)
    if separator is None or len(separator) != len(ENTRY_POINT_HEADERS) or not all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in separator
    ):
        reporter.error(
            f"{atlas_path.name}:{separator_line_number}: Entry-point families "
            "table needs a four-column Markdown separator row"
        )
        return []

    families: list[EntryPointFamily] = []
    seen_names: dict[str, int] = {}
    for row_number, line in numbered_lines[2:]:
        cells = split_markdown_table_row(line)
        if cells is None or len(cells) != len(ENTRY_POINT_HEADERS):
            reporter.error(
                f"{atlas_path.name}:{row_number}: Entry-point family row must "
                "contain exactly four table cells"
            )
            continue
        name, raw_anchor, focused_view, no_view_reason = cells
        if any(PLACEHOLDER_RE.search(cell) for cell in cells if cell):
            reporter.error(
                f"{atlas_path.name}:{row_number}: replace every Entry-point "
                "families placeholder with discovered repository truth"
            )
            continue
        if not name:
            reporter.error(
                f"{atlas_path.name}:{row_number}: entry-point family name is required"
            )
        else:
            normalized_name = re.sub(r"\s+", " ", name).casefold()
            if normalized_name in seen_names:
                reporter.error(
                    f"{atlas_path.name}:{row_number}: duplicate entry-point family "
                    f"`{name}`; first declared on row {seen_names[normalized_name]}"
                )
            else:
                seen_names[normalized_name] = row_number
        if not raw_anchor or not (
            raw_anchor.startswith("`") and raw_anchor.endswith("`")
        ):
            reporter.error(
                f"{atlas_path.name}:{row_number}: Representative anchor must be "
                "one inline-code exact path or `path :: symbol` anchor"
            )
        if bool(focused_view) == bool(no_view_reason):
            reporter.error(
                f"{atlas_path.name}:{row_number}: provide exactly one Focused view "
                "or No-view reason"
            )
        if no_view_reason:
            words = re.findall(r"[\w-]+", no_view_reason, re.UNICODE)
            if len(words) < 5:
                reporter.error(
                    f"{atlas_path.name}:{row_number}: No-view reason must explain "
                    "why ordering, handoffs, state transitions, and failure behavior "
                    "need no focused view"
                )
        if focused_view:
            link_match = re.fullmatch(r"\[\[([^\]]+)\]\]", focused_view)
            if link_match is None or "|" in focused_view or "#" in focused_view:
                reporter.error(
                    f"{atlas_path.name}:{row_number}: Focused view must be one "
                    "unaliased whole-note wikilink"
                )
        families.append(
            EntryPointFamily(
                name=name,
                anchor=clean_code_item(raw_anchor),
                focused_view=focused_view,
                no_view_reason=no_view_reason,
                row_number=row_number,
            )
        )

    if not families:
        reporter.error(
            f"{atlas_path.name}: Entry-point families must inventory at least one "
            "public or runnable family"
        )
    return families


def parse_canvas_semantic_groups(
    atlas_path: Path,
    atlas_text: str,
    reporter: Reporter,
) -> list[CanvasSemanticGroup]:
    """Parse the semantic contract that the compact Canvas must render."""

    _frontmatter, body = parse_frontmatter(atlas_text)
    heading_matches = list(
        re.finditer(r"(?mi)^##[ \t]+Canvas semantic groups[ \t]*$", body)
    )
    if len(heading_matches) != 1:
        reporter.error(
            f"{atlas_path.name}: map-version 2 needs exactly one "
            "`## Canvas semantic groups` section"
        )
        return []

    heading = heading_matches[0]
    following = body[heading.end() :]
    next_h2 = re.search(r"(?m)^##[ \t]+", following)
    section = following[: next_h2.start()] if next_h2 else following
    numbered_lines = [
        (body[: heading.end()].count("\n") + offset + 1, line)
        for offset, line in enumerate(section.splitlines(), start=1)
        if line.strip()
    ]
    if len(numbered_lines) < 3:
        reporter.error(
            f"{atlas_path.name}: Canvas semantic groups needs its header, "
            "separator, and at least one group row"
        )
        return []

    header_line_number, header_line = numbered_lines[0]
    header = split_markdown_table_row(header_line)
    normalized_header = tuple(cell.casefold() for cell in (header or []))
    if normalized_header != CANVAS_GROUP_HEADERS:
        reporter.error(
            f"{atlas_path.name}:{header_line_number}: Canvas semantic groups "
            "table must use `Group | Scope key | Question | Members`"
        )
        return []

    separator_line_number, separator_line = numbered_lines[1]
    separator = split_markdown_table_row(separator_line)
    if separator is None or len(separator) != len(CANVAS_GROUP_HEADERS) or not all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in separator
    ):
        reporter.error(
            f"{atlas_path.name}:{separator_line_number}: Canvas semantic groups "
            "table needs a four-column Markdown separator row"
        )
        return []

    groups: list[CanvasSemanticGroup] = []
    seen_names: dict[str, int] = {}
    seen_scope_keys: dict[str, int] = {}
    seen_members: dict[str, int] = {}
    for row_number, line in numbered_lines[2:]:
        cells = split_markdown_table_row(line)
        if cells is None or len(cells) != len(CANVAS_GROUP_HEADERS):
            reporter.error(
                f"{atlas_path.name}:{row_number}: Canvas semantic group row "
                "must contain exactly four table cells"
            )
            continue
        name, scope_key, question, raw_members = cells
        if any(PLACEHOLDER_RE.search(cell) for cell in cells if cell):
            reporter.error(
                f"{atlas_path.name}:{row_number}: replace every Canvas semantic "
                "group placeholder with discovered architecture"
            )
            continue

        normalized_name = re.sub(r"\s+", " ", name).casefold()
        if not name:
            reporter.error(
                f"{atlas_path.name}:{row_number}: semantic group name is required"
            )
        elif normalized_name in seen_names:
            reporter.error(
                f"{atlas_path.name}:{row_number}: duplicate semantic group `{name}`; "
                f"first declared on row {seen_names[normalized_name]}"
            )
        else:
            seen_names[normalized_name] = row_number

        if not CANVAS_SCOPE_KEY_RE.fullmatch(scope_key):
            reporter.error(
                f"{atlas_path.name}:{row_number}: Scope key must be a stable "
                "lowercase dot-or-hyphen key"
            )
        elif scope_key in seen_scope_keys:
            reporter.error(
                f"{atlas_path.name}:{row_number}: duplicate semantic group scope "
                f"key `{scope_key}`; first declared on row {seen_scope_keys[scope_key]}"
            )
        else:
            seen_scope_keys[scope_key] = row_number

        if not question or not question.endswith("?") or not QUESTION_RE.search(question):
            reporter.error(
                f"{atlas_path.name}:{row_number}: semantic group Question must "
                "ask the architectural question that makes these members cohere"
            )

        raw_links = WIKILINK_RE.findall(raw_members)
        residual = WIKILINK_RE.sub("", raw_members)
        residual = re.sub(r"[·,;\s]+", "", residual)
        if not raw_links or residual:
            reporter.error(
                f"{atlas_path.name}:{row_number}: Members must be only canonical "
                "block wikilinks separated by `·`"
            )
        members: list[str] = []
        for raw_link in raw_links:
            member = clean_wikilink(raw_link)
            if member in seen_members:
                reporter.error(
                    f"{atlas_path.name}:{row_number}: [[{member}]] belongs to more "
                    "than one semantic group; first declared on row "
                    f"{seen_members[member]}"
                )
                continue
            seen_members[member] = row_number
            members.append(member)

        groups.append(
            CanvasSemanticGroup(
                name=name,
                scope_key=scope_key,
                question=question,
                members=tuple(members),
                row_number=row_number,
            )
        )
    return groups


def normalize_relation_label(label: str) -> str:
    value = re.sub(r"^\d+\.\s*", "", label.strip())
    value = re.sub(r"\s+", " ", value)
    return value.rstrip(".:").casefold()


def parse_block(path: Path, reporter: Reporter) -> Block:
    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = parse_frontmatter(text)
    parent_raw = extract_scalar("Parent:", body)
    parent: str | None = None
    model_links: list[tuple[str, str]] = []
    if parent_raw:
        links = WIKILINK_RE.findall(parent_raw)
        if len(links) == 1 and re.fullmatch(r"\[\[[^\]]+\]\]", parent_raw):
            parent = clean_wikilink(links[0])
            model_links.append(("Parent", links[0]))
        else:
            reporter.error(
                f"{path.name}: Parent must contain exactly one ordinary wikilink"
            )

    relationships: dict[str, set[tuple[str, str]]] = {
        "implemented": set(),
        "planned": set(),
        "detail-only": set(),
    }
    for item in extract_list_after("Connects:", body):
        match = CONNECT_RE.match(f"- {item}")
        if not match:
            reporter.error(
                f"{path.name}: invalid Connects item; expected "
                "[implemented|planned|detail-only] [[Target]] -> verb phrase: "
                f"{item}"
            )
            continue
        tag, raw_target, label = match.groups()
        target = clean_wikilink(raw_target)
        relationships[tag].add((target, label.strip()))
        model_links.append(("Connects", raw_target))

    for field_name in ("Requires:", "Policies:"):
        for item in extract_list_after(field_name, body):
            links = WIKILINK_RE.findall(item)
            if len(links) != 1:
                reporter.error(
                    f"{path.name}: {field_name[:-1]} item must contain exactly "
                    f"one ordinary wikilink: {item}"
                )
                continue
            model_links.append((field_name[:-1], links[0]))

    return Block(
        title=path.stem,
        path=path,
        frontmatter=frontmatter,
        text=text,
        parent=parent,
        footprints=[
            clean_code_item(item)
            for item in extract_list_after("Code footprint:", body)
        ],
        anchors=[
            clean_code_item(item)
            for item in extract_list_after("Concrete anchors:", body)
        ],
        evidence=extract_list_after("Evidence:", body),
        relationships=relationships,
        model_links=model_links,
    )


def markdown_title(text: str) -> str | None:
    _frontmatter, text = parse_frontmatter(text)
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines():
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            token = fence.group(1)
            if fence_character is None:
                fence_character = token[0]
                fence_length = len(token)
            elif (
                token[0] == fence_character
                and len(token) >= fence_length
                and not line[fence.end() :].strip()
            ):
                fence_character = None
                fence_length = 0
            continue
        if fence_character is not None:
            continue
        heading = re.match(r"^ {0,3}#\s+(.+?)\s*$", line)
        if heading:
            return heading.group(1)
    return None


def leading_markdown_title(text: str) -> str | None:
    """Return an H1 only when it is the first body content in the note."""

    _frontmatter, body = parse_frontmatter(text)
    for line in body.splitlines():
        if not line.strip():
            continue
        heading = re.match(r"^ {0,3}#\s+(.+?)\s*$", line)
        return heading.group(1) if heading else None
    return None


def mermaid_blocks(text: str) -> list[str]:
    return [match.group(1) for match in re.finditer(r"```mermaid\s*\n(.*?)```", text, re.DOTALL)]


def parse_classes(line: str, facts: DiagramFacts) -> None:
    parts = line.strip().split()
    if len(parts) < 3 or parts[0] != "class":
        return
    ids = {value.strip() for value in parts[1].split(",") if value.strip()}
    classes = set(parts[2:])
    if "internal-link" in classes:
        facts.internal_link_ids.update(ids)
    if "planned" in classes:
        facts.planned_ids.update(ids)


def parse_flowchart(code: str, reporter: Reporter, location: str) -> DiagramFacts:
    facts = DiagramFacts()
    raw_edges: list[tuple[str, str, str, str]] = []
    for raw_line in code.splitlines()[1:]:
        line = raw_line.strip()
        if not line or line.startswith(("%%", "classDef", "style", "subgraph", "direction")) or line == "end":
            continue
        if line.startswith("class "):
            parse_classes(line, facts)
            continue
        node = NODE_RE.match(line)
        if node:
            node_id, label = node.groups()
            facts.nodes[node_id] = label.strip()
            continue
        solid = SOLID_EDGE_RE.match(line)
        if solid:
            source, label, target = solid.groups()
            raw_edges.append(("implemented", source, target, label.strip()))
            continue
        planned = PLANNED_EDGE_RE.match(line)
        if planned:
            source, quoted, plain, target = planned.groups()
            label = (quoted or plain or "").strip()
            if not label:
                reporter.error(f"{location}: planned edge must have a verb label: {line}")
            raw_edges.append(("planned", source, target, label))
            continue
        if any(token in line for token in ("-->", "-.")):
            reporter.error(
                f"{location}: unsupported edge syntax; declare nodes separately and "
                f"use one labelled edge per line: {line}"
            )

    for edge_type, source_id, target_id, _label in raw_edges:
        if source_id not in facts.nodes or target_id not in facts.nodes:
            reporter.error(
                f"{location}: edge references undeclared node: {source_id} -> {target_id}"
            )
            continue
        edge = (
            facts.nodes[source_id],
            facts.nodes[target_id],
            normalize_relation_label(_label),
        )
        if edge_type == "implemented":
            facts.solid_edges.add(edge)
        else:
            facts.planned_edges.add(edge)
    return facts


def parse_sequence(code: str, reporter: Reporter, location: str) -> DiagramFacts:
    facts = DiagramFacts()
    messages: list[tuple[str, str, str]] = []
    for raw_line in code.splitlines()[1:]:
        line = raw_line.strip()
        if not line or line.startswith(("%%", "Note", "activate", "deactivate", "autonumber")):
            continue
        participant = PARTICIPANT_RE.match(line)
        if participant:
            participant_id, label = participant.groups()
            facts.nodes[participant_id] = label.strip()
            continue
        message = MESSAGE_RE.match(line)
        if message:
            source_id, target_id, label = message.groups()
            messages.append((source_id, target_id, label))
            continue
    for source_id, target_id, label in messages:
        if source_id not in facts.nodes or target_id not in facts.nodes:
            reporter.error(
                f"{location}: sequence message references undeclared participant: "
                f"{source_id} -> {target_id}"
            )
            continue
        facts.solid_edges.add(
            (
                facts.nodes[source_id],
                facts.nodes[target_id],
                normalize_relation_label(label),
            )
        )
    return facts


def relationship_triples(
    blocks: dict[str, Block], tag: str
) -> set[tuple[str, str, str]]:
    return {
        (block.title, target, normalize_relation_label(label))
        for block in blocks.values()
        for target, label in block.relationships[tag]
    }


def git_revision_context(repo: Path, reporter: Reporter) -> GitRevisionContext | None:
    try:
        format_result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--show-object-format=storage"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        head_result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD^{commit}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        reporter.error(
            "map-version 2 revision validation requires a Git repository with a checked-out HEAD"
        )
        return None

    object_format = format_result.stdout.strip()
    oid_lengths = {"sha1": 40, "sha256": 64}
    oid_length = oid_lengths.get(object_format)
    if oid_length is None:
        reporter.error(f"unsupported Git object format: {object_format or '<missing>'}")
        return None
    head = head_result.stdout.strip().lower()
    if not re.fullmatch(rf"[0-9a-f]{{{oid_length}}}", head):
        reporter.error("Git returned an invalid full HEAD object id")
        return None
    return GitRevisionContext(head, object_format, oid_length)


def resolve_full_commit(
    revision: str,
    repo: Path,
    context: GitRevisionContext,
    location: str,
    reporter: Reporter,
) -> str | None:
    value = revision.strip().lower()
    if not re.fullmatch(rf"[0-9a-f]{{{context.oid_length}}}", value):
        reporter.error(
            f"{location}: revision must be a full {context.object_format} Git object id"
        )
        return None
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{value}^{{commit}}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    resolved = result.stdout.strip().lower() if result.returncode == 0 else ""
    if resolved != value:
        reporter.error(f"{location}: revision does not resolve to a commit: {revision}")
        return None
    return resolved


def validate_v2_revision_contract(
    atlas_path: Path,
    atlas_frontmatter: dict[str, str],
    coverage_path: Path,
    repo: Path,
    reporter: Reporter,
) -> GitRevisionContext | None:
    context = git_revision_context(repo, reporter)
    if context is None:
        return None

    atlas_revision = resolve_full_commit(
        atlas_frontmatter.get("revision", ""),
        repo,
        context,
        atlas_path.name,
        reporter,
    )
    if not coverage_path.is_file():
        reporter.error(f"coverage note does not exist: {coverage_path}")
        return context
    coverage_text = coverage_path.read_text(encoding="utf-8", errors="replace")
    coverage_frontmatter, _body = parse_frontmatter(coverage_text)
    coverage_revision = resolve_full_commit(
        coverage_frontmatter.get("revision", ""),
        repo,
        context,
        coverage_path.name,
        reporter,
    )
    if atlas_revision and coverage_revision and atlas_revision != coverage_revision:
        reporter.error(
            f"{coverage_path.name}: revision must match {atlas_path.name} revision"
        )
    if atlas_revision and atlas_revision != context.head:
        reporter.error(
            f"{atlas_path.name}: revision must equal the currently checked-out HEAD commit"
        )
    if coverage_revision and coverage_revision != context.head:
        reporter.error(
            f"{coverage_path.name}: revision must equal the currently checked-out HEAD commit"
        )
    return context


def working_tree_has_dirty_paths(
    repo: Path, reporter: Reporter
) -> bool | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        reporter.error(f"cannot inspect repository dirty paths: {error}")
        return None
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        reporter.error(
            "cannot inspect repository dirty paths"
            + (f": {message}" if message else "")
        )
        return None
    return bool(result.stdout)


def validate_mapped_target(
    atlas_path: Path,
    atlas_text: str,
    repo: Path,
    reporter: Reporter,
) -> None:
    dirty = working_tree_has_dirty_paths(repo, reporter)
    if dirty is None:
        return
    expected = "HEAD + dirty paths" if dirty else "HEAD"
    actual = extract_scalar("Mapped target:", atlas_text)
    if actual != expected:
        shown = actual or "<missing>"
        reporter.error(
            f"{atlas_path.name}: Mapped target must be `{expected}` for the "
            f"active checkout; found `{shown}`"
        )


def relative_posix_path(
    raw: str, location: str, reporter: Reporter
) -> PurePosixPath | None:
    value = raw.strip()
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        reporter.error(f"{location}: path must be a relative POSIX path: `{raw}`")
        return None
    return path


def resolve_map_artifact(
    map_dir: Path,
    raw: str,
    suffix: str,
    label: str,
    reporter: Reporter,
) -> Path | None:
    relative = relative_posix_path(raw, f"{label} frontmatter", reporter)
    if relative is None:
        return None
    candidate = (map_dir / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(map_dir)
    except ValueError:
        reporter.error(f"{label} artifact escapes project map directory: `{raw}`")
        return None
    if candidate.suffix != suffix:
        reporter.error(f"{label} artifact must use the {suffix} extension: `{raw}`")
        return None
    if not candidate.is_file():
        reporter.error(f"{label} artifact does not exist: {candidate}")
        return None
    return candidate


def resolve_model_wikilink(
    vault: Path,
    raw: str,
    location: str,
    reporter: Reporter,
) -> Path | None:
    """Resolve a model link exactly as one unambiguous Markdown note."""

    target = wikilink_target(raw)
    relative = relative_posix_path(target, location, reporter)
    if relative is None:
        return None
    relative_text = relative.as_posix()
    if target != relative_text:
        reporter.error(
            f"{location}: wikilink path must be normalized POSIX: [[{raw}]]"
        )
        return None
    note_text = relative_text if relative_text.endswith(".md") else f"{relative_text}.md"
    note_relative = PurePosixPath(note_text)
    if len(note_relative.parts) > 1:
        candidate = (vault / Path(*note_relative.parts)).resolve()
        try:
            candidate.relative_to(vault)
        except ValueError:
            reporter.error(f"{location}: wikilink escapes vault: [[{raw}]]")
            return None
        if not candidate.is_file():
            reporter.error(
                f"{location}: path-qualified wikilink target does not exist: [[{raw}]]"
            )
            return None
        return candidate

    matches_found = sorted(
        path.resolve()
        for path in vault.rglob(note_relative.name)
        if path.is_file()
    )
    if not matches_found:
        reporter.error(f"{location}: wikilink target does not exist: [[{raw}]]")
        return None
    if len(matches_found) > 1:
        choices = ", ".join(
            path.relative_to(vault).as_posix() for path in matches_found[:5]
        )
        reporter.error(
            f"{location}: ambiguous wikilink [[{raw}]] resolves to multiple notes "
            f"({choices}); use an exact vault-relative path"
        )
        return None
    return matches_found[0]


def validate_block_model_links(
    blocks: dict[str, Block], vault: Path, reporter: Reporter
) -> None:
    canonical_by_path = {
        block.path.resolve(): block for block in blocks.values()
    }
    for block in blocks.values():
        for field_name, raw in block.model_links:
            location = f"{block.path.name}: {field_name}"
            resolved = resolve_model_wikilink(vault, raw, location, reporter)
            if resolved is None:
                continue
            target_block = canonical_by_path.get(resolved)
            if target_block is None:
                reporter.error(
                    f"{location}: wikilink must resolve to a canonical block note: "
                    f"[[{raw}]]"
                )
                continue
            expected_title = clean_wikilink(raw)
            if target_block.title != expected_title:
                reporter.error(
                    f"{location}: wikilink title does not match its canonical "
                    f"block target [[{target_block.title}]]"
                )


def validate_entry_point_inventory(
    atlas_path: Path,
    map_dir: Path,
    repo: Path,
    vault_arg: str | None,
    reporter: Reporter,
) -> None:
    atlas_text = atlas_path.read_text(encoding="utf-8", errors="replace")
    families = parse_entry_point_inventory(atlas_path, atlas_text, reporter)
    if not families:
        return

    for family in families:
        if family.anchor:
            validate_anchor(
                family.anchor,
                repo,
                f"{atlas_path.name}:{family.row_number}",
                reporter,
            )

    if not vault_arg:
        return
    vault = Path(vault_arg).expanduser().resolve()
    if not vault.is_dir():
        return

    represented_by: dict[Path, EntryPointFamily] = {}
    for family in families:
        if not family.focused_view:
            continue
        link_match = re.fullmatch(r"\[\[([^\]]+)\]\]", family.focused_view)
        if (
            link_match is None
            or "|" in family.focused_view
            or "#" in family.focused_view
        ):
            continue
        raw_link = link_match.group(1)
        location = (
            f"{atlas_path.name}:{family.row_number}: focused view for "
            f"`{family.name}`"
        )
        resolved = resolve_model_wikilink(vault, raw_link, location, reporter)
        if resolved is None:
            continue
        try:
            resolved.relative_to(map_dir)
        except ValueError:
            reporter.error(
                f"{location}: focused view must stay inside the project map"
            )
            continue
        previous = represented_by.get(resolved)
        if previous is not None:
            reporter.error(
                f"{location}: each inventory row needs its own focused view; "
                f"this note already represents `{previous.name}` on row "
                f"{previous.row_number}"
            )
            continue
        represented_by[resolved] = family

        view_text = resolved.read_text(encoding="utf-8", errors="replace")
        view_frontmatter, _body = parse_frontmatter(view_text)
        if view_frontmatter.get("type") != "mental-map-view":
            reporter.error(f"{location}: target must be a mental-map-view note")
            continue
        if view_frontmatter.get("view") not in {"journey", "contract"}:
            reporter.error(
                f"{location}: target view must use `view: journey` or "
                "`view: contract`"
            )
        represented_family = view_frontmatter.get("entry-point-family", "").strip()
        if represented_family != family.name:
            shown = represented_family or "<missing>"
            reporter.error(
                f"{location}: target must declare "
                f"`entry-point-family: {family.name}`; found `{shown}`"
            )


def atlas_links_artifact(
    atlas_text: str,
    artifact: Path,
    map_dir: Path,
    vault: Path,
) -> bool:
    relative = PurePosixPath(artifact.relative_to(map_dir).as_posix())
    vault_relative = PurePosixPath(artifact.relative_to(vault).as_posix())
    same_named_artifacts = [
        path
        for path in map_dir.rglob(relative.name)
        if path.is_file() and path.suffix == artifact.suffix
    ]
    for raw in WIKILINK_RE.findall(atlas_text):
        target = wikilink_target(raw)
        if not target:
            continue
        linked = PurePosixPath(target)
        if linked in {relative, vault_relative}:
            return True
        if (
            len(linked.parts) == 1
            and linked.name == relative.name
            and len(same_named_artifacts) == 1
        ):
            return True
    return False


def atlas_embeds_artifact_view(
    atlas_text: str,
    artifact: Path,
    map_dir: Path,
    vault: Path,
    view_name: str,
) -> bool:
    for raw in re.findall(r"!\[\[([^\]]+)\]\]", atlas_text):
        target = raw.split("|", 1)[0].strip()
        _path, separator, fragment = target.partition("#")
        if separator and fragment.strip() == view_name and atlas_links_artifact(
            f"[[{raw}]]", artifact, map_dir, vault
        ):
            return True
    return False


def atlas_linked_canvases(
    atlas_text: str, map_dir: Path, vault: Path, reporter: Reporter
) -> list[Path]:
    """Resolve every explicit Canvas wikilink in the atlas without guessing."""

    resolved: list[Path] = []
    for raw in WIKILINK_RE.findall(atlas_text):
        target = wikilink_target(raw)
        if not target.endswith(".canvas"):
            continue
        relative = relative_posix_path(
            target, "atlas Canvas wikilink", reporter
        )
        if relative is None:
            continue
        if len(relative.parts) == 1:
            candidates = sorted(
                path.resolve()
                for path in map_dir.rglob(relative.name)
                if path.is_file()
            )
            if not candidates:
                reporter.error(
                    f"atlas Canvas wikilink target does not exist: [[{raw}]]"
                )
                continue
            if len(candidates) > 1:
                reporter.error(
                    f"atlas Canvas wikilink is ambiguous: [[{raw}]]; use an "
                    "exact project-map-relative path"
                )
                continue
            candidate = candidates[0]
        else:
            candidates = []
            for root in (vault, map_dir):
                possible = (root / Path(*relative.parts)).resolve()
                try:
                    possible.relative_to(map_dir)
                except ValueError:
                    continue
                if possible.is_file() and possible not in candidates:
                    candidates.append(possible)
            if not candidates:
                reporter.error(
                    f"atlas Canvas wikilink target does not exist: [[{raw}]]"
                )
                continue
            if len(candidates) > 1:
                reporter.error(
                    f"atlas Canvas wikilink is ambiguous: [[{raw}]]; use its "
                    "exact vault-relative path"
                )
                continue
            candidate = candidates[0]
        if candidate not in resolved:
            resolved.append(candidate)
    return resolved


def resolve_canvas_file(
    vault: Path, raw: str, canvas_path: Path, reporter: Reporter
) -> Path | None:
    canvas_name = canvas_path.name
    if raw != raw.strip():
        reporter.error(
            f"{canvas_name}: Canvas file card path has surrounding whitespace: "
            f"`{raw}`"
        )
        return None
    relative = relative_posix_path(
        raw, f"{canvas_name}: Canvas file card", reporter
    )
    if relative is None:
        return None
    normalized = relative.as_posix()
    if raw != normalized:
        reporter.error(
            f"{canvas_name}: Canvas file card path must be a normalized "
            f"vault-relative POSIX path; use `{normalized}` instead of `{raw}`"
        )
        return None
    candidate = (vault / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(vault)
    except ValueError:
        reporter.error(f"{canvas_name}: Canvas file card escapes vault: `{raw}`")
        return None
    if not candidate.is_file():
        canvas_relative_candidate = (
            canvas_path.parent / Path(*relative.parts)
        ).resolve()
        try:
            canvas_relative_vault_path = canvas_relative_candidate.relative_to(vault)
        except ValueError:
            canvas_relative_vault_path = None
        if (
            canvas_relative_vault_path is not None
            and canvas_relative_candidate.is_file()
        ):
            expected = canvas_relative_vault_path.as_posix()
            reporter.error(
                f"{canvas_name}: Canvas file card uses a Canvas-relative path; "
                f"Obsidian requires a vault-relative path: use `{expected}` "
                f"instead of `{raw}`"
            )
            return None
        reporter.error(f"{canvas_name}: Canvas file card target does not exist: `{raw}`")
        return None
    return candidate


def validate_canvas(
    canvas_path: Path,
    vault: Path,
    blocks: dict[str, Block],
    reporter: Reporter,
    *,
    compact: bool = False,
    relationships: bool = False,
    semantic_groups: list[CanvasSemanticGroup] | None = None,
) -> DiagramFacts:
    facts = DiagramFacts()
    try:
        data = json.loads(
            canvas_path.read_text(encoding="utf-8", errors="replace")
        )
    except (OSError, json.JSONDecodeError) as error:
        reporter.error(f"{canvas_path.name}: invalid JSON Canvas: {error}")
        return facts
    if not isinstance(data, dict):
        reporter.error(f"{canvas_path.name}: JSON Canvas root must be an object")
        return facts

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    if not isinstance(nodes, list):
        reporter.error(f"{canvas_path.name}: nodes must be an array")
        nodes = []
    if not isinstance(edges, list):
        reporter.error(f"{canvas_path.name}: edges must be an array")
        edges = []

    block_by_path = {block.path.resolve(): block for block in blocks.values()}
    node_titles: dict[str, str | None] = {}
    canonical_card_ids: dict[Path, str] = {}
    canonical_rectangles: dict[str, tuple[int, int, int, int]] = {}
    canonical_positions: dict[str, int] = {}
    group_rectangles: dict[str, tuple[str, int, int, int, int, int]] = {}
    all_ids: set[str] = set()
    valid_node_types = {"text", "file", "link", "group"}

    for position, node in enumerate(nodes, start=1):
        location = f"{canvas_path.name}: node {position}"
        if not isinstance(node, dict):
            reporter.error(f"{location} must be an object")
            continue
        for field_name in ("x", "y"):
            if type(node.get(field_name)) is not int:
                reporter.error(f"{location} {field_name} must be an integer")
        for field_name in ("width", "height"):
            value = node.get(field_name)
            if type(value) is not int or value <= 0:
                reporter.error(
                    f"{location} {field_name} must be a positive integer"
                )
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            reporter.error(f"{location} needs a non-empty string id")
            continue
        if node_id in all_ids:
            reporter.error(f"{canvas_path.name}: duplicate Canvas id: {node_id}")
            continue
        all_ids.add(node_id)

        node_type = node.get("type")
        if node_type not in valid_node_types:
            reporter.error(f"{location} has unsupported type: {node_type!r}")
            node_titles[node_id] = None
            continue
        node_titles[node_id] = None
        if node_id.startswith("mental-map:block:") and node_type != "file":
            reporter.error(
                f"{location} generated block card must use type `file` so it "
                "opens its canonical Markdown note"
            )
            continue
        if node_type == "text" and not isinstance(node.get("text"), str):
            reporter.error(f"{location} text node needs a string text value")
        if node_type == "link" and not isinstance(node.get("url"), str):
            reporter.error(f"{location} link node needs a string url value")
        if node_type == "group":
            label = node.get("label")
            if not isinstance(label, str) or not label.strip():
                reporter.error(f"{location} group node needs a non-empty label")
            geometry = tuple(
                node.get(field) for field in ("x", "y", "width", "height")
            )
            if (
                isinstance(label, str)
                and label.strip()
                and all(type(value) is int for value in geometry)
                and geometry[2] > 0
                and geometry[3] > 0
            ):
                group_rectangles[node_id] = (label, *geometry, position)
        if node_type != "file":
            continue

        raw_file = node.get("file")
        if not isinstance(raw_file, str) or not raw_file.strip():
            reporter.error(f"{location} needs a non-empty file path")
            continue
        file_path = resolve_canvas_file(
            vault, raw_file, canvas_path, reporter
        )
        if file_path is None:
            continue
        subpath = node.get("subpath")
        if subpath is not None and (
            not isinstance(subpath, str) or not subpath.startswith("#")
        ):
            reporter.error(f"{location} subpath must start with '#'")
        block = block_by_path.get(file_path)
        if block is None:
            if not node_id.startswith("mental-map:"):
                continue
            reporter.error(
                f"{location} generated file card must point to a canonical "
                f"mental-map block: `{raw_file}`"
            )
            continue

        expected_file = block.path.relative_to(vault).as_posix()
        atlas_id = block.frontmatter.get("atlas-id", "").strip()
        expected_id = f"mental-map:block:{atlas_id}"
        previous_id = canonical_card_ids.get(file_path)
        if previous_id is not None:
            reporter.error(
                f"{location} duplicates canonical block card [[{block.title}]] "
                f"already represented by node `{previous_id}`"
            )
        else:
            canonical_card_ids[file_path] = node_id
        if raw_file != expected_file:
            reporter.error(
                f"{location} file path must exactly match the canonical "
                f"vault-relative block path: use `{expected_file}` instead of "
                f"`{raw_file}`"
            )
        if node_id != expected_id:
            reporter.error(
                f"{location} canonical block card id must be `{expected_id}` "
                f"for [[{block.title}]]; manual ids are not allowed"
            )
            continue
        expected_subpath = f"#{block.title}"
        if subpath != expected_subpath:
            reporter.error(
                f"{location} must use subpath `{expected_subpath}` so the "
                "file-backed card skips Properties and exposes a native drag "
                "surface outside edit mode"
            )
        node_titles[node_id] = block.title
        facts.nodes[node_id] = block.title
        geometry = tuple(node.get(field) for field in ("x", "y", "width", "height"))
        if (
            all(type(value) is int for value in geometry)
            and geometry[2] > 0
            and geometry[3] > 0
        ):
            canonical_rectangles[block.title] = geometry
            canonical_positions[block.title] = position

    if compact or relationships:
        rectangles = list(canonical_rectangles.items())
        for index, first in enumerate(rectangles):
            first_title, (first_x, first_y, first_width, first_height) = first
            for second in rectangles[index + 1 :]:
                second_title, (
                    second_x,
                    second_y,
                    second_width,
                    second_height,
                ) = second
                overlaps = (
                    first_x < second_x + second_width
                    and second_x < first_x + first_width
                    and first_y < second_y + second_height
                    and second_y < first_y + first_height
                )
                if overlaps:
                    canvas_kind = (
                        "compact" if compact else "all-relationships"
                    )
                    reporter.error(
                        f"{canvas_path.name}: {canvas_kind} canonical block cards overlap: "
                        f"[[{first_title}]] and [[{second_title}]]"
                    )

    implemented = relationship_triples(blocks, "implemented")
    seen_relationships: set[tuple[str, str, str]] = set()
    for position, edge in enumerate(edges, start=1):
        location = f"{canvas_path.name}: edge {position}"
        if not isinstance(edge, dict):
            reporter.error(f"{location} must be an object")
            continue
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not edge_id.strip():
            reporter.error(f"{location} needs a non-empty string id")
            continue
        if edge_id in all_ids:
            reporter.error(f"{canvas_path.name}: duplicate Canvas id: {edge_id}")
            continue
        all_ids.add(edge_id)
        label = edge.get("label")
        edge_enums = {
            "fromSide": {"top", "right", "bottom", "left"},
            "toSide": {"top", "right", "bottom", "left"},
            "fromEnd": {"none", "arrow"},
            "toEnd": {"none", "arrow"},
        }
        for field_name, allowed in edge_enums.items():
            if field_name in edge and edge[field_name] not in allowed:
                reporter.error(
                    f"{location} {field_name} must be one of "
                    f"{', '.join(sorted(allowed))}"
                )

        source_id = edge.get("fromNode")
        target_id = edge.get("toNode")
        if not isinstance(source_id, str) or not isinstance(target_id, str):
            reporter.error(f"{location} needs string fromNode and toNode ids")
            continue
        dangling = False
        for endpoint in (source_id, target_id):
            if endpoint not in node_titles:
                reporter.error(f"{location} references missing node id: {endpoint}")
                dangling = True
        if dangling:
            continue

        source = node_titles[source_id]
        target = node_titles[target_id]
        if source is None or target is None:
            if edge_id.startswith("mental-map:"):
                reporter.error(
                    f"{location} generated edge must connect generated canonical "
                    "block cards"
                )
            continue
        if edge.get("fromEnd", "none") != "none" or edge.get(
            "toEnd", "arrow"
        ) != "arrow":
            reporter.error(
                f"{location} must use fromEnd=none and toEnd=arrow for canonical direction"
            )
            continue
        if not isinstance(label, str) or not label.strip():
            if not relationships:
                reporter.error(f"{location} needs a relationship label")
                continue
            candidates = {
                triple
                for triple in implemented - seen_relationships
                if triple[0] == source and triple[1] == target
            }
            if len(candidates) != 1:
                reporter.error(
                    f"{location} needs a relationship label because "
                    f"{source} -> {target} does not identify exactly one "
                    "unprojected [implemented] relationship"
                )
                continue
            triple = next(iter(candidates))
        else:
            triple = (source, target, normalize_relation_label(label))
        if triple not in implemented:
            reporter.error(
                f"{location} lacks a matching source-note [implemented] relationship: "
                f"{source} -> {target} ({triple[2]})"
            )
            continue
        if triple in seen_relationships:
            reporter.error(
                f"{location} is a duplicate semantic relationship edge: "
                f"{source} -> {target} ({triple[2]})"
            )
        seen_relationships.add(triple)
        facts.solid_edges.add(triple)
    if compact or relationships:
        validate_grouped_canvas_semantics(
            canvas_path,
            blocks,
            facts,
            canonical_rectangles,
            canonical_positions,
            group_rectangles,
            semantic_groups or [],
            reporter,
            compact=compact,
        )
    return facts


def rectangles_overlap(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> bool:
    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    return (
        first_x < second_x + second_width
        and second_x < first_x + first_width
        and first_y < second_y + second_height
        and second_y < first_y + first_height
    )


def rectangle_contains(
    outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]
) -> bool:
    outer_x, outer_y, outer_width, outer_height = outer
    inner_x, inner_y, inner_width, inner_height = inner
    return (
        outer_x <= inner_x
        and outer_y <= inner_y
        and inner_x + inner_width <= outer_x + outer_width
        and inner_y + inner_height <= outer_y + outer_height
    )


def validate_grouped_canvas_semantics(
    canvas_path: Path,
    blocks: dict[str, Block],
    facts: DiagramFacts,
    canonical_rectangles: dict[str, tuple[int, int, int, int]],
    canonical_positions: dict[str, int],
    group_rectangles: dict[str, tuple[str, int, int, int, int, int]],
    semantic_groups: list[CanvasSemanticGroup],
    reporter: Reporter,
    *,
    compact: bool,
) -> None:
    """Validate semantic grouping for compact and exhaustive Canvases."""

    canvas_name = canvas_path.name
    card_titles = set(facts.nodes.values())
    implemented_card_titles = {
        title
        for title in card_titles
        if blocks[title].frontmatter.get("status") == "implemented"
    }
    if compact:
        orientation_titles = {
            block.title
            for block in blocks.values()
            if block.frontmatter.get("status") == "implemented"
            and (
                block.parent is None
                or block.frontmatter.get("level") in {"context", "runtime"}
            )
        }
        for title in sorted(orientation_titles - card_titles):
            reporter.error(
                f"{canvas_name}: compact Canvas omits orientation block [[{title}]]; "
                "implemented root, context, and runtime blocks cannot be delegated "
                "to Mermaid or scoped views"
            )

        if len(implemented_card_titles) > 1:
            incident_titles = {
                title
                for source, target, _label in facts.solid_edges
                for title in (source, target)
            }
            for title in sorted(implemented_card_titles - incident_titles):
                reporter.error(
                    f"{canvas_name}: compact Canvas has unexplained isolated card "
                    f"[[{title}]]; connect it with a canonical orientation relationship "
                    "or move the non-orienting detail to a scoped view"
                )

    if not semantic_groups:
        return

    block_by_title = {block.title: block for block in blocks.values()}
    declared_by_id = {
        f"mental-map:group:{group.scope_key}": group for group in semantic_groups
    }
    declared_group_for_member: dict[str, CanvasSemanticGroup] = {}
    for group in semantic_groups:
        if not group.members:
            reporter.error(
                f"{canvas_name}: declared semantic group `{group.name}` needs at "
                "least one canonical member"
            )
        for member in group.members:
            block = block_by_title.get(member)
            if block is None:
                reporter.error(
                    f"{canvas_name}: declared semantic group `{group.name}` names "
                    f"unknown block [[{member}]]"
                )
                continue
            if block.frontmatter.get("status") == "deprecated":
                reporter.error(
                    f"{canvas_name}: semantic group `{group.name}` cannot "
                    f"use deprecated block [[{member}]]"
                )
            declared_group_for_member[member] = group
            if member not in card_titles:
                reporter.error(
                    f"{canvas_name}: declared semantic group `{group.name}` member "
                    f"[[{member}]] is missing its Canvas card"
                )

    if compact:
        for title in sorted(card_titles - set(declared_group_for_member)):
            reporter.error(
                f"{canvas_name}: compact Canvas card [[{title}]] is not assigned to "
                "exactly one declared semantic group"
            )
    else:
        for title in sorted(card_titles - set(declared_group_for_member)):
            ancestor = blocks[title].parent
            visited: set[str] = set()
            while ancestor and ancestor not in visited:
                visited.add(ancestor)
                inherited_group = declared_group_for_member.get(ancestor)
                if inherited_group is not None:
                    declared_group_for_member[title] = inherited_group
                    break
                ancestor_block = blocks.get(ancestor)
                ancestor = ancestor_block.parent if ancestor_block else None
            if title not in declared_group_for_member:
                reporter.error(
                    f"{canvas_name}: all-relationships Canvas card [[{title}]] "
                    "cannot inherit a declared semantic group from its parent chain"
                )

    for node_id in sorted(set(group_rectangles) - set(declared_by_id)):
        reporter.error(
            f"{canvas_name}: Canvas group node `{node_id}` is not declared in "
            "the atlas Canvas semantic groups table"
        )

    valid_group_rectangles: dict[str, tuple[int, int, int, int]] = {}
    group_positions: dict[str, int] = {}
    for node_id, group in declared_by_id.items():
        rendered = group_rectangles.get(node_id)
        if rendered is None:
            reporter.error(
                f"{canvas_name}: missing declared semantic group node `{node_id}`"
            )
            continue
        label, x, y, width, height, position = rendered
        if label != group.name:
            reporter.error(
                f"{canvas_name}: semantic group node `{node_id}` label must be "
                f"exactly `{group.name}`"
            )
        valid_group_rectangles[group.scope_key] = (x, y, width, height)
        group_positions[group.scope_key] = position

    rendered_groups = list(valid_group_rectangles.items())
    for index, (first_key, first_rectangle) in enumerate(rendered_groups):
        for second_key, second_rectangle in rendered_groups[index + 1 :]:
            if rectangles_overlap(first_rectangle, second_rectangle):
                reporter.error(
                    f"{canvas_name}: semantic group rectangles overlap: "
                    f"`{first_key}` and `{second_key}`"
                )

    for title, group in declared_group_for_member.items():
        card_rectangle = canonical_rectangles.get(title)
        group_rectangle = valid_group_rectangles.get(group.scope_key)
        if card_rectangle is None or group_rectangle is None:
            continue
        if not rectangle_contains(group_rectangle, card_rectangle):
            reporter.error(
                f"{canvas_name}: [[{title}]] must be fully contained by declared "
                f"semantic group `{group.name}`"
            )
        group_position = group_positions[group.scope_key]
        card_position = canonical_positions.get(title)
        if card_position is not None and group_position > card_position:
            reporter.error(
                f"{canvas_name}: semantic group `{group.name}` must appear before "
                f"its member [[{title}]] in the nodes array so the group renders behind it"
            )

    if not compact:
        return

    group_keys = {
        group.scope_key
        for group in semantic_groups
        if any(member in implemented_card_titles for member in group.members)
    }
    if len(group_keys) > 1:
        adjacency: dict[str, set[str]] = {key: set() for key in group_keys}
        for source, target, _label in facts.solid_edges:
            source_group = declared_group_for_member.get(source)
            target_group = declared_group_for_member.get(target)
            if (
                source_group is None
                or target_group is None
                or source_group.scope_key == target_group.scope_key
            ):
                continue
            adjacency[source_group.scope_key].add(target_group.scope_key)
            adjacency[target_group.scope_key].add(source_group.scope_key)
        start = next(iter(group_keys))
        reached = {start}
        frontier = [start]
        while frontier:
            current = frontier.pop()
            for neighbor in adjacency[current] - reached:
                reached.add(neighbor)
                frontier.append(neighbor)
        disconnected = sorted(group_keys - reached)
        if disconnected:
            reporter.error(
                f"{canvas_name}: semantic groups do not form one canonical "
                "orientation backbone; disconnected groups: "
                + ", ".join(f"`{key}`" for key in disconnected)
            )


def validate_base(
    base_path: Path, project: str, reporter: Reporter
) -> None:
    try:
        text = base_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        reporter.error(f"{base_path.name}: cannot read Base: {error}")
        return
    for detail in yaml_surface_errors(text, require_top_level_scalars=False):
        reporter.error(f"{base_path.name}: invalid Base YAML: {detail}")
    if not re.search(r"(?m)^filters:\s*(?:#.*)?$", text):
        reporter.error(f"{base_path.name}: Base needs a top-level filters section")

    comparisons = {
        (match.group(1), match.group(3))
        for match in re.finditer(
            r"(?:note\.)?(type|project)\s*==\s*(['\"])(.*?)\2", text
        )
    }
    if ("type", "mental-map-block") not in comparisons:
        reporter.error(
            f'{base_path.name}: Base must filter type == "mental-map-block"'
        )
    if project and ("project", project) not in comparisons:
        reporter.error(
            f'{base_path.name}: Base must filter project == "{project}"'
        )

    views_match = re.search(r"(?m)^views:\s*(?:#.*)?$", text)
    if views_match is None:
        reporter.error(f"{base_path.name}: Base needs a top-level views section")
        return
    views_text = text[views_match.end() :]
    if not re.search(r"(?m)^\s*-\s+type:\s*\S+", views_text):
        reporter.error(f"{base_path.name}: Base needs at least one configured view")
    columns = set(
        re.findall(r"(?m)^\s*-\s+([A-Za-z_][\w.-]*)\s*(?:#.*)?$", views_text)
    )
    missing = sorted(
        {
            "file.name",
            "kind",
            "level",
            "status",
            "confidence",
            "reviewed-revision",
        }
        - columns
    )
    if missing:
        reporter.error(
            f"{base_path.name}: Base view is missing required columns: "
            f"{', '.join(missing)}"
        )
    if not re.search(
        r'''(?m)^\s+name:\s*(?:["']Needs review["']|Needs review)\s*(?:#.*)?$''',
        views_text,
    ):
        reporter.error(f"{base_path.name}: Base needs a `Needs review` view")
    if not re.search(
        r'''note\[\s*["']reviewed-revision["']\s*\]\s*!=\s*'''
        r'''this(?:\.revision|\[\s*["']revision["']\s*\])''',
        views_text,
    ):
        reporter.error(
            f"{base_path.name}: `Needs review` must compare "
            'note["reviewed-revision"] with this.revision'
        )


def validate_native_views(
    atlas_path: Path,
    atlas_frontmatter: dict[str, str],
    map_dir: Path,
    vault_arg: str | None,
    blocks: dict[str, Block],
    project: str,
    reporter: Reporter,
) -> tuple[bool, DiagramFacts | None]:
    map_version = atlas_frontmatter.get("map-version")
    if map_version not in {None, "", "1", "2"}:
        reporter.error(
            f"{atlas_path.name}: unsupported map-version: {map_version}"
        )
    if map_version != "2":
        return False, None

    atlas_text = atlas_path.read_text(encoding="utf-8", errors="replace")
    semantic_groups = parse_canvas_semantic_groups(
        atlas_path, atlas_text, reporter
    )
    for field_name in (
        "Purpose:",
        "Domain boundary:",
        "Quality priorities:",
        "Current risks:",
        "Coverage summary:",
        "Unresolved questions:",
        "Start here:",
    ):
        value = extract_scalar(field_name, atlas_text)
        if not value:
            reporter.error(
                f"{atlas_path.name}: map-version 2 needs a non-empty {field_name} line"
            )
        elif re.search(r"\bDRAFT\b", value, re.IGNORECASE):
            reporter.error(
                f"{atlas_path.name}: {field_name} must replace the DRAFT placeholder"
            )
    canvas_ref = atlas_frontmatter.get("canvas")
    relationships_canvas_ref = atlas_frontmatter.get("relationships-canvas")
    base_ref = atlas_frontmatter.get("base")
    sync_state_ref = atlas_frontmatter.get("sync-state")
    if not canvas_ref:
        reporter.error(f"{atlas_path.name}: map-version 2 requires canvas frontmatter")
    if not relationships_canvas_ref:
        reporter.error(
            f"{atlas_path.name}: map-version 2 requires "
            "relationships-canvas frontmatter"
        )
    if not base_ref:
        reporter.error(f"{atlas_path.name}: map-version 2 requires base frontmatter")
    if not sync_state_ref:
        reporter.error(
            f"{atlas_path.name}: map-version 2 requires sync-state frontmatter"
        )
    else:
        state_path = relative_posix_path(
            sync_state_ref, "sync-state frontmatter", reporter
        )
        if state_path is not None and state_path.suffix != ".json":
            reporter.error(
                f"{atlas_path.name}: sync-state frontmatter must name a .json sidecar"
            )
    if not vault_arg:
        reporter.error(f"{atlas_path.name}: map-version 2 requires --vault")
        return True, DiagramFacts()

    vault = Path(vault_arg).expanduser().resolve()
    if not vault.is_dir():
        reporter.error(f"Obsidian vault does not exist: {vault}")
        return True, DiagramFacts()
    if not (vault / ".obsidian").is_dir():
        reporter.error(
            "Obsidian vault root must contain .obsidian/: "
            f"{vault}; pass the exact directory Obsidian opened"
        )
        return True, DiagramFacts()
    try:
        map_dir.relative_to(vault)
    except ValueError:
        reporter.error(f"project map directory is outside Obsidian vault: {map_dir}")
        return True, DiagramFacts()

    validate_block_model_links(blocks, vault, reporter)

    canvas_facts = DiagramFacts()
    canvas_refs = [("Canvas", canvas_ref)]
    if relationships_canvas_ref:
        canvas_refs.append(("Relationships Canvas", relationships_canvas_ref))

    implemented = relationship_triples(blocks, "implemented")
    resolved_canvases: list[tuple[Path, str]] = []
    for label, reference in canvas_refs:
        if not reference:
            continue
        canvas_path = resolve_map_artifact(
            map_dir, reference, ".canvas", label, reporter
        )
        if canvas_path is None:
            continue
        existing_label = None
        for existing_path, candidate_label in resolved_canvases:
            try:
                same_file = canvas_path.samefile(existing_path)
            except OSError:
                same_file = canvas_path == existing_path
            if same_file:
                existing_label = candidate_label
                break
        if existing_label is not None:
            reporter.error(
                f"{atlas_path.name}: relationships-canvas must resolve to a "
                f"separate Canvas file from {existing_label.lower()}"
            )
            continue
        resolved_canvases.append((canvas_path, label))
        if not atlas_links_artifact(atlas_text, canvas_path, map_dir, vault):
            reporter.error(
                f"{atlas_path.name}: atlas must link or embed [[{reference}]]"
            )
        facts = validate_canvas(
            canvas_path,
            vault,
            blocks,
            reporter,
            compact=label == "Canvas",
            relationships=label == "Relationships Canvas",
            semantic_groups=(
                semantic_groups
                if label in {"Canvas", "Relationships Canvas"}
                else None
            ),
        )
        if label == "Canvas":
            active_titles = {
                block.title
                for block in blocks.values()
                if block.frontmatter.get("status") != "deprecated"
            }
            active_cards = active_titles.intersection(facts.nodes.values())
            if active_titles and not active_cards:
                reporter.error(
                    f"{canvas_path.name}: compact Canvas needs at least one "
                    "active canonical file-backed block card"
                )
        canvas_facts.nodes.update(facts.nodes)
        canvas_facts.solid_edges.update(facts.solid_edges)
        canvas_facts.planned_edges.update(facts.planned_edges)
        if label == "Relationships Canvas":
            for edge in sorted(implemented - facts.solid_edges):
                reporter.error(
                    f"{canvas_path.name}: all-relationships view omits [implemented] "
                    f"relationship: {edge[0]} -> {edge[1]} ({edge[2]})"
                )

    for scoped_canvas in atlas_linked_canvases(
        atlas_text, map_dir, vault, reporter
    ):
        already_validated = False
        for configured_canvas, _label in resolved_canvases:
            try:
                already_validated = scoped_canvas.samefile(configured_canvas)
            except OSError:
                already_validated = scoped_canvas == configured_canvas
            if already_validated:
                break
        if already_validated:
            continue
        facts = validate_canvas(
            scoped_canvas,
            vault,
            blocks,
            reporter,
        )
        canvas_facts.nodes.update(facts.nodes)
        canvas_facts.solid_edges.update(facts.solid_edges)
        canvas_facts.planned_edges.update(facts.planned_edges)

    if base_ref:
        base_path = resolve_map_artifact(
            map_dir, base_ref, ".base", "Base", reporter
        )
        if base_path is not None:
            if not atlas_links_artifact(atlas_text, base_path, map_dir, vault):
                reporter.error(
                    f"{atlas_path.name}: atlas must link or embed [[{base_ref}]]"
                )
            if not atlas_embeds_artifact_view(
                atlas_text, base_path, map_dir, vault, "Needs review"
            ):
                reporter.error(
                    f"{atlas_path.name}: atlas must embed "
                    f"![[{base_ref}#Needs review]]"
                )
            validate_base(base_path, project, reporter)
    return True, canvas_facts


def validate_blocks(
    blocks: dict[str, Block],
    index_text: str | None,
    repo: Path,
    reporter: Reporter,
    map_version: str | None = None,
    revision_context: GitRevisionContext | None = None,
) -> None:
    index_counts = Counter(
        clean_wikilink(raw) for raw in WIKILINK_RE.findall(index_text or "")
    )
    atlas_ids: dict[str, list[str]] = defaultdict(list)
    for block in blocks.values():
        fm = block.frontmatter
        title = leading_markdown_title(block.text)
        if title != block.title:
            reporter.error(
                f"{block.path.name}: H1 must exactly match filename ({block.title})"
            )
        reserved_tokens = [
            token for token in RESERVED_BLOCK_TITLE_TOKENS if token in block.title
        ]
        title_grammar_errors: list[str] = []
        if block.title != block.title.strip():
            title_grammar_errors.append("has surrounding whitespace")
        if block.title.endswith("."):
            title_grammar_errors.append("ends in a dot")
        if any(ord(character) < 32 or ord(character) == 127 for character in block.title):
            title_grammar_errors.append("contains a control character")
        if reserved_tokens:
            title_grammar_errors.append(
                "contains reserved syntax " + ", ".join(reserved_tokens)
            )
        if title_grammar_errors:
            reporter.error(
                f"{block.path.name}: block title violates the safe one-component "
                f"Obsidian filename grammar: {'; '.join(title_grammar_errors)}"
            )
        if fm.get("type") != "mental-map-block":
            reporter.error(f"{block.path.name}: type must be mental-map-block")
        if fm.get("kind") not in VALID_KINDS:
            reporter.error(f"{block.path.name}: invalid kind: {fm.get('kind', '<missing>')}")
        if fm.get("level") not in VALID_LEVELS:
            reporter.error(f"{block.path.name}: invalid level: {fm.get('level', '<missing>')}")
        status = fm.get("status")
        if status not in VALID_STATUSES:
            reporter.error(f"{block.path.name}: invalid status: {status or '<missing>'}")
        if not extract_scalar("Purpose:", block.text):
            reporter.error(f"{block.path.name}: block needs a one-sentence Purpose")
        if fm.get("kind") == "responsibility" and not extract_scalar(
            "Hides:", block.text
        ):
            reporter.error(f"{block.path.name}: responsibility needs a one-sentence Hides")
        if block.footprints and fm.get("kind") != "responsibility":
            reporter.error(
                f"{block.path.name}: only kind responsibility may declare Code footprint"
            )
        if block.footprints and status in {"planned", "deprecated"}:
            reporter.error(
                f"{block.path.name}: {status} blocks must not own Code footprint"
            )
        if index_text is not None and index_counts[block.title] != 1:
            reporter.error(
                f"{block.path.name}: index must link this block exactly once; "
                f"found {index_counts[block.title]}"
            )
        if map_version == "2":
            atlas_id = fm.get("atlas-id", "").strip()
            if not atlas_id:
                reporter.error(f"{block.path.name}: map-version 2 requires atlas-id")
            else:
                atlas_ids[atlas_id].append(block.path.name)
            if fm.get("confidence") not in VALID_CONFIDENCES:
                reporter.error(
                    f"{block.path.name}: confidence must be one of "
                    "accounted, traced, deeply-inspected"
                )
        if block.parent and block.parent not in blocks:
            reporter.error(f"{block.path.name}: missing parent block [[{block.parent}]]")
        for tag, relations in block.relationships.items():
            for target, label in relations:
                if target not in blocks:
                    reporter.error(
                        f"{block.path.name}: {tag} relationship target is missing: [[{target}]]"
                    )
                if len(label.split()) < 2:
                    reporter.warn(
                        f"{block.path.name}: relationship label may be too vague: {label}"
                    )
        if status == "implemented" and fm.get("kind") == "responsibility":
            if not block.footprints:
                reporter.error(f"{block.path.name}: implemented responsibility needs Code footprint")
            if not block.anchors:
                reporter.error(f"{block.path.name}: implemented responsibility needs Concrete anchors")
            if map_version == "2" and not fm.get("reviewed-revision", "").strip():
                reporter.error(
                    f"{block.path.name}: implemented responsibility needs reviewed-revision"
                )
        reviewed_revision = fm.get("reviewed-revision", "").strip()
        if (
            status == "implemented"
            and map_version == "2"
            and reviewed_revision
            and revision_context is not None
        ):
            resolve_full_commit(
                reviewed_revision,
                repo,
                revision_context,
                f"{block.path.name}: reviewed-revision",
                reporter,
            )
        if status == "planned" and not block.evidence:
            reporter.error(f"{block.path.name}: planned block needs Evidence")
        if status == "deprecated" and not extract_scalar("Deprecation:", block.text):
            reporter.error(f"{block.path.name}: deprecated block needs Deprecation")
        if status == "implemented" and not block.evidence:
            reporter.error(f"{block.path.name}: implemented block needs Evidence")
        if (
            status in {"implemented", "planned"}
            and block.evidence
            and not any(EVIDENCE_REFERENCE_RE.search(item) for item in block.evidence)
        ):
            reporter.error(
                f"{block.path.name}: active block Evidence must cite a concrete "
                "full revision, issue/ticket/PR, ADR, PRD, or architecture document"
            )
        for anchor in block.anchors:
            validate_anchor(anchor, repo, block.path.name, reporter)

    if index_text is not None:
        extra_index = sorted(set(index_counts) - set(blocks))
        for title in extra_index:
            reporter.error(f"index links non-block note or missing block: [[{title}]]")
    for atlas_id, note_names in sorted(atlas_ids.items()):
        if len(note_names) > 1:
            reporter.error(
                f"duplicate atlas-id `{atlas_id}`: {', '.join(sorted(note_names))}"
            )
    validate_parent_hierarchy(blocks, reporter)


def validate_parent_hierarchy(
    blocks: dict[str, Block], reporter: Reporter
) -> None:
    complete: set[str] = set()
    active: list[str] = []
    active_positions: dict[str, int] = {}
    reported_cycles: set[tuple[str, ...]] = set()

    def visit(title: str) -> None:
        if title in complete:
            return
        if title in active_positions:
            cycle = tuple(active[active_positions[title] :] + [title])
            identity = tuple(sorted(set(cycle)))
            if identity not in reported_cycles:
                reported_cycles.add(identity)
                reporter.error(
                    "parent hierarchy contains a cycle: " + " -> ".join(cycle)
                )
            return
        active_positions[title] = len(active)
        active.append(title)
        parent = blocks[title].parent
        if parent in blocks:
            visit(parent)
        active.pop()
        active_positions.pop(title, None)
        complete.add(title)

    for title in sorted(blocks):
        visit(title)


def validate_anchor(anchor: str, repo: Path, note_name: str, reporter: Reporter) -> None:
    path_text, separator, symbol = anchor.partition(" :: ")
    if "::" in anchor and not separator:
        reporter.error(
            f"{note_name}: concrete anchor must use `path :: symbol` with "
            f"one space around `::`: `{anchor}`"
        )
        return
    if separator and (not symbol or " :: " in symbol or not ANCHOR_SYMBOL_RE.fullmatch(symbol)):
        reporter.error(
            f"{note_name}: concrete anchor symbol must be a bare or "
            f"dot-qualified token: `{anchor}`"
        )
        return
    if GLOB_META_RE.search(path_text):
        reporter.error(f"{note_name}: concrete anchor must be an exact path: `{anchor}`")
        return
    relative = relative_posix_path(
        path_text, f"{note_name}: concrete anchor", reporter
    )
    if relative is None:
        return
    if path_text != relative.as_posix():
        reporter.error(
            f"{note_name}: concrete anchor path must be normalized repo-relative "
            f"POSIX: `{path_text}`"
        )
        return
    path = (repo / Path(*relative.parts)).resolve()
    try:
        path.relative_to(repo)
    except ValueError:
        reporter.error(f"{note_name}: anchor path escapes repository: `{path_text}`")
        return
    if not path.exists() or not path.is_file():
        reporter.error(f"{note_name}: anchor path not found: `{path_text}`")
        return
    if separator:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            reporter.error(f"{note_name}: cannot read anchor path: `{path_text}`")
            return
        for segment in symbol.split("."):
            token_pattern = re.compile(
                rf"(?<![\w$-]){re.escape(segment)}(?![\w$-])",
                re.UNICODE,
            )
            if not token_pattern.search(text):
                reporter.error(
                    f"{note_name}: anchor symbol segment `{segment}` not found "
                    f"as a complete token: `{anchor}`"
                )
                return


def validate_views(
    atlas_path: Path,
    view_paths: list[Path],
    blocks: dict[str, Block],
    max_nodes: int | None,
    reporter: Reporter,
    canvas_facts: DiagramFacts | None = None,
    atlas_uses_canvas: bool = False,
) -> None:
    implemented = relationship_triples(blocks, "implemented")
    planned = relationship_triples(blocks, "planned")
    projected_implemented: set[tuple[str, str, str]] = set(
        canvas_facts.solid_edges if canvas_facts else ()
    )
    projected_planned: set[tuple[str, str, str]] = set()
    projected_nodes: set[str] = set(
        canvas_facts.nodes.values() if canvas_facts else ()
    )
    atlas_text = atlas_path.read_text(encoding="utf-8", errors="replace")
    atlas_links = {clean_wikilink(raw) for raw in WIKILINK_RE.findall(atlas_text)}

    for view_path in view_paths:
        if view_path.stem not in atlas_links:
            reporter.error(f"atlas must link view note: [[{view_path.stem}]]")

    for path in [atlas_path, *view_paths]:
        text = path.read_text(encoding="utf-8", errors="replace")
        fm, _body = parse_frontmatter(text)
        location_prefix = path.relative_to(atlas_path.parent).as_posix()
        if path == atlas_path:
            if fm.get("type") != "mental-map-atlas":
                reporter.error(f"{path.name}: type must be mental-map-atlas")
        else:
            if fm.get("type") != "mental-map-view":
                reporter.error(f"{location_prefix}: type must be mental-map-view")
            if fm.get("view") not in VALID_VIEW_TYPES:
                reporter.error(
                    f"{location_prefix}: invalid view type: {fm.get('view', '<missing>')}"
                )
            if fm.get("level") not in VALID_LEVELS:
                reporter.error(
                    f"{location_prefix}: invalid level: {fm.get('level', '<missing>')}"
                )
            title = markdown_title(text) or ""
            if not QUESTION_RE.search(title) or not title.endswith("?"):
                reporter.error(f"{location_prefix}: view H1 must ask a question")
            if not re.search(r"(?m)^Scope:\s+\S", text):
                reporter.error(f"{location_prefix}: view needs a Scope line")
            if not re.search(r"(?m)^Legend:\s+\S", text):
                reporter.error(f"{location_prefix}: view needs a Legend line")

        ordinary_links = {clean_wikilink(raw) for raw in WIKILINK_RE.findall(text)}
        diagrams = mermaid_blocks(text)
        if not diagrams:
            if path == atlas_path and atlas_uses_canvas:
                continue
            reporter.error(f"{location_prefix}: note contains no Mermaid diagram")
            continue
        for position, code in enumerate(diagrams, start=1):
            significant = [
                line.strip()
                for line in code.splitlines()
                if line.strip() and not line.strip().startswith("%%")
            ]
            if not significant:
                reporter.error(f"{location_prefix} diagram {position}: empty Mermaid block")
                continue
            first = significant[0]
            diagram_location = f"{location_prefix} diagram {position}"
            if first.startswith("flowchart "):
                direction = first.split(maxsplit=1)[1]
                if direction not in {"LR", "TB"}:
                    reporter.error(
                        f"{diagram_location}: flowchart direction must be LR or TB"
                    )
                facts = parse_flowchart(code, reporter, diagram_location)
                if max_nodes is not None and len(facts.nodes) > max_nodes:
                    reporter.error(
                        f"{diagram_location}: {len(facts.nodes)} nodes exceeds {max_nodes}"
                    )
                for node_id, label in facts.nodes.items():
                    if node_id not in facts.internal_link_ids:
                        reporter.error(
                            f"{diagram_location}: node lacks internal-link class: {label}"
                        )
                    block = blocks.get(label)
                    if block and block.frontmatter.get("status") == "planned":
                        if node_id not in facts.planned_ids:
                            reporter.error(
                                f"{diagram_location}: planned block lacks planned style: {label}"
                            )
            elif first == "sequenceDiagram":
                facts = parse_sequence(code, reporter, diagram_location)
                if max_nodes is not None and len(facts.nodes) > max_nodes:
                    reporter.error(
                        f"{diagram_location}: {len(facts.nodes)} participants exceeds {max_nodes}"
                    )
            elif first in {"stateDiagram-v2", "erDiagram"}:
                reporter.warn(
                    f"{diagram_location}: state/ER internals require semantic manual review"
                )
                continue
            else:
                reporter.error(f"{diagram_location}: unsupported Mermaid type: {first}")
                continue

            for label in facts.nodes.values():
                projected_nodes.add(label)
                if label not in blocks:
                    reporter.error(f"{diagram_location}: node has no block note: {label}")
                if label not in ordinary_links:
                    reporter.error(
                        f"{diagram_location}: node/participant lacks ordinary wikilink: [[{label}]]"
                    )
            for edge in facts.solid_edges:
                projected_implemented.add(edge)
                if edge not in implemented:
                    reporter.error(
                        f"{diagram_location}: solid edge lacks source-note [implemented] "
                        f"relationship: {edge[0]} -> {edge[1]} ({edge[2]})"
                    )
            for edge in facts.planned_edges:
                projected_planned.add(edge)
                if edge not in planned:
                    reporter.error(
                        f"{diagram_location}: dashed edge lacks source-note [planned] "
                        f"relationship: {edge[0]} -> {edge[1]} ({edge[2]})"
                    )

    for edge in sorted(implemented - projected_implemented):
        reporter.error(
            f"[implemented] relationship appears in no view: "
            f"{edge[0]} -> {edge[1]} ({edge[2]})"
        )
    for edge in sorted(planned - projected_planned):
        reporter.error(
            f"[planned] relationship appears in no view: "
            f"{edge[0]} -> {edge[1]} ({edge[2]})"
        )
    for block in blocks.values():
        if block.frontmatter.get("status") == "deprecated":
            continue
        if block.title not in projected_nodes:
            reporter.error(f"active block appears in no diagram: {block.title}")


def pattern_regex(pattern: str) -> re.Pattern[str]:
    pattern = normalize_repo_pattern(pattern)
    pieces: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
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
        elif char == "?":
            pieces.append("[^/]")
            index += 1
        else:
            pieces.append(re.escape(char))
            index += 1
    pieces.append("$")
    return re.compile("".join(pieces))


def matches(path: str, pattern: str) -> bool:
    normalized = normalize_repo_pattern(pattern)
    if not GLOB_META_RE.search(normalized):
        return path == normalized or path.startswith(normalized.rstrip("/") + "/")
    return bool(pattern_regex(normalized).match(path))


def normalize_repo_pattern(pattern: str) -> str:
    value = pattern.strip()
    return value[2:] if value.startswith("./") else value


def repo_files(repo: Path, reporter: Reporter) -> list[str]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        candidates = [value for value in result.stdout.decode(errors="replace").split("\0") if value]
        return sorted(
            value
            for value in candidates
            if (repo / PurePosixPath(value)).is_file()
            or (repo / PurePosixPath(value)).is_symlink()
        )
    except (OSError, subprocess.CalledProcessError):
        reporter.warn("git inventory unavailable; falling back to filesystem walk")
        files: list[str] = []
        for root, dirs, names in os.walk(repo):
            dirs[:] = [name for name in dirs if name not in EXCLUDED_REPO_DIRS]
            for name in names:
                path = Path(root) / name
                if path.is_file() or path.is_symlink():
                    files.append(path.relative_to(repo).as_posix())
        return sorted(files)


def split_exclusion(item: str) -> tuple[str, str]:
    value = clean_code_item(item)
    if " -> " not in value:
        return value, ""
    pattern, reason = value.split(" -> ", 1)
    return pattern.strip().strip("`"), reason.strip()


def validate_coverage(
    coverage_path: Path,
    blocks: dict[str, Block],
    repo: Path,
    reporter: Reporter,
) -> None:
    text = coverage_path.read_text(encoding="utf-8", errors="replace")
    validate_markdown_frontmatter_surface(coverage_path, text, reporter)
    fm, body = parse_frontmatter(text)
    if fm.get("type") != "mental-map-coverage":
        reporter.error(f"{coverage_path.name}: type must be mental-map-coverage")
    if not fm.get("revision"):
        reporter.error(f"{coverage_path.name}: revision is required")

    includes = [clean_code_item(item) for item in extract_list_after("Include:", body)]
    raw_excludes = [split_exclusion(item) for item in extract_list_after("Exclude:", body)]
    if not includes:
        reporter.error(f"{coverage_path.name}: Include must select maintained code")
    for pattern, reason in raw_excludes:
        if not reason:
            reporter.error(
                f"{coverage_path.name}: exclusion needs '-> reason': `{pattern}`"
            )

    inventory = repo_files(repo, reporter)
    included = {
        path
        for path in inventory
        if any(matches(path, pattern) for pattern in includes)
    }
    excluded = {
        path
        for path in inventory
        if any(matches(path, pattern) for pattern, _reason in raw_excludes)
    }
    selected = sorted(included - excluded)
    unclassified = sorted(set(inventory) - included - excluded)
    reporter.excluded_files = len(excluded)
    reporter.unresolved_files = len(unclassified)
    if not included:
        reporter.error("coverage Include patterns match no repository files")
    elif not selected:
        reporter.error(
            "coverage selects no maintained files after Exclude patterns win"
        )

    for pattern in includes:
        if not any(matches(path, pattern) for path in inventory):
            reporter.error(f"coverage Include pattern matches nothing: `{pattern}`")
    for pattern, _reason in raw_excludes:
        if not any(matches(path, pattern) for path in inventory):
            reporter.warn(f"coverage Exclude pattern matches nothing: `{pattern}`")

    if unclassified:
        preview = ", ".join(unclassified[:20])
        suffix = (
            f" (+{len(unclassified) - 20} more)"
            if len(unclassified) > 20
            else ""
        )
        reporter.error(
            "unclassified repository files (add Include or reasoned Exclude): "
            f"{preview}{suffix}"
        )

    owners: dict[str, list[str]] = defaultdict(list)
    responsibility_blocks = [
        block
        for block in blocks.values()
        if block.frontmatter.get("kind") == "responsibility"
        and block.frontmatter.get("status") == "implemented"
    ]
    for block in responsibility_blocks:
        for pattern in block.footprints:
            matched = [path for path in selected if matches(path, pattern)]
            if not matched:
                reporter.error(
                    f"{block.path.name}: Code footprint matches no in-scope file: `{pattern}`"
                )
            for path in matched:
                if block.title not in owners[path]:
                    owners[path].append(block.title)

    unowned = [path for path in selected if not owners[path]]
    overlaps = {path: names for path, names in owners.items() if len(names) > 1}
    reporter.mapped_files = len(selected) - len(unowned) - len(overlaps)
    reporter.unresolved_files = len(unclassified) + len(unowned) + len(overlaps)
    if unowned:
        preview = ", ".join(unowned[:20])
        suffix = f" (+{len(unowned) - 20} more)" if len(unowned) > 20 else ""
        reporter.error(f"unowned in-scope files: {preview}{suffix}")
    if overlaps:
        preview_items = [
            f"{path} ({', '.join(names)})" for path, names in sorted(overlaps.items())[:20]
        ]
        suffix = f" (+{len(overlaps) - 20} more)" if len(overlaps) > 20 else ""
        reporter.error(f"multiply-owned in-scope files: {'; '.join(preview_items)}{suffix}")


def derive_name(atlas: str, suffix: str) -> str:
    stem = Path(atlas).stem
    project = stem.removesuffix(" Atlas")
    return f"{project} {suffix}.md"


def resolve_validation_note(
    map_dir: Path,
    value: str,
    label: str,
    reporter: Reporter,
) -> Path | None:
    try:
        return validation_receipt.resolve_map_path(
            map_dir,
            value,
            default_name=None,
            label=label,
            allowed_suffixes={".md"},
        )
    except validation_receipt.ValidationReceiptError as error:
        reporter.error(str(error))
        return None


def validate(args: argparse.Namespace) -> Reporter:
    reporter = Reporter()
    repo = Path(args.repo).expanduser().resolve()
    map_dir = Path(args.map_dir).expanduser().resolve()

    if not repo.is_dir():
        reporter.error(f"repository does not exist: {repo}")
        return reporter
    if not map_dir.is_dir():
        reporter.error(f"project map directory does not exist: {map_dir}")
        return reporter
    try:
        map_dir.relative_to(repo)
        overlaps = True
    except ValueError:
        try:
            repo.relative_to(map_dir)
            overlaps = True
        except ValueError:
            overlaps = False
    if overlaps:
        reporter.error(
            "project map directory and repository must not overlap; move the "
            "map outside the repository"
        )
        return reporter

    atlas_path = resolve_validation_note(
        map_dir, args.atlas, "atlas note", reporter
    )
    index_path = resolve_validation_note(
        map_dir,
        args.index or derive_name(args.atlas, "Blocks Index"),
        "blocks index",
        reporter,
    )
    coverage_path = resolve_validation_note(
        map_dir,
        args.coverage or derive_name(args.atlas, "Code Coverage"),
        "coverage note",
        reporter,
    )
    if atlas_path is None or index_path is None or coverage_path is None:
        return reporter
    if not atlas_path.is_file():
        reporter.error(f"atlas note does not exist: {atlas_path}")
        return reporter

    atlas_text = atlas_path.read_text(encoding="utf-8", errors="replace")
    validate_markdown_frontmatter_surface(atlas_path, atlas_text, reporter)
    atlas_frontmatter, _atlas_body = parse_frontmatter(atlas_text)
    map_version = atlas_frontmatter.get("map-version")
    if map_version != "2" and not index_path.is_file():
        reporter.error(f"index note does not exist: {index_path}")
        return reporter

    typed_notes: list[tuple[Path, dict[str, str], str]] = []
    seen_notes: set[Path] = set()
    for discovered_path in sorted(map_dir.rglob("*.md")):
        path = discovered_path.resolve()
        try:
            path.relative_to(map_dir)
        except ValueError:
            reporter.error(
                "Markdown map artifact escapes project map directory through "
                f"a symlink: {discovered_path.relative_to(map_dir).as_posix()}"
            )
            continue
        if path in seen_notes:
            continue
        seen_notes.add(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        if path != atlas_path:
            validate_markdown_frontmatter_surface(path, text, reporter)
        frontmatter, _body = parse_frontmatter(text)
        typed_notes.append((path, frontmatter, text))

    atlas_links = {
        clean_wikilink(raw)
        for raw in WIKILINK_RE.findall(atlas_text)
    }
    if map_version != "2" and index_path.stem not in atlas_links:
        reporter.error(f"{atlas_path.name}: atlas must link index [[{index_path.stem}]]")
    if args.check_coverage and coverage_path.stem not in atlas_links:
        reporter.error(
            f"{atlas_path.name}: atlas must link coverage [[{coverage_path.stem}]]"
        )
    project = atlas_frontmatter.get("project")
    if not project:
        reporter.error(f"{atlas_path.name}: project is required")
    if atlas_frontmatter.get("mapping-mode") not in {"codebase-atlas", "change-map"}:
        reporter.error(
            f"{atlas_path.name}: mapping-mode must be codebase-atlas or change-map"
        )
    if not atlas_frontmatter.get("revision"):
        reporter.error(f"{atlas_path.name}: revision is required")
    revision_context = None
    if map_version == "2":
        revision_context = validate_v2_revision_contract(
            atlas_path,
            atlas_frontmatter,
            coverage_path,
            repo,
            reporter,
        )
        validate_mapped_target(atlas_path, atlas_text, repo, reporter)
    if project:
        for path, frontmatter, _text in typed_notes:
            note_type = frontmatter.get("type")
            if note_type not in {
                "mental-map-atlas",
                "mental-map-block",
                "mental-map-view",
                "mental-map-coverage",
            }:
                continue
            if frontmatter.get("project") != project:
                reporter.error(
                    f"{path.relative_to(map_dir).as_posix()}: project must be {project}"
                )

    block_paths = [path for path, fm, _text in typed_notes if fm.get("type") == "mental-map-block"]
    title_counts = Counter(path.stem for path in block_paths)
    for title, count in title_counts.items():
        if count > 1:
            reporter.error(f"duplicate block-note title inside project map: {title}")
    blocks = {path.stem: parse_block(path, reporter) for path in block_paths}
    if not blocks:
        reporter.error("project map contains no mental-map-block notes")

    validate_blocks(
        blocks,
        None
        if map_version == "2"
        else index_path.read_text(encoding="utf-8", errors="replace"),
        repo,
        reporter,
        map_version=map_version,
        revision_context=revision_context,
    )
    atlas_uses_canvas, canvas_facts = validate_native_views(
        atlas_path,
        atlas_frontmatter,
        map_dir,
        getattr(args, "vault", None),
        blocks,
        project or "",
        reporter,
    )
    if map_version == "2":
        validate_entry_point_inventory(
            atlas_path,
            map_dir,
            repo,
            getattr(args, "vault", None),
            reporter,
        )
    view_paths = [path for path, fm, _text in typed_notes if fm.get("type") == "mental-map-view"]
    validate_views(
        atlas_path,
        view_paths,
        blocks,
        args.max_nodes,
        reporter,
        canvas_facts=canvas_facts,
        atlas_uses_canvas=atlas_uses_canvas,
    )

    if args.check_coverage:
        if not coverage_path.is_file():
            reporter.error(f"coverage note does not exist: {coverage_path}")
        else:
            validate_coverage(coverage_path, blocks, repo, reporter)
    elif coverage_path.is_file():
        reporter.warn("coverage note exists but --check-coverage was omitted")
    else:
        reporter.warn("whole-codebase coverage check skipped")
    return reporter


def capture_sync_status(args: argparse.Namespace) -> dict[str, object]:
    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "sync_map_state.py"),
        "status",
        "--repo",
        args.repo,
        "--map-dir",
        args.map_dir,
    ]
    if args.coverage:
        command.extend(["--coverage", args.coverage])
    if args.state:
        command.extend(["--state", args.state])
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        message = result.stdout.strip() or result.stderr.strip()
        raise validation_receipt.ValidationReceiptError(
            f"cannot capture validation target: {message or 'sync status failed'}"
        )
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise validation_receipt.ValidationReceiptError(
            "sync status returned invalid JSON"
        ) from error
    if not isinstance(status, dict):
        raise validation_receipt.ValidationReceiptError(
            "sync status returned a non-object result"
        )
    if status.get("schema") != SYNC_STATE_SCHEMA_VERSION:
        raise validation_receipt.ValidationReceiptError(
            f"sync status must use schema v{SYNC_STATE_SCHEMA_VERSION}"
        )
    return status


def resolve_validation_control_paths(
    args: argparse.Namespace, map_dir: Path
) -> tuple[Path, Path]:
    state_path = validation_receipt.resolve_sidecar_path(
        map_dir,
        args.state,
        default_name=validation_receipt.DEFAULT_SYNC_STATE_NAME,
        label="sync state",
        forbidden_paths=(map_dir / validation_receipt.DEFAULT_RECEIPT_NAME,),
    )
    receipt_path = validation_receipt.resolve_sidecar_path(
        map_dir,
        args.receipt,
        default_name=validation_receipt.DEFAULT_RECEIPT_NAME,
        label="validation receipt",
        forbidden_paths=(state_path,),
    )
    return state_path, receipt_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="repository root")
    parser.add_argument(
        "--vault",
        help="Obsidian vault root containing .obsidian; required for map-version 2",
    )
    parser.add_argument("--map-dir", required=True, help="project map directory in the vault")
    parser.add_argument("--atlas", required=True, help="atlas filename relative to map-dir")
    parser.add_argument(
        "--index",
        help="legacy blocks index filename; derived from atlas when required",
    )
    parser.add_argument("--coverage", help="coverage filename; derived from atlas by default")
    parser.add_argument(
        "--state",
        help="sync-state path passed to target capture; defaults inside map-dir",
    )
    parser.add_argument(
        "--check-coverage",
        action="store_true",
        help="require exhaustive one-owner coverage for selected repository files",
    )
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=None,
        help="optional positive per-Mermaid node/participant limit",
    )
    parser.add_argument(
        "--write-receipt",
        action="store_true",
        help="write an exact validation receipt after all checks pass",
    )
    parser.add_argument(
        "--receipt",
        help=(
            "validation receipt path; defaults to "
            f"<map-dir>/{validation_receipt.DEFAULT_RECEIPT_NAME}"
        ),
    )
    args = parser.parse_args()

    if args.max_nodes is not None and args.max_nodes < 1:
        parser.error("--max-nodes must be a positive integer when supplied")

    if args.write_receipt and not args.check_coverage:
        parser.error("--write-receipt requires --check-coverage")

    before_status: dict[str, object] | None = None
    before_map_digest: str | None = None
    state_path: Path | None = None
    receipt_destination: Path | None = None
    if args.write_receipt:
        try:
            map_dir = Path(args.map_dir).expanduser().resolve()
            state_path, receipt_destination = resolve_validation_control_paths(
                args, map_dir
            )
            before_status = capture_sync_status(args)
            before_map_digest = validation_receipt.map_digest(
                map_dir
            )
        except validation_receipt.ValidationReceiptError as error:
            print(f"Errors:\n- {error}")
            return 2

    reporter = validate(args)
    if reporter.warnings:
        print("Warnings:")
        for warning in reporter.warnings:
            print(f"- {warning}")
    if reporter.errors:
        print("Errors:")
        for error in reporter.errors:
            print(f"- {error}")
        if args.check_coverage:
            print(
                "Coverage: "
                f"mapped={reporter.mapped_files} "
                f"excluded={reporter.excluded_files} "
                f"unresolved={reporter.unresolved_files}"
            )
        return 1
    receipt_path: Path | None = None
    if args.write_receipt:
        map_dir = Path(args.map_dir).expanduser().resolve()
        try:
            after_status = capture_sync_status(args)
            after_map_digest = validation_receipt.map_digest(map_dir)
            if (
                before_status is None
                or before_status.get("targetFingerprint")
                != after_status.get("targetFingerprint")
            ):
                raise validation_receipt.ValidationReceiptError(
                    "repository target changed during validation"
                )
            if before_map_digest != after_map_digest:
                raise validation_receipt.ValidationReceiptError(
                    "mental-map artifacts changed during validation"
                )
            before_context = validation_receipt.status_context_from_report(
                before_status
            )
            after_context = validation_receipt.status_context_from_report(
                after_status
            )
            if before_context != after_context:
                raise validation_receipt.ValidationReceiptError(
                    "sync baseline or trust context changed during validation"
                )
            target = after_status.get("target")
            changed = after_status.get("changedPaths")
            if not isinstance(target, dict) or not isinstance(changed, dict):
                raise validation_receipt.ValidationReceiptError(
                    "sync status omitted target validation fields"
                )
            coverage = target.get("coverage")
            changed_all = changed.get("all")
            if not isinstance(coverage, dict) or not isinstance(changed_all, list):
                raise validation_receipt.ValidationReceiptError(
                    "sync status omitted coverage or changed paths"
                )
            receipt_path = validation_receipt.write_receipt(
                map_dir,
                Path(__file__).resolve().parent,
                target_fingerprint=str(after_status["targetFingerprint"]),
                coverage_contract_sha256=str(coverage["contractSha256"]),
                changed_paths=[str(path) for path in changed_all],
                status_context=after_context,
                receipt_path=receipt_destination,
                forbidden_paths=(state_path,) if state_path is not None else (),
            )
        except (KeyError, validation_receipt.ValidationReceiptError) as error:
            print(f"Errors:\n- validation passed but receipt was not written: {error}")
            return 2
    if args.check_coverage:
        print(
            "Coverage: "
            f"mapped={reporter.mapped_files} "
            f"excluded={reporter.excluded_files} unresolved=0"
        )
    print("Mental map validation passed.")
    if receipt_path is not None:
        print(f"Validation receipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
