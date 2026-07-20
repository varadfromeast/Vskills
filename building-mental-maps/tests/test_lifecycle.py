#!/usr/bin/env python3
"""End-to-end bootstrap and non-breaking commit synchronization."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
VALIDATOR = SKILL_DIR / "scripts" / "validate_mental_map.py"
SYNC = SKILL_DIR / "scripts" / "sync_map_state.py"


class MentalMapLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.vault = self.root / "vault"
        self.map_dir = self.vault / "Engineering/Architecture/Parcel Map"
        self.repo.mkdir()
        self.map_dir.mkdir(parents=True)
        (self.vault / ".obsidian").mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test User")
        self.write_repo("src/intake.py", "def submit(parcel):\n    return parcel\n")
        self.write_repo("src/store.py", "def save(parcel):\n    return parcel['id']\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "initial parcel flow")
        self.initial_head = self.git("rev-parse", "HEAD")
        self.write_initial_map(self.initial_head)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        ).stdout.strip()

    @staticmethod
    def write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def write_repo(self, relative: str, text: str) -> None:
        self.write(self.repo / relative, text)

    @property
    def canvas_path(self) -> Path:
        return self.map_dir / "Parcel Atlas.canvas"

    @property
    def relationships_canvas_path(self) -> Path:
        return self.map_dir / "Views/Parcel All Relationships.canvas"

    @property
    def coverage_path(self) -> Path:
        return self.map_dir / "Parcel Code Coverage.md"

    def vault_path(self, relative: str) -> str:
        return f"Engineering/Architecture/Parcel Map/{relative}"

    def write_coverage(self, revision: str) -> None:
        self.write(
            self.coverage_path,
            f"""---
type: mental-map-coverage
project: Parcel
revision: {revision}
---

# Parcel Code Coverage

Include:
- `src/**`

Exclude:
""",
        )

    def block(
        self,
        name: str,
        atlas_id: str,
        revision: str,
        footprint: str,
        anchor: str,
        purpose: str,
        hides: str,
        provides: str,
        requires: str,
        connects: str,
    ) -> str:
        return f"""---
type: mental-map-block
project: Parcel
atlas-id: {atlas_id}
kind: responsibility
level: responsibility
status: implemented
confidence: traced
reviewed-revision: {revision}
---

# {name}

Purpose: {purpose}

Hides: {hides}

Code footprint:
- `{footprint}`

Concrete anchors:
- `{anchor}`

Provides:
- {provides}

Requires:
{requires}

State and invariants:
- Invariant: Parcel identity is stable across the journey.

Runtime behavior:
- Success: Returns a domain-level result.
- Failure: Rejects malformed or unavailable work without corrupting stored state.

Deployment: Runs in the Parcel API process.

Quality and risks:
- Priority: Preserve traceable parcel state.

Connects:
{connects}

Evidence:
- `mapped at {revision}`
"""

    def write_atlas(self, revision: str, *, changed: bool) -> None:
        mode = "change-map" if changed else "codebase-atlas"
        mapped_target = (
            "HEAD + dirty paths"
            if self.git("status", "--porcelain=v1", "--untracked-files=all")
            else "HEAD"
        )
        status_link = (
            " · [[How Does Parcel Status Reach Storage]]" if changed else ""
        )
        status_inventory_row = (
            "\n| Parcel status query | `src/status.py :: status` | "
            "[[Engineering/Architecture/Parcel Map/Flows/How Does Parcel Status Reach Storage.md]] | |"
            if changed
            else ""
        )
        canvas_members = (
            "[[Parcel Intake]] · [[Parcel Store]] · [[Parcel Status Query]]"
            if changed
            else "[[Parcel Intake]] · [[Parcel Store]]"
        )
        self.write(
            self.map_dir / "Parcel Atlas.md",
            f"""---
type: mental-map-atlas
map-version: 2
project: Parcel
mapping-mode: {mode}
revision: {revision}
canvas: Parcel Atlas.canvas
relationships-canvas: Views/Parcel All Relationships.canvas
base: Parcel Blocks.base
sync-state: .mental-map-state.json
---

# Parcel Atlas

Purpose: Accept parcels and expose their durable processing state.

Domain boundary: Parcel intake and status are internal; callers are external.

Quality priorities: Preserve accepted work and explain every state transition.

Current risks: Storage availability can temporarily delay answers.

Coverage summary: All maintained Parcel source files are included.

Mapped target: {mapped_target}

Unresolved questions: None.

Start here: [[Parcel Atlas.canvas]] · [[Views/Parcel All Relationships.canvas]] · [[Parcel Blocks.base]] ·
[[Parcel Code Coverage]] · [[How Does Parcel Submission Finish]]{status_link}

## Entry-point families

| Family | Representative anchor | Focused view | No-view reason |
| --- | --- | --- | --- |
| Parcel submission | `src/intake.py :: submit` | [[Engineering/Architecture/Parcel Map/Flows/How Does Parcel Submission Finish.md]] | |{status_inventory_row}

## Canvas semantic groups

| Group | Scope key | Question | Members |
| --- | --- | --- | --- |
| Parcel lifecycle | parcel-lifecycle | How does parcel work reach durable state? | {canvas_members} |

## Needs review

![[Parcel Blocks.base#Needs review]]
""",
        )

    def write_base(self) -> None:
        self.write(
            self.map_dir / "Parcel Blocks.base",
            """filters:
  and:
    - 'type == "mental-map-block"'
    - 'project == "Parcel"'
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
""",
        )

    def write_submission_flow(self) -> None:
        self.write(
            self.map_dir / "Flows/How Does Parcel Submission Finish.md",
            """---
type: mental-map-view
project: Parcel
view: journey
level: responsibility
entry-point-family: Parcel submission
---

# How Does Parcel Submission Finish?

Scope: One accepted parcel reaches durable storage.

Legend: Solid messages are implemented calls.

```mermaid
sequenceDiagram
  participant Intake as Parcel Intake
  participant Store as Parcel Store
  Intake->>Store: persists accepted parcels in
```

Blocks: [[Parcel Intake]] · [[Parcel Store]]
""",
        )

    def write_status_flow(self) -> None:
        self.write(
            self.map_dir / "Flows/How Does Parcel Status Reach Storage.md",
            """---
type: mental-map-view
project: Parcel
view: journey
level: responsibility
entry-point-family: Parcel status query
---

# How Does Parcel Status Reach Storage?

Scope: One status request reads the durable parcel state.

Legend: Solid messages are implemented calls.

```mermaid
sequenceDiagram
  participant Status as Parcel Status Query
  participant Store as Parcel Store
  Status->>Store: requests stored status from
```

Blocks: [[Parcel Status Query]] · [[Parcel Store]]
""",
        )

    def initial_canvas(self) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "id": "mental-map:group:parcel-lifecycle",
                    "type": "group",
                    "label": "Parcel lifecycle",
                    "x": -100,
                    "y": -100,
                    "width": 1480,
                    "height": 420,
                },
                {
                    "id": "manual:orientation",
                    "type": "text",
                    "text": "Read left to right.",
                    "x": -420,
                    "y": -220,
                    "width": 280,
                    "height": 100,
                    "color": "6",
                },
                {
                    "id": "mental-map:block:parcel.intake",
                    "type": "file",
                    "file": self.vault_path("Blocks/Parcel Intake.md"),
                    "subpath": "#Parcel Intake",
                    "x": 0,
                    "y": 0,
                    "width": 320,
                    "height": 220,
                    "color": "4",
                },
                {
                    "id": "mental-map:block:parcel.store",
                    "type": "file",
                    "file": self.vault_path("Blocks/Parcel Store.md"),
                    "subpath": "#Parcel Store",
                    "x": 480,
                    "y": 0,
                    "width": 320,
                    "height": 220,
                    "color": "5",
                },
            ],
            "edges": [
                {
                    "id": "manual:reading-order",
                    "fromNode": "manual:orientation",
                    "toNode": "mental-map:block:parcel.intake",
                },
                {
                    "id": "mental-map:edge:intake-store",
                    "fromNode": "mental-map:block:parcel.intake",
                    "toNode": "mental-map:block:parcel.store",
                    "label": "persists accepted parcels in",
                },
            ],
        }

    def write_initial_map(self, revision: str) -> None:
        self.write_coverage(revision)
        self.write_atlas(revision, changed=False)
        self.write_base()
        self.write_submission_flow()
        self.write(
            self.map_dir / "Blocks/Parcel Intake.md",
            self.block(
                "Parcel Intake",
                "parcel.intake",
                revision,
                "src/intake.py",
                "src/intake.py :: submit",
                "Accept parcels for processing.",
                "Validation and request-shaping details.",
                "`submit parcel` -> returns the accepted parcel",
                "- [[Parcel Store]] :: `save parcel` -> persists before completion",
                "- [implemented] [[Parcel Store]] -> persists accepted parcels in",
            ),
        )
        self.write(
            self.map_dir / "Blocks/Parcel Store.md",
            self.block(
                "Parcel Store",
                "parcel.store",
                revision,
                "src/store.py",
                "src/store.py :: save",
                "Persist accepted parcel state.",
                "Storage and durability details.",
                "`save parcel` -> returns the durable parcel id",
                "",
                "",
            ),
        )
        initial_canvas = json.dumps(self.initial_canvas(), indent=2)
        self.write(self.canvas_path, initial_canvas)
        self.write(self.relationships_canvas_path, initial_canvas)

    def run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def validate_and_receipt(self) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            [
                sys.executable,
                str(VALIDATOR),
                "--repo",
                str(self.repo),
                "--vault",
                str(self.vault),
                "--map-dir",
                str(self.map_dir),
                "--atlas",
                "Parcel Atlas.md",
                "--coverage",
                self.coverage_path.name,
                "--check-coverage",
                "--write-receipt",
            ]
        )

    def status(self) -> dict[str, object]:
        result = self.run_command(
            [
                sys.executable,
                str(SYNC),
                "status",
                "--repo",
                str(self.repo),
                "--map-dir",
                str(self.map_dir),
                "--coverage",
                self.coverage_path.name,
            ]
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def checkpoint(self, fingerprint: str) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            [
                sys.executable,
                str(SYNC),
                "checkpoint",
                "--repo",
                str(self.repo),
                "--map-dir",
                str(self.map_dir),
                "--coverage",
                self.coverage_path.name,
                "--require-fingerprint",
                fingerprint,
            ]
        )

    def test_control_sidecars_cannot_overwrite_map_artifacts(self) -> None:
        atlas_path = self.map_dir / "Parcel Atlas.md"
        atlas_before = atlas_path.read_bytes()
        receipt_collision = self.run_command(
            [
                sys.executable,
                str(VALIDATOR),
                "--repo",
                str(self.repo),
                "--vault",
                str(self.vault),
                "--map-dir",
                str(self.map_dir),
                "--atlas",
                atlas_path.name,
                "--coverage",
                self.coverage_path.name,
                "--check-coverage",
                "--write-receipt",
                "--receipt",
                atlas_path.name,
            ]
        )
        self.assertEqual(2, receipt_collision.returncode)
        self.assertIn("must use one of these suffixes", receipt_collision.stdout)
        self.assertEqual(atlas_before, atlas_path.read_bytes())

        coverage_before = self.coverage_path.read_bytes()
        state_collision = self.run_command(
            [
                sys.executable,
                str(SYNC),
                "status",
                "--repo",
                str(self.repo),
                "--map-dir",
                str(self.map_dir),
                "--coverage",
                self.coverage_path.name,
                "--state",
                self.coverage_path.name,
            ]
        )
        self.assertEqual(2, state_collision.returncode)
        self.assertIn("must use one of these suffixes", state_collision.stdout)
        self.assertEqual(coverage_before, self.coverage_path.read_bytes())

        custom_control = self.map_dir / "custom-control.json"
        custom_control.write_text('{"sentinel": true}\n', encoding="utf-8")
        custom_before = custom_control.read_bytes()
        custom_collision = self.run_command(
            [
                sys.executable,
                str(VALIDATOR),
                "--repo",
                str(self.repo),
                "--vault",
                str(self.vault),
                "--map-dir",
                str(self.map_dir),
                "--atlas",
                atlas_path.name,
                "--coverage",
                self.coverage_path.name,
                "--check-coverage",
                "--write-receipt",
                "--state",
                custom_control.name,
                "--receipt",
                custom_control.name,
            ]
        )
        self.assertEqual(2, custom_collision.returncode)
        self.assertIn("collides", custom_collision.stdout)
        self.assertEqual(custom_before, custom_control.read_bytes())

    def test_new_commit_updates_blocks_flows_and_canvas_without_breakage(self) -> None:
        initial_validation = self.validate_and_receipt()
        self.assertEqual(
            0,
            initial_validation.returncode,
            initial_validation.stdout + initial_validation.stderr,
        )
        initial_status = self.status()
        initial_checkpoint = self.checkpoint(str(initial_status["targetFingerprint"]))
        self.assertEqual(
            0,
            initial_checkpoint.returncode,
            initial_checkpoint.stdout + initial_checkpoint.stderr,
        )
        initial_state = (self.map_dir / ".mental-map-state.json").read_bytes()
        original_canvas = json.loads(self.canvas_path.read_text(encoding="utf-8"))
        original_nodes = {node["id"]: node for node in original_canvas["nodes"]}
        original_edges = {edge["id"]: edge for edge in original_canvas["edges"]}

        self.write_repo(
            "src/store.py",
            "def save(parcel):\n    return parcel['id']\n\ndef lookup(parcel_id):\n    return parcel_id\n",
        )
        self.write_repo(
            "src/status.py",
            "from .store import lookup\n\ndef status(parcel_id):\n    return lookup(parcel_id)\n",
        )
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "add parcel status query")
        current_head = self.git("rev-parse", "HEAD")
        changed = self.status()
        self.assertEqual(["src/status.py"], changed["changedPaths"]["added"])
        self.assertEqual(["src/store.py"], changed["changedPaths"]["modified"])

        rejected = self.checkpoint(str(changed["targetFingerprint"]))
        self.assertEqual(2, rejected.returncode)
        self.assertIn("validation receipt is stale", rejected.stdout)
        self.assertEqual(
            initial_state, (self.map_dir / ".mental-map-state.json").read_bytes()
        )

        self.write_coverage(current_head)
        self.write_atlas(current_head, changed=True)
        self.write_status_flow()
        self.write(
            self.map_dir / "Blocks/Parcel Store.md",
            self.block(
                "Parcel Store",
                "parcel.store",
                current_head,
                "src/store.py",
                "src/store.py :: lookup",
                "Persist and retrieve accepted parcel state.",
                "Storage, lookup, and durability details.",
                "`save or lookup parcel` -> returns durable state",
                "",
                "",
            ),
        )
        self.write(
            self.map_dir / "Blocks/Parcel Status Query.md",
            self.block(
                "Parcel Status Query",
                "parcel.status-query",
                current_head,
                "src/status.py",
                "src/status.py :: status",
                "Answer parcel status requests.",
                "Lookup orchestration and response-shaping details.",
                "`query status` -> returns the current parcel state",
                "- [[Parcel Store]] :: `lookup parcel` -> returns durable state",
                "- [implemented] [[Parcel Store]] -> requests stored status from",
            ),
        )
        updated_canvas = json.loads(self.canvas_path.read_text(encoding="utf-8"))
        updated_canvas["nodes"].append(
            {
                "id": "mental-map:block:parcel.status-query",
                "type": "file",
                "file": self.vault_path("Blocks/Parcel Status Query.md"),
                "subpath": "#Parcel Status Query",
                "x": 960,
                "y": 0,
                "width": 320,
                "height": 220,
                "color": "3",
            }
        )
        updated_canvas["edges"].append(
            {
                "id": "mental-map:edge:status-store",
                "fromNode": "mental-map:block:parcel.status-query",
                "toNode": "mental-map:block:parcel.store",
                "label": "requests stored status from",
            }
        )
        self.write(self.canvas_path, json.dumps(updated_canvas, indent=2))
        self.write(
            self.relationships_canvas_path,
            json.dumps(updated_canvas, indent=2),
        )

        current_validation = self.validate_and_receipt()
        self.assertEqual(
            0,
            current_validation.returncode,
            current_validation.stdout + current_validation.stderr,
        )
        final_canvas = json.loads(self.canvas_path.read_text(encoding="utf-8"))
        final_nodes = {node["id"]: node for node in final_canvas["nodes"]}
        final_edges = {edge["id"]: edge for edge in final_canvas["edges"]}
        for stable_id in (
            "manual:orientation",
            "mental-map:block:parcel.intake",
            "mental-map:block:parcel.store",
        ):
            self.assertEqual(original_nodes[stable_id], final_nodes[stable_id])
        for stable_id in ("manual:reading-order", "mental-map:edge:intake-store"):
            self.assertEqual(original_edges[stable_id], final_edges[stable_id])
        self.assertEqual(
            self.vault_path("Blocks/Parcel Status Query.md"),
            final_nodes["mental-map:block:parcel.status-query"]["file"],
        )
        for node in final_canvas["nodes"]:
            if str(node["id"]).startswith("mental-map:block:"):
                self.assertTrue((self.vault / node["file"]).is_file())

        final_status = self.status()
        final_checkpoint = self.checkpoint(str(final_status["targetFingerprint"]))
        self.assertEqual(
            0,
            final_checkpoint.returncode,
            final_checkpoint.stdout + final_checkpoint.stderr,
        )
        after = self.status()
        self.assertEqual([], after["changedPaths"]["all"])
        state = json.loads(
            (self.map_dir / ".mental-map-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(current_head, state["head"])


if __name__ == "__main__":
    unittest.main()
