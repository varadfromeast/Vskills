from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


VALIDATOR_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "validate_mental_map.py"
)
SCRIPT_DIR = VALIDATOR_PATH.parent
sys.path.insert(0, str(SCRIPT_DIR))
SPEC = importlib.util.spec_from_file_location("validate_mental_map", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


class MentalMapValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.vault = self.root / "vault"
        self.map_dir = self.vault / "Project Map"
        self.repo.mkdir()
        self.map_dir.mkdir(parents=True)
        (self.vault / ".obsidian").mkdir()
        self._write(self.repo / "src/a.py", "def alpha():\n    return 'a'\n")
        self._write(self.repo / "src/b.py", "def beta():\n    return 'b'\n")
        self.git("init", "--quiet")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test User")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "initial")
        self.head = self.git("rev-parse", "HEAD")
        self._write_blocks()
        self._write_coverage()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def _write_coverage(self, revision: str | None = None) -> None:
        self._write(
            self.map_dir / "Demo Code Coverage.md",
            f"""---
type: mental-map-coverage
project: Demo
revision: {revision or self.head}
---

# Demo Code Coverage

Include:
- `src/**`

Exclude:
""",
        )

    def _write_blocks(self) -> None:
        self._write(
            self.map_dir / "Blocks/A.md",
            f"""---
type: mental-map-block
project: Demo
atlas-id: demo.a
kind: responsibility
level: responsibility
status: implemented
confidence: traced
reviewed-revision: {self.head}
---

# A

Purpose: Accept work.

Hides: Input details.

Code footprint:
- `src/a.py`

Concrete anchors:
- `src/a.py :: alpha`

Connects:
- [implemented] [[B]] -> sends work to

Evidence:
- `mapped at {self.head}`
""",
        )
        self._write(
            self.map_dir / "Blocks/B.md",
            f"""---
type: mental-map-block
project: Demo
atlas-id: demo.b
kind: responsibility
level: responsibility
status: implemented
confidence: traced
reviewed-revision: {self.head}
---

# B

Purpose: Finish work.

Hides: Output details.

Code footprint:
- `src/b.py`

Concrete anchors:
- `src/b.py :: beta`

Connects:

Evidence:
- `mapped at {self.head}`
""",
        )

    def _args(self, include_vault: bool = True) -> SimpleNamespace:
        return SimpleNamespace(
            repo=str(self.repo),
            vault=str(self.vault) if include_vault else None,
            map_dir=str(self.map_dir),
            atlas="Demo Atlas.md",
            index=None,
            coverage="Demo Code Coverage.md",
            check_coverage=False,
            max_nodes=12,
        )

    def _write_legacy_atlas(self) -> None:
        self._write(
            self.map_dir / "Demo Blocks Index.md",
            "# Demo Blocks Index\n\n- [[A]]\n- [[B]]\n",
        )
        self._write(
            self.map_dir / "Demo Atlas.md",
            """---
type: mental-map-atlas
project: Demo
mapping-mode: codebase-atlas
revision: abc1234
---

# Demo Atlas

[[Demo Blocks Index]]

```mermaid
flowchart LR
  A["A"]
  B["B"]
  A -->|sends work to| B
  class A,B internal-link
```

Blocks: [[A]] · [[B]]
""",
        )

    def _valid_canvas(self) -> dict[str, object]:
        return {
            "nodes": [
                {
                    "id": "mental-map:group:demo-work",
                    "type": "group",
                    "label": "Demo work",
                    "x": -100,
                    "y": -100,
                    "width": 900,
                    "height": 400,
                },
                {
                    "id": "mental-map:block:demo.a",
                    "type": "file",
                    "file": "Project Map/Blocks/A.md",
                    "subpath": "#A",
                    "x": 0,
                    "y": 0,
                    "width": 300,
                    "height": 200,
                },
                {
                    "id": "mental-map:block:demo.b",
                    "type": "file",
                    "file": "Project Map/Blocks/B.md",
                    "subpath": "#B",
                    "x": 400,
                    "y": 0,
                    "width": 300,
                    "height": 200,
                },
            ],
            "edges": [
                {
                    "id": "mental-map:edge:demo.a-to-demo.b",
                    "fromNode": "mental-map:block:demo.a",
                    "toNode": "mental-map:block:demo.b",
                    "label": "sends work to",
                }
            ],
        }

    def _two_group_canvas(self) -> dict[str, object]:
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        assert isinstance(nodes, list)
        first_group = nodes[0]
        first_group.update(
            {
                "id": "mental-map:group:intake",
                "label": "Intake",
                "x": -50,
                "y": -50,
                "width": 400,
                "height": 300,
            }
        )
        second_group = {
            "id": "mental-map:group:completion",
            "type": "group",
            "label": "Completion",
            "x": 350,
            "y": -50,
            "width": 400,
            "height": 300,
        }
        canvas["nodes"] = [first_group, second_group, *nodes[1:]]
        return canvas

    def _declare_two_canvas_groups(self) -> None:
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "| Demo work | demo-work | How does accepted demo work reach completion? | [[A]] · [[B]] |",
                "| Intake | intake | What accepts demo work? | [[A]] |\n"
                "| Completion | completion | What completes demo work? | [[B]] |",
            ),
        )
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(self._two_group_canvas()),
        )

    @staticmethod
    def _valid_base() -> str:
        return """filters:
  and:
    - 'type == "mental-map-block"'
    - 'project == "Demo"'
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

    def _write_v2_atlas(
        self,
        *,
        canvas: dict[str, object] | None = None,
        base: str | None = None,
        frontmatter: str = (
            "canvas: Demo Atlas.canvas\n"
            "relationships-canvas: Views/Demo All Relationships.canvas\n"
            "base: Demo Blocks.base\n"
            "sync-state: .mental-map-state.json\n"
        ),
        extra_body: str = "",
    ) -> None:
        mapped_target = (
            "HEAD + dirty paths"
            if self.git("status", "--porcelain=v1", "--untracked-files=all")
            else "HEAD"
        )
        self._write(
            self.map_dir / "Demo Atlas.md",
            f"""---
type: mental-map-atlas
project: Demo
mapping-mode: codebase-atlas
revision: {self.head}
map-version: 2
{frontmatter}---

# Demo Atlas

Purpose: Demonstrate the atlas contract.

Domain boundary: Accept and finish demo work; external concerns stay outside.

Quality priorities: Keep accepted work understandable and traceable.

Current risks: None known in this fixture.

Coverage summary: All maintained demo sources are included.

Mapped target: {mapped_target}

Unresolved questions: None.

Start here: [[Demo Atlas.canvas]] · [[Views/Demo All Relationships.canvas]] · [[Demo Blocks.base]] · [[Demo Code Coverage]]

## Entry-point families

| Family | Representative anchor | Focused view | No-view reason |
| --- | --- | --- | --- |
| Alpha library helper | `src/a.py :: alpha` | | Pure synchronous value lookup has no architectural ordering, handoff, or recovery. |

## Canvas semantic groups

| Group | Scope key | Question | Members |
| --- | --- | --- | --- |
| Demo work | demo-work | How does accepted demo work reach completion? | [[A]] · [[B]] |

## Needs review

![[Demo Blocks.base#Needs review]]
{extra_body}
""",
        )
        if canvas is not None:
            self._write(
                self.map_dir / "Demo Atlas.canvas", json.dumps(canvas)
            )
            relationships_canvas = (
                self.map_dir / "Views/Demo All Relationships.canvas"
            )
            if not relationships_canvas.exists():
                self._write(relationships_canvas, json.dumps(canvas))
        if base is not None:
            self._write(self.map_dir / "Demo Blocks.base", base)

    def _write_entry_point_view(
        self,
        *,
        family: str = "Demo work submission",
        filename: str = "How Does Demo Work Finish.md",
        view_type: str = "journey",
        declared_family: str | None = None,
    ) -> None:
        self._write(
            self.map_dir / "Flows" / filename,
            f"""---
type: mental-map-view
project: Demo
view: {view_type}
level: responsibility
entry-point-family: {declared_family or family}
---

# How Does Demo Work Finish?

Scope: One accepted demo submission through completion.

Legend: Solid arrows are implemented relationships.

```mermaid
flowchart LR
  A["A"]
  B["B"]
  A -->|sends work to| B
  class A,B internal-link
```

Blocks: [[A]] · [[B]]
""",
        )

    def _errors(self, include_vault: bool = True) -> list[str]:
        return validator.validate(self._args(include_vault)).errors

    def _run_validator_cli(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR_PATH),
                "--repo",
                str(self.repo),
                "--vault",
                str(self.vault),
                "--map-dir",
                str(self.map_dir),
                "--atlas",
                "Demo Atlas.md",
                "--coverage",
                "Demo Code Coverage.md",
                *extra,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def _run_main_with_validation_side_effect(self, side_effect: object) -> tuple[int, str]:
        arguments = [
            str(VALIDATOR_PATH),
            "--repo",
            str(self.repo),
            "--vault",
            str(self.vault),
            "--map-dir",
            str(self.map_dir),
            "--atlas",
            "Demo Atlas.md",
            "--coverage",
            "Demo Code Coverage.md",
            "--check-coverage",
            "--write-receipt",
        ]
        output = io.StringIO()
        with (
            mock.patch.object(sys, "argv", arguments),
            mock.patch.object(validator, "validate", side_effect=side_effect),
            contextlib.redirect_stdout(output),
        ):
            result = validator.main()
        return result, output.getvalue()

    def test_legacy_mermaid_map_still_passes_without_vault(self) -> None:
        self._write_legacy_atlas()
        self.assertEqual([], self._errors(include_vault=False))

    def test_legacy_map_still_requires_index(self) -> None:
        self._write_legacy_atlas()
        (self.map_dir / "Demo Blocks Index.md").unlink()
        self.assertTrue(any("index note does not exist" in item for item in self._errors()))

    def test_valid_v2_canvas_and_base_replace_atlas_mermaid(self) -> None:
        self._write_v2_atlas(
            canvas=self._valid_canvas(), base=self._valid_base()
        )
        self.assertEqual([], self._errors())

    def test_v2_requires_all_relationships_canvas(self) -> None:
        self._write_v2_atlas(
            canvas=self._valid_canvas(),
            base=self._valid_base(),
            frontmatter=(
                "canvas: Demo Atlas.canvas\n"
                "base: Demo Blocks.base\n"
                "sync-state: .mental-map-state.json\n"
            ),
        )

        self.assertTrue(
            any(
                "requires relationships-canvas frontmatter" in item
                for item in self._errors()
            )
        )

    def test_entry_point_inventory_accepts_one_bound_focused_view(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "| Alpha library helper | `src/a.py :: alpha` | | Pure synchronous value lookup has no architectural ordering, handoff, or recovery. |",
                "| Demo work submission | `src/a.py :: alpha` | [[Project Map/Flows/How Does Demo Work Finish.md]] | |",
            ),
        )
        self._write_entry_point_view(view_type="contract")

        self.assertEqual([], self._errors())

    def test_v2_requires_nonempty_entry_point_inventory(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        text = atlas.read_text(encoding="utf-8")
        start = text.index("## Entry-point families")
        end = text.index("## Needs review")
        self._write(atlas, text[:start] + text[end:])

        self.assertTrue(
            any("needs exactly one `## Entry-point families`" in error for error in self._errors())
        )

    def test_entry_point_row_requires_view_or_substantive_waiver(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "| Alpha library helper | `src/a.py :: alpha` | | Pure synchronous value lookup has no architectural ordering, handoff, or recovery. |",
                "| Demo work submission | `src/a.py :: alpha` | | |\n"
                "| Batch import | `src/b.py :: beta` | | None |",
            ),
        )

        errors = self._errors()
        self.assertTrue(any("provide exactly one Focused view" in error for error in errors))
        self.assertTrue(any("No-view reason must explain" in error for error in errors))

    def test_focused_view_must_bind_exactly_one_inventory_family(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "| Alpha library helper | `src/a.py :: alpha` | | Pure synchronous value lookup has no architectural ordering, handoff, or recovery. |",
                "| Demo work submission | `src/a.py :: alpha` | [[Project Map/Flows/How Does Demo Work Finish.md]] | |\n"
                "| Batch import | `src/b.py :: beta` | [[Project Map/Flows/How Does Demo Work Finish.md]] | |",
            ),
        )
        self._write_entry_point_view(declared_family="Different family")

        errors = self._errors()
        self.assertTrue(any("target must declare `entry-point-family" in error for error in errors))
        self.assertTrue(any("each inventory row needs its own focused view" in error for error in errors))

    def test_entry_point_representative_anchor_is_validated(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "`src/a.py :: alpha`",
                "`src/missing.py :: launch`",
                1,
            ),
        )

        self.assertTrue(any("anchor path not found" in error for error in self._errors()))

    def test_successful_full_validation_writes_exact_receipt(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        result = self._run_validator_cli("--check-coverage", "--write-receipt")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        receipt_path = self.map_dir / ".mental-map-validation.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(2, receipt["schema"])
        self.assertEqual(["src/a.py", "src/b.py"], receipt["changedPaths"])
        self.assertIn("statusContext", receipt)
        self.assertIn("Validation receipt:", result.stdout)

    def test_relative_receipt_path_is_map_relative_for_validation(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        result = self._run_validator_cli(
            "--check-coverage",
            "--write-receipt",
            "--receipt",
            "receipts/exact.json",
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue((self.map_dir / "receipts/exact.json").is_file())

    def test_failed_validation_preserves_previous_receipt(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        first = self._run_validator_cli("--check-coverage", "--write-receipt")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        receipt_path = self.map_dir / ".mental-map-validation.json"
        original = receipt_path.read_bytes()
        canvas_path = self.map_dir / "Demo Atlas.canvas"
        canvas = json.loads(canvas_path.read_text(encoding="utf-8"))
        canvas["nodes"][1]["file"] = "Blocks/A.md"
        self._write(canvas_path, json.dumps(canvas))

        failed = self._run_validator_cli("--check-coverage", "--write-receipt")

        self.assertEqual(1, failed.returncode)
        self.assertEqual(original, receipt_path.read_bytes())

    def test_repository_change_during_validation_blocks_receipt(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        real_validate = validator.validate

        def change_repository(args: object) -> object:
            report = real_validate(args)
            self._write(self.repo / "src/a.py", "def alpha():\n    return 'changed'\n")
            return report

        result, output = self._run_main_with_validation_side_effect(change_repository)

        self.assertEqual(2, result)
        self.assertIn("repository target changed during validation", output)
        self.assertFalse((self.map_dir / ".mental-map-validation.json").exists())

    def test_map_change_during_validation_blocks_receipt(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        real_validate = validator.validate

        def change_map(args: object) -> object:
            report = real_validate(args)
            atlas = self.map_dir / "Demo Atlas.md"
            self._write(
                atlas,
                atlas.read_text(encoding="utf-8") + "\nChanged during validation.\n",
            )
            return report

        result, output = self._run_main_with_validation_side_effect(change_map)

        self.assertEqual(2, result)
        self.assertIn("mental-map artifacts changed during validation", output)
        self.assertFalse((self.map_dir / ".mental-map-validation.json").exists())

    def test_validator_reads_utf8_domain_language(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "Purpose: Accept work.", "Purpose: Accept café work for José."
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertEqual([], self._errors())

    def test_extensionless_dotted_wikilink_resolves_block_title(self) -> None:
        block_b = self.map_dir / "Blocks/B.md"
        dotted_block = self.map_dir / "Blocks/API v2.0.md"
        self._write(
            dotted_block,
            block_b.read_text(encoding="utf-8").replace(
                "# B\n", "# API v2.0\n"
            ),
        )
        block_b.unlink()
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "[[B]]", "[[API v2.0]]"
            ),
        )
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        assert isinstance(nodes, list)
        nodes[2]["file"] = "Project Map/Blocks/API v2.0.md"
        nodes[2]["subpath"] = "#API v2.0"
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace("[[B]]", "[[API v2.0]]"),
        )

        self.assertEqual([], self._errors())

    def test_explicit_markdown_suffix_resolves_block_title(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace("[[B]]", "[[B.md]]"),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertEqual([], self._errors())

    def test_only_responsibility_blocks_may_declare_code_footprints(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "kind: responsibility", "kind: runtime"
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any(
                "only kind responsibility may declare Code footprint" in item
                for item in self._errors()
            )
        )

    def test_reasoned_tests_exclusion_is_valid_coverage_boundary(self) -> None:
        self._write(self.repo / "tests/test_app.py", "def test_app():\n    assert True\n")
        self._write(
            self.map_dir / "Demo Code Coverage.md",
            f"""---
type: mental-map-coverage
project: Demo
revision: {self.head}
---

# Demo Code Coverage

Include:
- `src/**`
- `tests/**`

Exclude:
- `tests/**` -> user requested tests outside this atlas boundary
""",
        )
        reporter = validator.Reporter()
        blocks = {
            path.stem: validator.parse_block(path, reporter)
            for path in sorted((self.map_dir / "Blocks").glob("*.md"))
        }

        validator.validate_coverage(
            self.map_dir / "Demo Code Coverage.md",
            blocks,
            self.repo,
            reporter,
        )

        self.assertEqual([], reporter.errors)
        self.assertEqual(1, reporter.excluded_files)

    def test_v2_requires_native_frontmatter_and_vault(self) -> None:
        self._write_v2_atlas(
            canvas=self._valid_canvas(),
            base=self._valid_base(),
            frontmatter="",
        )
        errors = self._errors(include_vault=False)
        self.assertTrue(any("requires canvas frontmatter" in item for item in errors))
        self.assertTrue(any("requires base frontmatter" in item for item in errors))
        self.assertTrue(any("requires --vault" in item for item in errors))

    def test_v2_rejects_parent_of_actual_obsidian_vault(self) -> None:
        (self.vault / ".obsidian").rmdir()
        (self.map_dir / ".obsidian").mkdir()
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        errors = self._errors()

        self.assertTrue(
            any("vault root must contain .obsidian" in item for item in errors)
        )

    def test_v2_requires_source_free_atlas_orientation(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "Domain boundary: Accept and finish demo work; external concerns stay outside.\n",
                "",
            ),
        )

        self.assertTrue(
            any(
                "needs a non-empty Domain boundary: line" in item
                for item in self._errors()
            )
        )

    def test_canvas_rejects_duplicate_and_dangling_ids(self) -> None:
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        assert isinstance(nodes, list)
        nodes[2]["id"] = "mental-map:block:demo.a"
        edges = canvas["edges"]
        assert isinstance(edges, list)
        edges[0]["toNode"] = "missing"
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())
        errors = self._errors()
        self.assertTrue(
            any("duplicate Canvas id: mental-map:block:demo.a" in item for item in errors)
        )
        self.assertTrue(any("references missing node id: missing" in item for item in errors))

    def test_canvas_rejects_noncanonical_file_cards_and_edge_drift(self) -> None:
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        edges = canvas["edges"]
        assert isinstance(nodes, list) and isinstance(edges, list)
        nodes[2]["file"] = "Project Map/Demo Atlas.md"
        edges[0]["label"] = "uses"
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())
        errors = self._errors()
        self.assertTrue(
            any("must point to a canonical mental-map block" in item for item in errors)
        )

        nodes[2]["file"] = "Project Map/Blocks/B.md"
        self._write(
            self.map_dir / "Demo Atlas.canvas", json.dumps(canvas)
        )
        errors = self._errors()
        self.assertTrue(
            any("lacks a matching source-note [implemented]" in item for item in errors)
        )

    def test_generated_block_card_must_narrow_to_its_heading(self) -> None:
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        assert isinstance(nodes, list)
        del nodes[1]["subpath"]
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        self.assertTrue(
            any(
                "must use subpath `#A`" in item
                and "native drag surface" in item
                for item in self._errors()
            )
        )

    def test_relationships_canvas_cannot_replace_compact_backbone(self) -> None:
        compact = self._valid_canvas()
        compact["edges"] = []
        relationships = self._valid_canvas()
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(relationships),
        )
        self._write_v2_atlas(
            canvas=compact,
            base=self._valid_base(),
            frontmatter=(
                "canvas: Demo Atlas.canvas\n"
                "relationships-canvas: Views/Demo All Relationships.canvas\n"
                "base: Demo Blocks.base\n"
                "sync-state: .mental-map-state.json\n"
            ),
            extra_body="[[Views/Demo All Relationships.canvas]]",
        )

        self.assertTrue(
            any(
                "compact Canvas has unexplained isolated card [[A]]" in error
                for error in self._errors()
            )
        )

    def test_relationships_canvas_cannot_replace_compact_front_door_cards(
        self,
    ) -> None:
        relationships = self._valid_canvas()
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(relationships),
        )
        self._write_v2_atlas(
            canvas={"nodes": [], "edges": []},
            base=self._valid_base(),
            frontmatter=(
                "canvas: Demo Atlas.canvas\n"
                "relationships-canvas: Views/Demo All Relationships.canvas\n"
                "base: Demo Blocks.base\n"
                "sync-state: .mental-map-state.json\n"
            ),
            extra_body="[[Views/Demo All Relationships.canvas]]",
        )

        self.assertTrue(
            any(
                "compact Canvas needs at least one active canonical file-backed "
                "block card" in item
                for item in self._errors()
            )
        )

    def test_mermaid_cannot_replace_a_compact_orientation_card(self) -> None:
        compact = self._valid_canvas()
        compact["nodes"] = compact["nodes"][:2]
        compact["edges"] = []
        self._write(
            self.map_dir / "Flows/How Does Work Finish.md",
            """---
type: mental-map-view
project: Demo
view: journey
level: responsibility
---

# How Does Work Finish?

Scope: The accepted work path.

Legend: Solid arrows are implemented relationships.

```mermaid
flowchart LR
  A["A"]
  B["B"]
  A -->|sends work to| B
  class A,B internal-link
```

Blocks: [[A]] · [[B]]
""",
        )
        self._write_v2_atlas(
            canvas=compact,
            base=self._valid_base(),
            extra_body="[[How Does Work Finish]]",
        )

        self.assertTrue(
            any(
                "compact Canvas omits orientation block [[B]]" in error
                for error in self._errors()
            )
        )

    def test_compact_canvas_requires_declared_semantic_groups(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        text = atlas.read_text(encoding="utf-8")
        start = text.index("## Canvas semantic groups\n")
        end = text.index("## Needs review\n")
        self._write(atlas, text[:start] + text[end:])

        self.assertTrue(
            any(
                "needs exactly one `## Canvas semantic groups` section" in error
                for error in self._errors()
            )
        )

    def test_compact_canvas_rejects_undeclared_or_missing_group_nodes(self) -> None:
        canvas = self._valid_canvas()
        canvas["nodes"] = canvas["nodes"][1:]
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        self.assertTrue(
            any(
                "missing declared semantic group node `mental-map:group:demo-work`"
                in error
                for error in self._errors()
            )
        )

    def test_compact_canvas_cards_must_be_inside_their_declared_group(self) -> None:
        canvas = self._valid_canvas()
        canvas["nodes"][2]["x"] = 900
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        self.assertTrue(
            any(
                "[[B]] must be fully contained by declared semantic group `Demo work`"
                in error
                for error in self._errors()
            )
        )

    def test_compact_canvas_accepts_connected_semantic_groups(self) -> None:
        self._write_v2_atlas(
            canvas=self._two_group_canvas(), base=self._valid_base()
        )
        self._declare_two_canvas_groups()

        self.assertEqual([], self._errors())

    def test_compact_canvas_semantic_groups_need_one_backbone(self) -> None:
        canvas = self._two_group_canvas()
        canvas["edges"] = []
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())
        self._declare_two_canvas_groups()

        self.assertTrue(
            any(
                "semantic groups do not form one canonical orientation backbone"
                in error
                for error in self._errors()
            )
        )

    def test_mermaid_cannot_replace_the_compact_canvas_backbone(self) -> None:
        canvas = self._valid_canvas()
        canvas["edges"] = []
        self._write(
            self.map_dir / "Flows/How Does Work Finish.md",
            """---
type: mental-map-view
project: Demo
view: journey
level: responsibility
---

# How Does Work Finish?

Scope: The accepted work path.

Legend: Solid arrows are implemented relationships.

```mermaid
flowchart LR
  A["A"]
  B["B"]
  A -->|sends work to| B
  class A,B internal-link
```

Blocks: [[A]] · [[B]]
""",
        )
        self._write_v2_atlas(
            canvas=canvas,
            base=self._valid_base(),
            extra_body="[[How Does Work Finish]]",
        )

        errors = self._errors()
        self.assertTrue(
            any("compact Canvas has unexplained isolated card [[A]]" in error for error in errors)
        )
        self.assertTrue(
            any("compact Canvas has unexplained isolated card [[B]]" in error for error in errors)
        )

    def test_deprecated_blocks_do_not_require_compact_cards(self) -> None:
        self._write(
            self.map_dir / "Blocks/Legacy.md",
            """---
type: mental-map-block
project: Demo
atlas-id: demo.legacy
kind: actor
level: context
status: deprecated
confidence: accounted
---

# Legacy

Purpose: Record a retired participant.

Deprecation: Replaced by the active path.
""",
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertEqual([], self._errors())

    def test_relationships_canvas_is_validated_independently(self) -> None:
        relationships = self._valid_canvas()
        edges = relationships["edges"]
        assert isinstance(edges, list)
        edges[0]["label"] = "invented relationship"
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(relationships),
        )
        self._write_v2_atlas(
            canvas=self._valid_canvas(),
            base=self._valid_base(),
            frontmatter=(
                "canvas: Demo Atlas.canvas\n"
                "relationships-canvas: Views/Demo All Relationships.canvas\n"
                "base: Demo Blocks.base\n"
                "sync-state: .mental-map-state.json\n"
            ),
            extra_body="[[Views/Demo All Relationships.canvas]]",
        )

        errors = self._errors()
        self.assertTrue(
            any(
                "Demo All Relationships.canvas" in item
                and "lacks a matching source-note [implemented]" in item
                for item in errors
            )
        )

    def test_relationships_canvas_must_be_exhaustive(self) -> None:
        relationships = self._valid_canvas()
        relationships["edges"] = []
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(relationships),
        )
        self._write_v2_atlas(
            canvas=self._valid_canvas(),
            base=self._valid_base(),
            frontmatter=(
                "canvas: Demo Atlas.canvas\n"
                "relationships-canvas: Views/Demo All Relationships.canvas\n"
                "base: Demo Blocks.base\n"
                "sync-state: .mental-map-state.json\n"
            ),
            extra_body="[[Views/Demo All Relationships.canvas]]",
        )

        self.assertTrue(
            any(
                "all-relationships view omits [implemented] relationship" in item
                for item in self._errors()
            )
        )

    def test_relationships_canvas_allows_one_unambiguous_unlabelled_edge(
        self,
    ) -> None:
        relationships = self._valid_canvas()
        edges = relationships["edges"]
        assert isinstance(edges, list)
        del edges[0]["label"]
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(relationships),
        )
        self._write_v2_atlas(
            canvas=self._valid_canvas(), base=self._valid_base()
        )

        self.assertEqual([], self._errors())

    def test_relationships_canvas_keeps_declared_semantic_groups(self) -> None:
        relationships = self._valid_canvas()
        relationships["nodes"] = relationships["nodes"][1:]
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(relationships),
        )
        self._write_v2_atlas(
            canvas=self._valid_canvas(), base=self._valid_base()
        )

        self.assertTrue(
            any(
                "Demo All Relationships.canvas: missing declared semantic group node"
                in item
                for item in self._errors()
            )
        )

    def test_relationships_canvas_cards_must_not_overlap(self) -> None:
        relationships = self._valid_canvas()
        relationships["nodes"][2]["x"] = 100
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(relationships),
        )
        self._write_v2_atlas(
            canvas=self._valid_canvas(), base=self._valid_base()
        )

        self.assertTrue(
            any(
                "all-relationships canonical block cards overlap: [[A]] and [[B]]"
                in item
                for item in self._errors()
            )
        )

    def test_relationships_canvas_deeper_card_inherits_ancestor_group(self) -> None:
        block_b = self.map_dir / "Blocks/B.md"
        self._write(
            block_b,
            block_b.read_text(encoding="utf-8").replace(
                "# B\n",
                "# B\n\nParent: [[A]]\n",
            ),
        )
        relationships = self._valid_canvas()
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(relationships),
        )
        compact = self._valid_canvas()
        compact["nodes"] = compact["nodes"][:2]
        compact["edges"] = []
        self._write_v2_atlas(canvas=compact, base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "[[A]] · [[B]]",
                "[[A]]",
            ),
        )

        self.assertEqual([], self._errors())

    def test_compact_canvas_has_no_numeric_edge_label_quota(self) -> None:
        labels = [f"relationship {position}" for position in range(13)]
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "- [implemented] [[B]] -> sends work to",
                "\n".join(
                    f"- [implemented] [[B]] -> {label}" for label in labels
                ),
            ),
        )
        canvas = self._valid_canvas()
        canvas["edges"] = [
            {
                "id": f"mental-map:edge:demo.a-to-demo.b-{position}",
                "fromNode": "mental-map:block:demo.a",
                "toNode": "mental-map:block:demo.b",
                "label": label,
            }
            for position, label in enumerate(labels)
        ]
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        self.assertEqual([], self._errors())

    def test_compact_canvas_rejects_duplicate_semantic_edges(self) -> None:
        canvas = self._valid_canvas()
        canvas["edges"] = [
            {
                "id": f"mental-map:edge:duplicate-{position}",
                "fromNode": "mental-map:block:demo.a",
                "toNode": "mental-map:block:demo.b",
                "label": "sends work to",
            }
            for position in range(13)
        ]
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        errors = self._errors()
        self.assertTrue(
            any("duplicate semantic relationship edge" in item for item in errors)
        )

    def test_compact_canvas_allows_many_manual_navigation_labels(self) -> None:
        canvas = self._valid_canvas()
        canvas["nodes"].extend(
            [
                {
                    "id": "manual:start",
                    "type": "text",
                    "text": "Start",
                    "x": -400,
                    "y": 0,
                    "width": 200,
                    "height": 100,
                },
                {
                    "id": "manual:end",
                    "type": "text",
                    "text": "End",
                    "x": 800,
                    "y": 0,
                    "width": 200,
                    "height": 100,
                },
            ]
        )
        canvas["edges"].extend(
            {
                "id": f"manual:guide-{position}",
                "fromNode": "manual:start",
                "toNode": "manual:end",
                "label": f"guide {position}",
            }
            for position in range(12)
        )
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        self.assertEqual([], self._errors())

    def test_relationships_canvas_must_resolve_to_a_separate_file(self) -> None:
        self._write_v2_atlas(
            canvas=self._valid_canvas(),
            base=self._valid_base(),
            frontmatter=(
                "canvas: Demo Atlas.canvas\n"
                "relationships-canvas: ./Demo Atlas.canvas\n"
                "base: Demo Blocks.base\n"
                "sync-state: .mental-map-state.json\n"
            ),
            extra_body="[[Demo Atlas.canvas]]",
        )

        self.assertTrue(
            any(
                "must resolve to a separate Canvas file" in item
                for item in self._errors()
            )
        )

    def test_relationships_canvas_hardlink_is_not_an_independent_layout(self) -> None:
        self._write_v2_atlas(
            canvas=self._valid_canvas(),
            base=self._valid_base(),
            frontmatter=(
                "canvas: Demo Atlas.canvas\n"
                "relationships-canvas: Demo Relationships Alias.canvas\n"
                "base: Demo Blocks.base\n"
                "sync-state: .mental-map-state.json\n"
            ),
            extra_body="[[Demo Relationships Alias.canvas]]",
        )
        try:
            (self.map_dir / "Demo Relationships Alias.canvas").hardlink_to(
                self.map_dir / "Demo Atlas.canvas"
            )
        except OSError as error:
            self.skipTest(f"hardlinks are unavailable: {error}")

        self.assertTrue(
            any(
                "must resolve to a separate Canvas file" in item
                for item in self._errors()
            )
        )

    def test_atlas_link_must_not_resolve_to_same_named_wrong_canvas(self) -> None:
        relationships = self._valid_canvas()
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(relationships),
        )
        self._write(
            self.map_dir / "Other/Views/Demo All Relationships.canvas",
            json.dumps({"nodes": [], "edges": []}),
        )
        self._write_v2_atlas(
            canvas=self._valid_canvas(),
            base=self._valid_base(),
            frontmatter=(
                "canvas: Demo Atlas.canvas\n"
                "relationships-canvas: Views/Demo All Relationships.canvas\n"
                "base: Demo Blocks.base\n"
                "sync-state: .mental-map-state.json\n"
            ),
            extra_body="[[Other/Views/Demo All Relationships.canvas]]",
        )
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "[[Views/Demo All Relationships.canvas]]",
                "[[Other/Views/Demo All Relationships.canvas]]",
            ),
        )

        self.assertTrue(
            any(
                "atlas must link or embed [[Views/Demo All Relationships.canvas]]"
                in item
                for item in self._errors()
            )
        )

    def test_canvas_explains_that_block_cards_are_vault_relative(self) -> None:
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        assert isinstance(nodes, list)
        nodes[1]["file"] = "Blocks/A.md"
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        errors = self._errors()

        self.assertTrue(
            any(
                "uses a Canvas-relative path" in item
                and "use `Project Map/Blocks/A.md`" in item
                for item in errors
            )
        )

    def test_canvas_rejects_nonliteral_vault_paths_that_obsidian_cannot_resolve(
        self,
    ) -> None:
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        assert isinstance(nodes, list)
        nodes[1]["file"] = " Project Map/Blocks/A.md "
        nodes[2]["file"] = "./Project Map/Blocks/B.md"
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        errors = self._errors()

        self.assertTrue(any("has surrounding whitespace" in item for item in errors))
        self.assertTrue(
            any(
                "must be a normalized vault-relative POSIX path" in item
                and "use `Project Map/Blocks/B.md`" in item
                for item in errors
            )
        )

    def test_canvas_accepts_exact_paths_for_a_deeply_nested_project_map(self) -> None:
        nested_map_dir = self.vault / "Architecture/Projects/Project Map"
        nested_map_dir.parent.mkdir(parents=True)
        self.map_dir.rename(nested_map_dir)
        self.map_dir = nested_map_dir
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        assert isinstance(nodes, list)
        for node in nodes:
            if node.get("type") == "file":
                node["file"] = f"Architecture/Projects/{node['file']}"
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())
        atlas_path = self.map_dir / "Demo Atlas.md"
        atlas_text = atlas_path.read_text(encoding="utf-8")
        atlas_text = atlas_text.replace(
            "[[Demo Atlas.canvas]]",
            "[[Architecture/Projects/Project Map/Demo Atlas.canvas]]",
        ).replace(
            "[[Demo Blocks.base]]",
            "[[Architecture/Projects/Project Map/Demo Blocks.base]]",
        )
        atlas_path.write_text(atlas_text, encoding="utf-8")

        self.assertEqual([], self._errors())

    def test_canvas_requires_integer_geometry_and_positive_dimensions(self) -> None:
        cases = (
            ("x", None, "x must be an integer"),
            ("x", 0.5, "x must be an integer"),
            ("y", True, "y must be an integer"),
            ("width", "300", "width must be a positive integer"),
            ("height", 0, "height must be a positive integer"),
        )
        for field_name, value, message in cases:
            with self.subTest(field_name=field_name, value=value):
                canvas = self._valid_canvas()
                nodes = canvas["nodes"]
                assert isinstance(nodes, list)
                if value is None:
                    nodes[0].pop(field_name)
                else:
                    nodes[0][field_name] = value
                self._write_v2_atlas(canvas=canvas, base=self._valid_base())

                self.assertTrue(any(message in item for item in self._errors()))

    def test_canvas_requires_native_text_and_link_payloads(self) -> None:
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        assert isinstance(nodes, list)
        nodes.extend(
            [
                {
                    "id": "manual:text",
                    "type": "text",
                    "x": 0,
                    "y": 300,
                    "width": 200,
                    "height": 100,
                },
                {
                    "id": "manual:link",
                    "type": "link",
                    "url": 42,
                    "x": 300,
                    "y": 300,
                    "width": 200,
                    "height": 100,
                },
            ]
        )
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        errors = self._errors()
        self.assertTrue(any("text node needs a string text value" in item for item in errors))
        self.assertTrue(any("link node needs a string url value" in item for item in errors))

    def test_base_requires_filters_views_and_columns(self) -> None:
        base = """filters:
  and:
    - 'type == "mental-map-block"'
views:
  - type: table
    order:
      - file.name
      - status
"""
        self._write_v2_atlas(canvas=self._valid_canvas(), base=base)
        errors = self._errors()
        self.assertTrue(any("must filter project" in item for item in errors))
        self.assertTrue(any("missing required columns" in item for item in errors))
        self.assertTrue(any("confidence" in item for item in errors))
        self.assertTrue(any("reviewed-revision" in item for item in errors))
        self.assertTrue(any("needs a `Needs review` view" in item for item in errors))
        self.assertTrue(any("must compare" in item for item in errors))

    def test_atlas_must_embed_contextual_needs_review_view(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "![[Demo Blocks.base#Needs review]]\n", ""
            ),
        )

        self.assertTrue(
            any("atlas must embed" in item for item in self._errors())
        )

    def test_v2_requires_stable_block_metadata_and_canvas_id(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        text = block_a.read_text(encoding="utf-8").replace(
            "atlas-id: demo.a", "atlas-id: demo.b"
        )
        text = text.replace("confidence: traced", "confidence: guessed")
        text = text.replace(f"reviewed-revision: {self.head}", "reviewed-revision:")
        self._write(block_a, text)
        canvas = self._valid_canvas()
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())
        errors = self._errors()
        self.assertTrue(any("duplicate atlas-id `demo.b`" in item for item in errors))
        self.assertTrue(any("confidence must be one of" in item for item in errors))
        self.assertTrue(any("needs reviewed-revision" in item for item in errors))
        self.assertTrue(any("id must be `mental-map:block:demo.b`" in item for item in errors))

    def test_v2_requires_nonempty_atlas_id(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "atlas-id: demo.a", "atlas-id:"
            ),
        )
        self._write_v2_atlas(
            canvas=self._valid_canvas(), base=self._valid_base()
        )
        self.assertTrue(
            any("map-version 2 requires atlas-id" in item for item in self._errors())
        )

    def test_block_h1_inside_fenced_code_does_not_satisfy_heading_contract(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "# A\n",
                "```text\n# A\n```\n",
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any(
                "A.md: H1 must exactly match filename (A)" in item
                for item in self._errors()
            )
        )

    def test_block_title_rejects_obsidian_link_delimiters(self) -> None:
        source = self.map_dir / "Blocks/A.md"
        renamed = self.map_dir / "Blocks/A#Unsafe.md"
        self._write(
            renamed,
            source.read_text(encoding="utf-8").replace("# A\n", "# A#Unsafe\n"),
        )
        source.unlink()
        canvas = self._valid_canvas()
        canvas["nodes"][1]["file"] = "Project Map/Blocks/A#Unsafe.md"
        canvas["nodes"][1]["subpath"] = "#A#Unsafe"
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        self.assertTrue(
            any(
                "A#Unsafe.md: block title violates the safe one-component"
                in item
                for item in self._errors()
            )
        )

    def test_frontmatter_comment_does_not_satisfy_block_h1_contract(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        text = block_a.read_text(encoding="utf-8")
        text = text.replace("\n---\n\n# A\n", "\n# A\n---\n")
        self._write(block_a, text)
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any(
                "A.md: H1 must exactly match filename (A)" in item
                for item in self._errors()
            )
        )

    def test_html_comment_does_not_satisfy_block_h1_contract(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "# A\n",
                "<!--\n# A\n-->\n",
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any(
                "A.md: H1 must exactly match filename (A)" in item
                for item in self._errors()
            )
        )

    def test_manual_nested_canvas_cards_and_edges_are_preserved(self) -> None:
        self._write(
            self.map_dir / "Views/Scoped Architecture.canvas",
            json.dumps({"nodes": [], "edges": []}),
        )
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        edges = canvas["edges"]
        assert isinstance(nodes, list) and isinstance(edges, list)
        nodes.extend(
            [
                {
                    "id": "manual:orientation",
                    "type": "text",
                    "text": "Open the scoped view for detail.",
                    "x": 0,
                    "y": 300,
                    "width": 260,
                    "height": 100,
                },
                {
                    "id": "manual:scoped-view",
                    "type": "file",
                    "file": "Project Map/Views/Scoped Architecture.canvas",
                    "x": 400,
                    "y": 300,
                    "width": 300,
                    "height": 200,
                },
            ]
        )
        edges.append(
            {
                "id": "manual:navigation-edge",
                "fromNode": "manual:orientation",
                "toNode": "manual:scoped-view",
            }
        )
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())
        self.assertEqual([], self._errors())

    def test_manual_edge_between_block_cards_must_match_canonical_relationship(
        self,
    ) -> None:
        canvas = self._valid_canvas()
        edges = canvas["edges"]
        assert isinstance(edges, list)
        edges.append(
            {
                "id": "manual:invented-block-edge",
                "fromNode": "mental-map:block:demo.a",
                "toNode": "mental-map:block:demo.b",
                "label": "deletes all work",
            }
        )
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        self.assertTrue(
            any(
                "lacks a matching source-note [implemented] relationship" in item
                and "deletes all work" in item
                for item in self._errors()
            )
        )

    def test_generated_block_id_must_remain_a_file_backed_card(self) -> None:
        compact = self._valid_canvas()
        compact["nodes"][1] = {
            "id": "mental-map:block:demo.a",
            "type": "text",
            "text": "A copied summary",
            "x": 0,
            "y": 0,
            "width": 300,
            "height": 200,
        }
        compact["edges"] = []
        self._write(
            self.map_dir / "Views/Demo All Relationships.canvas",
            json.dumps(self._valid_canvas()),
        )
        self._write_v2_atlas(
            canvas=compact,
            base=self._valid_base(),
            frontmatter=(
                "canvas: Demo Atlas.canvas\n"
                "relationships-canvas: Views/Demo All Relationships.canvas\n"
                "base: Demo Blocks.base\n"
                "sync-state: .mental-map-state.json\n"
            ),
            extra_body="[[Views/Demo All Relationships.canvas]]",
        )

        self.assertTrue(
            any(
                "generated block card must use type `file`" in item
                for item in self._errors()
            )
        )

    def test_dot_prefixed_coverage_patterns_are_preserved(self) -> None:
        self.assertTrue(
            validator.matches(".github/workflows/ci.yml", ".github/**")
        )
        self.assertTrue(
            validator.matches(".github/workflows/ci.yml", "./.github/**")
        )

    def test_v2_journey_view_still_requires_mermaid(self) -> None:
        self._write_v2_atlas(
            canvas=self._valid_canvas(),
            base=self._valid_base(),
            extra_body="[[How Does Work Finish]]",
        )
        self._write(
            self.map_dir / "Views/How Does Work Finish.md",
            """---
type: mental-map-view
project: Demo
view: journey
level: responsibility
---

# How Does Work Finish?

Scope: The main work journey.

Legend: Solid is implemented.

Blocks: [[A]] · [[B]]
""",
        )
        errors = self._errors()
        self.assertTrue(
            any("How Does Work Finish.md: note contains no Mermaid diagram" in item for item in errors)
        )

    def test_v2_rejects_abbreviated_atlas_revision(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(self.head, self.head[:8]),
        )

        self.assertTrue(
            any("revision must be a full" in item for item in self._errors())
        )

    def test_v2_rejects_mismatched_atlas_and_coverage_revisions(self) -> None:
        previous = self.head
        self._write(self.repo / "src/a.py", "def alpha():\n    return 'changed'\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "change")
        self.head = self.git("rev-parse", "HEAD")
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        self._write_coverage(previous)

        errors = self._errors()
        self.assertTrue(any("revision must match" in item for item in errors))
        self.assertTrue(any("currently checked-out HEAD" in item for item in errors))

    def test_v2_rejects_stale_matching_revisions(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        self._write(self.repo / "src/a.py", "def alpha():\n    return 'changed'\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "change")

        errors = self._errors()
        self.assertTrue(
            any("Demo Atlas.md: revision must equal" in item for item in errors)
        )
        self.assertTrue(
            any("Demo Code Coverage.md: revision must equal" in item for item in errors)
        )

    def test_v2_requires_dirty_target_presentation_for_dirty_checkout(self) -> None:
        self._write(self.repo / "src/a.py", "def alpha():\n    return 'dirty'\n")
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "Mapped target: HEAD + dirty paths", "Mapped target: HEAD"
            ),
        )

        self.assertTrue(
            any(
                "Mapped target must be `HEAD + dirty paths`" in item
                for item in self._errors()
            )
        )

    def test_v2_rejects_dirty_target_presentation_for_clean_checkout(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "Mapped target: HEAD", "Mapped target: HEAD + dirty paths"
            ),
        )

        self.assertTrue(
            any(
                "Mapped target must be `HEAD`" in item
                for item in self._errors()
            )
        )

    def test_v2_requires_mapped_target_line(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace("Mapped target: HEAD\n\n", ""),
        )

        self.assertTrue(
            any("Mapped target must be `HEAD`" in item for item in self._errors())
        )

    def test_v2_rejects_unresolved_full_reviewed_revision(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                self.head, "0" * len(self.head)
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any("reviewed-revision: revision does not resolve" in item for item in self._errors())
        )

    def test_v2_validates_nonempty_reviewed_revision_on_any_implemented_block(self) -> None:
        self._write(
            self.map_dir / "Blocks/Operator.md",
            f"""---
type: mental-map-block
project: Demo
atlas-id: demo.operator
kind: actor
level: context
status: implemented
confidence: traced
reviewed-revision: {'0' * len(self.head)}
---

# Operator

Purpose: Starts work.

Evidence:
- `mapped at {self.head}`
""",
        )
        canvas = self._valid_canvas()
        nodes = canvas["nodes"]
        assert isinstance(nodes, list)
        nodes.append(
            {
                "id": "mental-map:block:demo.operator",
                "type": "file",
                "file": "Project Map/Blocks/Operator.md",
                "subpath": "#Operator",
                "x": -400,
                "y": 0,
                "width": 300,
                "height": 200,
            }
        )
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        self.assertTrue(
            any("Operator.md: reviewed-revision: revision does not resolve" in item for item in self._errors())
        )

    def test_v2_rejects_unresolved_full_atlas_revision(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                self.head, "0" * len(self.head)
            ),
        )

        self.assertTrue(
            any("Demo Atlas.md: revision does not resolve" in item for item in self._errors())
        )

    def test_v2_accepts_resolvable_historical_reviewed_revision(self) -> None:
        previous = self.head
        self._write(self.repo / "src/a.py", "def alpha():\n    return 'changed'\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "change")
        self.head = self.git("rev-parse", "HEAD")
        self._write_coverage()
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertIn(
            previous,
            (self.map_dir / "Blocks/A.md").read_text(encoding="utf-8"),
        )
        self.assertEqual([], self._errors())

    def test_model_links_require_exact_existing_canonical_targets(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        text = block_a.read_text(encoding="utf-8").replace(
            "[[B]]", "[[Missing/B]]"
        )
        text = text.replace(
            "Connects:\n",
            "Requires:\n"
            "- [[../B]] :: `finish` -> finish work\n\n"
            "Policies:\n"
            "- [[Policy]] -> authorizes work\n\n"
            "Connects:\n",
        )
        self._write(block_a, text)
        self._write(self.vault / "Policy.md", "# Policy\n")
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        errors = self._errors()

        self.assertTrue(any("path-qualified wikilink target does not exist" in error for error in errors))
        self.assertTrue(any("path must be a relative POSIX path" in error for error in errors))
        self.assertTrue(any("Policies: wikilink must resolve to a canonical block" in error for error in errors))

    def test_bare_model_wikilink_must_be_unique_in_the_vault(self) -> None:
        self._write(self.vault / "Other/B.md", "# B\n")
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any(
                "Connects: ambiguous wikilink [[B]]" in error
                and "exact vault-relative path" in error
                for error in self._errors()
            )
        )

    def test_path_qualified_model_wikilink_resolves_exactly(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "[[B]]", "[[Project Map/Blocks/B]]"
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertEqual([], self._errors())

    def test_scoped_canvas_cannot_replace_a_compact_orientation_card(self) -> None:
        compact = self._valid_canvas()
        compact["nodes"] = compact["nodes"][:2]
        compact["edges"] = []
        self._write(
            self.map_dir / "Views/Scoped Architecture.canvas",
            json.dumps(self._valid_canvas()),
        )
        self._write_v2_atlas(
            canvas=compact,
            base=self._valid_base(),
            extra_body="[[Views/Scoped Architecture.canvas]]",
        )

        self.assertTrue(
            any(
                "compact Canvas omits orientation block [[B]]" in error
                for error in self._errors()
            )
        )

    def test_atlas_linked_scoped_canvas_is_validated(self) -> None:
        scoped = self._valid_canvas()
        scoped["edges"][0]["fromSide"] = "diagonal"
        self._write(
            self.map_dir / "Views/Scoped Architecture.canvas",
            json.dumps(scoped),
        )
        self._write_v2_atlas(
            canvas=self._valid_canvas(),
            base=self._valid_base(),
            extra_body="[[Views/Scoped Architecture.canvas]]",
        )

        self.assertTrue(
            any(
                "Scoped Architecture.canvas: edge 1 fromSide must be one of"
                in error
                for error in self._errors()
            )
        )

    def test_manual_or_duplicate_cards_cannot_represent_canonical_blocks(self) -> None:
        canvas = self._valid_canvas()
        canvas["nodes"].append(
            {
                "id": "manual:duplicate-a",
                "type": "file",
                "file": "Project Map/Blocks/A.md",
                "subpath": "#A",
                "x": 800,
                "y": 0,
                "width": 300,
                "height": 200,
            }
        )
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        errors = self._errors()

        self.assertTrue(any("duplicates canonical block card [[A]]" in error for error in errors))
        self.assertTrue(any("manual ids are not allowed" in error for error in errors))

    def test_compact_canonical_cards_must_not_overlap(self) -> None:
        canvas = self._valid_canvas()
        canvas["nodes"][2]["x"] = 250
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        self.assertTrue(
            any(
                "compact canonical block cards overlap: [[A]] and [[B]]" in error
                for error in self._errors()
            )
        )

    def test_canvas_edge_enums_follow_json_canvas(self) -> None:
        canvas = self._valid_canvas()
        canvas["edges"][0]["fromSide"] = "center"
        canvas["edges"][0]["toEnd"] = "diamond"
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        errors = self._errors()

        self.assertTrue(any("fromSide must be one of" in error for error in errors))
        self.assertTrue(any("toEnd must be one of" in error for error in errors))

    def test_empty_orientation_scalar_does_not_consume_the_next_line(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "Purpose: Demonstrate the atlas contract.", "Purpose:"
            ),
        )

        self.assertTrue(
            any("needs a non-empty Purpose: line" in error for error in self._errors())
        )

    def test_required_orientation_rejects_draft_placeholders(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "Current risks: None known in this fixture.",
                "Current risks: DRAFT",
            ),
        )

        self.assertTrue(
            any("Current risks: must replace the DRAFT" in error for error in self._errors())
        )

    def test_v2_requires_coverage_questions_and_sync_state(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())
        atlas = self.map_dir / "Demo Atlas.md"
        text = atlas.read_text(encoding="utf-8")
        text = text.replace(
            "Coverage summary: All maintained demo sources are included.",
            "Coverage summary: DRAFT",
        )
        text = text.replace("Unresolved questions: None.", "Unresolved questions:")
        text = text.replace("sync-state: .mental-map-state.json\n", "")
        self._write(atlas, text)

        errors = self._errors()

        self.assertTrue(any("Coverage summary: must replace the DRAFT" in error for error in errors))
        self.assertTrue(any("needs a non-empty Unresolved questions: line" in error for error in errors))
        self.assertTrue(any("requires sync-state frontmatter" in error for error in errors))

    def test_yaml_surface_errors_are_rejected_in_native_artifacts(self) -> None:
        self._write_v2_atlas(
            canvas=self._valid_canvas(),
            base=self._valid_base() + "broken: [\n",
        )
        atlas = self.map_dir / "Demo Atlas.md"
        self._write(
            atlas,
            atlas.read_text(encoding="utf-8").replace(
                "map-version: 2", "map-version: 2\nflow: ["
            ),
        )
        block = self.map_dir / "Blocks/A.md"
        self._write(
            block,
            block.read_text(encoding="utf-8").replace(
                "confidence: traced", "confidence: traced\nmalformed scalar"
            ),
        )
        coverage = self.map_dir / "Demo Code Coverage.md"
        self._write(
            coverage,
            coverage.read_text(encoding="utf-8").replace(
                "revision: ", "flow: [\nrevision: ", 1
            ),
        )

        errors = self._errors()

        self.assertTrue(any("Demo Atlas.md: invalid frontmatter YAML" in error for error in errors))
        self.assertTrue(any("A.md: invalid frontmatter YAML" in error for error in errors))
        self.assertTrue(any("Demo Code Coverage.md: invalid frontmatter YAML" in error for error in errors))
        self.assertTrue(any("Demo Blocks.base: invalid Base YAML" in error for error in errors))

    def test_yaml_surface_accepts_apostrophes_in_plain_scalars(self) -> None:
        self.assertEqual(
            [],
            validator.yaml_surface_errors(
                "project: O'Reilly\n", require_top_level_scalars=True
            ),
        )

    def test_planned_and_deprecated_blocks_must_not_own_code(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "status: implemented", "status: planned"
            ),
        )
        block_b = self.map_dir / "Blocks/B.md"
        self._write(
            block_b,
            block_b.read_text(encoding="utf-8")
            .replace("status: implemented", "status: deprecated")
            .replace("Purpose: Finish work.", "Purpose: Finish work.\n\nDeprecation: Retired."),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        errors = self._errors()

        self.assertTrue(any("planned blocks must not own Code footprint" in error for error in errors))
        self.assertTrue(any("deprecated blocks must not own Code footprint" in error for error in errors))

    def test_active_evidence_must_be_concrete(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                f"- `mapped at {self.head}`", "- mapped carefully"
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any("active block Evidence must cite a concrete" in error for error in self._errors())
        )

    def test_planned_evidence_accepts_concrete_prd_document(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        text = block_a.read_text(encoding="utf-8")
        text = text.replace("status: implemented", "status: planned")
        text = text.replace(
            "Code footprint:\n- `src/a.py`\n\n"
            "Concrete anchors:\n- `src/a.py :: alpha`\n\n",
            "",
        )
        text = text.replace(
            f"- `mapped at {self.head}`", "- [PRD-12](docs/prd/work.md)"
        )
        self._write(block_a, text)
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertEqual([], self._errors())

    def test_planned_canvas_preview_does_not_invent_a_current_backbone_edge(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        text = block_a.read_text(encoding="utf-8")
        text = text.replace("status: implemented", "status: planned")
        text = text.replace(
            "Code footprint:\n- `src/a.py`\n\n"
            "Concrete anchors:\n- `src/a.py :: alpha`\n\n",
            "",
        )
        text = text.replace(
            "- [implemented] [[B]] -> sends work to",
            "- [planned] [[B]] -> sends work to",
        )
        text = text.replace(
            f"- `mapped at {self.head}`", "- [PRD-12](docs/prd/work.md)"
        )
        self._write(block_a, text)
        canvas = self._valid_canvas()
        canvas["edges"] = []
        self._write(
            self.map_dir / "Flows/How Might Work Finish.md",
            """---
type: mental-map-view
project: Demo
view: journey
level: responsibility
---

# How Might Work Finish?

Scope: The supported future work path.

Legend: Dashed arrows are planned relationships.

```mermaid
flowchart LR
  A["A"]
  B["B"]
  A -. "sends work to" .-> B
  class A,B internal-link
  class A planned
```

Blocks: [[A]] · [[B]]
""",
        )
        self._write_v2_atlas(
            canvas=canvas,
            base=self._valid_base(),
            extra_body="[[How Might Work Finish]]",
        )

        self.assertEqual([], self._errors())

    def test_parent_hierarchy_must_be_acyclic(self) -> None:
        for name, parent in (("A", "B"), ("B", "A")):
            path = self.map_dir / f"Blocks/{name}.md"
            self._write(
                path,
                path.read_text(encoding="utf-8").replace(
                    f"# {name}\n", f"# {name}\n\nParent: [[{parent}]]\n"
                ),
            )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any("parent hierarchy contains a cycle" in error for error in self._errors())
        )

    def test_concrete_anchor_cannot_escape_repository(self) -> None:
        self._write(self.root / "outside.py", "def alpha():\n    pass\n")
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "src/a.py :: alpha", "../outside.py :: alpha"
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any("concrete anchor: path must be a relative POSIX path" in error for error in self._errors())
        )

    def test_concrete_anchor_accepts_dot_qualified_symbol(self) -> None:
        self._write(
            self.repo / "src/a.py",
            "class AlphaService:\n    def alpha(self):\n        return 'a'\n",
        )
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "src/a.py :: alpha", "src/a.py :: AlphaService.alpha"
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertEqual([], self._errors())

    def test_concrete_anchor_requires_each_qualified_segment(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "src/a.py :: alpha", "src/a.py :: MissingService.alpha"
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any(
                "anchor symbol segment `MissingService` not found" in error
                for error in self._errors()
            )
        )

    def test_concrete_anchor_rejects_undocumented_qualifier_syntax(self) -> None:
        block_a = self.map_dir / "Blocks/A.md"
        self._write(
            block_a,
            block_a.read_text(encoding="utf-8").replace(
                "src/a.py :: alpha", "src/a.py :: AlphaService#alpha"
            ),
        )
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        self.assertTrue(
            any(
                "symbol must be a bare or dot-qualified token" in error
                for error in self._errors()
            )
        )

    def test_coverage_rejects_unclassified_inventory_paths(self) -> None:
        self._write(self.repo / "README.md", "# Demo\n")
        reporter = validator.Reporter()
        blocks = {
            path.stem: validator.parse_block(path, reporter)
            for path in sorted((self.map_dir / "Blocks").glob("*.md"))
        }

        validator.validate_coverage(
            self.map_dir / "Demo Code Coverage.md",
            blocks,
            self.repo,
            reporter,
        )

        self.assertTrue(any("unclassified repository files" in error for error in reporter.errors))
        self.assertEqual(1, reporter.unresolved_files)

    def test_coverage_exclude_classifies_paths_outside_include(self) -> None:
        self._write(self.repo / "docs/generated.txt", "generated\n")
        coverage = self.map_dir / "Demo Code Coverage.md"
        self._write(
            coverage,
            coverage.read_text(encoding="utf-8").replace(
                "Exclude:\n", "Exclude:\n- `docs/**` -> generated documentation\n"
            ),
        )
        reporter = validator.Reporter()
        blocks = {
            path.stem: validator.parse_block(path, reporter)
            for path in sorted((self.map_dir / "Blocks").glob("*.md"))
        }

        validator.validate_coverage(coverage, blocks, self.repo, reporter)

        self.assertEqual([], reporter.errors)
        self.assertEqual(1, reporter.excluded_files)
        self.assertEqual(0, reporter.unresolved_files)

    def test_coverage_requires_a_selected_path_after_exclusions(self) -> None:
        coverage = self.map_dir / "Demo Code Coverage.md"
        self._write(
            coverage,
            coverage.read_text(encoding="utf-8").replace(
                "Exclude:\n", "Exclude:\n- `src/**` -> generated sources\n"
            ),
        )
        reporter = validator.Reporter()
        blocks = {
            path.stem: validator.parse_block(path, reporter)
            for path in sorted((self.map_dir / "Blocks").glob("*.md"))
        }

        validator.validate_coverage(coverage, blocks, self.repo, reporter)

        self.assertTrue(
            any("selects no maintained files after Exclude" in error for error in reporter.errors)
        )

    def test_block_title_rejects_trailing_dot(self) -> None:
        source = self.map_dir / "Blocks/A.md"
        renamed = self.map_dir / "Blocks/A..md"
        self._write(
            renamed,
            source.read_text(encoding="utf-8").replace("# A\n", "# A.\n"),
        )
        source.unlink()
        canvas = self._valid_canvas()
        canvas["nodes"][1]["file"] = "Project Map/Blocks/A..md"
        canvas["nodes"][1]["subpath"] = "#A."
        self._write_v2_atlas(canvas=canvas, base=self._valid_base())

        self.assertTrue(
            any("block title violates the safe one-component" in error and "ends in a dot" in error for error in self._errors())
        )

    def test_capture_sync_status_rejects_unsupported_schema(self) -> None:
        args = SimpleNamespace(
            repo=str(self.repo),
            map_dir=str(self.map_dir),
            coverage=None,
            state=None,
        )
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"schema": 999}', stderr=""
        )

        with mock.patch.object(validator.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(
                validator.validation_receipt.ValidationReceiptError,
                "sync status must use schema",
            ):
                validator.capture_sync_status(args)

    def test_primary_markdown_artifacts_cannot_escape_map_directory(self) -> None:
        self._write_v2_atlas(canvas=self._valid_canvas(), base=self._valid_base())

        atlas_args = self._args()
        atlas_args.atlas = "../Outside Atlas.md"
        atlas_report = validator.validate(atlas_args)
        self.assertTrue(
            any("atlas note must stay inside" in error for error in atlas_report.errors)
        )

        coverage_args = self._args()
        coverage_args.coverage = "../Outside Coverage.md"
        coverage_report = validator.validate(coverage_args)
        self.assertTrue(
            any(
                "coverage note must stay inside" in error
                for error in coverage_report.errors
            )
        )

    def test_validator_rejects_repository_map_overlap(self) -> None:
        inside_map = self.repo / "Vault/Map"
        inside_map.mkdir(parents=True)
        args = self._args()
        args.map_dir = str(inside_map)

        report = validator.validate(args)

        self.assertTrue(any("must not overlap" in error for error in report.errors))

    def test_git_revision_context_accepts_sha256_repository(self) -> None:
        repo = self.root / "sha256-repo"
        init = subprocess.run(
            ["git", "init", "--quiet", "--object-format=sha256", str(repo)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if init.returncode != 0:
            self.skipTest("installed Git does not support SHA-256 repositories")
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test User"],
            check=True,
        )
        self._write(repo / "file.txt", "content\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--quiet", "-m", "initial"],
            check=True,
        )
        reporter = validator.Reporter()

        context = validator.git_revision_context(repo, reporter)

        self.assertEqual([], reporter.errors)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual("sha256", context.object_format)
        self.assertEqual(64, context.oid_length)
        self.assertEqual(64, len(context.head))


if __name__ == "__main__":
    unittest.main()
