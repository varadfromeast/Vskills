#!/usr/bin/env python3
"""Regression tests for scaffold_mental_map.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import scaffold_mental_map as scaffold  # noqa: E402


class ScaffoldMentalMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.vault = self.root / "vault"
        self.map_dir = self.vault / "Teams/Platform/Architecture/Demo Map"
        self.repo.mkdir()
        self.vault.mkdir()
        (self.vault / ".obsidian").mkdir()
        self.git("init", "--quiet")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test User")
        self.write_repo("src/app.py", "def run():\n    return True\n")
        self.write_repo("tests/test_app.py", "def test_run():\n    assert True\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "initial")

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

    def write_repo(self, relative: str, content: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def create(self) -> dict[str, object]:
        return scaffold.scaffold(
            repo_value=str(self.repo),
            vault_value=str(self.vault),
            map_dir_value=str(self.map_dir),
            project_value="Demo",
            includes=["src/**", "tests/**"],
            excludes=["tests/**=user requested tests outside this atlas boundary"],
        )

    def test_creates_nested_draft_without_checkpoint_or_receipt(self) -> None:
        result = self.create()

        self.assertTrue(result["created"])
        self.assertTrue(result["draft"])
        self.assertEqual(self.git("rev-parse", "HEAD"), result["revision"])
        self.assertEqual("HEAD", result["mappedTarget"])
        for directory in ("Blocks", "Views", "Flows"):
            self.assertTrue((self.map_dir / directory).is_dir())
        for filename in (
            "Demo Atlas.md",
            "Demo Atlas.canvas",
            "Views/Demo All Relationships.canvas",
            "Demo Blocks.base",
            "Demo Code Coverage.md",
        ):
            self.assertTrue((self.map_dir / filename).is_file())
        canvas = json.loads(
            (self.map_dir / "Demo Atlas.canvas").read_text(encoding="utf-8")
        )
        self.assertEqual({"edges": [], "nodes": []}, canvas)
        relationships_canvas = json.loads(
            (
                self.map_dir / "Views/Demo All Relationships.canvas"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual({"edges": [], "nodes": []}, relationships_canvas)
        coverage = (self.map_dir / "Demo Code Coverage.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("- `tests/**` -> user requested tests outside", coverage)
        atlas = (self.map_dir / "Demo Atlas.md").read_text(encoding="utf-8")
        self.assertNotIn("DRAFT", atlas)
        self.assertIn("Mapped target: HEAD", atlas)
        for field in (
            "Purpose:",
            "Domain boundary:",
            "Quality priorities:",
            "Current risks:",
            "Coverage summary:",
            "Unresolved questions:",
            "sync-state: .mental-map-state.json",
            "relationships-canvas: \"Views/Demo All Relationships.canvas\"",
        ):
            self.assertIn(field, atlas)
        self.assertIn(
            "[[Teams/Platform/Architecture/Demo Map/Demo Atlas.canvas]]",
            atlas,
        )
        self.assertIn(
            "[[Teams/Platform/Architecture/Demo Map/Demo Blocks.base]]",
            atlas,
        )
        self.assertIn(
            "[[Teams/Platform/Architecture/Demo Map/Views/Demo All Relationships.canvas]]",
            atlas,
        )
        self.assertIn(
            "![[Teams/Platform/Architecture/Demo Map/Demo Blocks.base#Needs review]]",
            atlas,
        )
        self.assertIn(
            "[[Teams/Platform/Architecture/Demo Map/Demo Code Coverage.md]]",
            atlas,
        )
        self.assertIn("## Entry-point families", atlas)
        self.assertIn(
            "| Family | Representative anchor | Focused view | No-view reason |",
            atlas,
        )
        self.assertIn("TODO: name a public or runnable family", atlas)
        self.assertIn("## Canvas semantic groups", atlas)
        self.assertIn(
            "| Group | Scope key | Question | Members |",
            atlas,
        )
        self.assertIn("TODO: name one coherent architectural scope", atlas)
        base = (self.map_dir / "Demo Blocks.base").read_text(encoding="utf-8")
        self.assertIn("name: Needs review", base)
        self.assertIn(
            "'note[\"reviewed-revision\"] != this.revision'", base
        )
        self.assertFalse((self.map_dir / ".mental-map-state.json").exists())
        self.assertFalse((self.map_dir / ".mental-map-validation.json").exists())

    def test_discloses_dirty_checkout_in_atlas(self) -> None:
        self.write_repo("src/app.py", "def run():\n    return False\n")
        self.write_repo("src/new.py", "NEW = True\n")

        result = self.create()

        self.assertEqual("HEAD + dirty paths", result["mappedTarget"])
        atlas = (self.map_dir / "Demo Atlas.md").read_text(encoding="utf-8")
        self.assertIn("Mapped target: HEAD + dirty paths", atlas)

    def test_escapes_apostrophe_in_base_filter(self) -> None:
        self.map_dir = self.vault / "O'Reilly Map"

        scaffold.scaffold(
            repo_value=str(self.repo),
            vault_value=str(self.vault),
            map_dir_value=str(self.map_dir),
            project_value="O'Reilly",
            includes=["src/**", "tests/**"],
            excludes=["tests/**=not mapped"],
        )

        base = (self.map_dir / "O'Reilly Blocks.base").read_text(encoding="utf-8")
        self.assertIn("- 'project == \"O''Reilly\"'", base)

    def test_rejects_unclassified_repository_files(self) -> None:
        with self.assertRaisesRegex(scaffold.ScaffoldError, "unclassified"):
            scaffold.scaffold(
                repo_value=str(self.repo),
                vault_value=str(self.vault),
                map_dir_value=str(self.map_dir),
                project_value="Demo",
                includes=["src/**"],
                excludes=[],
            )

        self.assertFalse(self.map_dir.exists())

    def test_rejects_map_directory_inside_repository(self) -> None:
        repo_vault = self.repo / "vault"
        (repo_vault / ".obsidian").mkdir(parents=True)
        repo_map = repo_vault / "Demo Map"

        with self.assertRaisesRegex(scaffold.ScaffoldError, "must not overlap"):
            scaffold.scaffold(
                repo_value=str(self.repo),
                vault_value=str(repo_vault),
                map_dir_value=str(repo_map),
                project_value="Demo",
                includes=["src/**", "tests/**"],
                excludes=["tests/**=not mapped"],
            )

        self.assertFalse(repo_map.exists())

    def test_rejects_repository_inside_map_directory(self) -> None:
        containing_vault = self.root / "containing-vault"
        containing_vault.mkdir()
        (containing_vault / ".obsidian").mkdir()
        nested_repo = containing_vault / "Future Map/repo"
        nested_repo.mkdir(parents=True)
        subprocess.run(["git", "-C", str(nested_repo), "init", "--quiet"], check=True)
        subprocess.run(
            ["git", "-C", str(nested_repo), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(nested_repo), "config", "user.name", "Test User"],
            check=True,
        )
        source = nested_repo / "src/app.py"
        source.parent.mkdir()
        source.write_text("print('demo')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(nested_repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(nested_repo), "commit", "--quiet", "-m", "initial"],
            check=True,
        )

        with self.assertRaisesRegex(scaffold.ScaffoldError, "must not overlap"):
            scaffold.scaffold(
                repo_value=str(nested_repo),
                vault_value=str(containing_vault),
                map_dir_value=str(containing_vault / "Future Map"),
                project_value="Demo",
                includes=["src/**"],
                excludes=[],
            )

    def test_rejects_unsafe_project_filename_components(self) -> None:
        for project in (" Demo", "Demo.", "Demo: Map", "Demo#Map", "Demo%%Map"):
            with self.subTest(project=project):
                with self.assertRaises(scaffold.ScaffoldError):
                    scaffold.scaffold(
                        repo_value=str(self.repo),
                        vault_value=str(self.vault),
                        map_dir_value=str(self.map_dir),
                        project_value=project,
                        includes=["src/**", "tests/**"],
                        excludes=["tests/**=not mapped"],
                    )

    def test_refuses_existing_destination_without_modifying_it(self) -> None:
        self.create()
        atlas = self.map_dir / "Demo Atlas.md"
        original = atlas.read_bytes()

        with self.assertRaisesRegex(scaffold.ScaffoldError, "refusing to overwrite"):
            self.create()

        self.assertEqual(original, atlas.read_bytes())

    def test_rejects_map_directory_outside_vault(self) -> None:
        with self.assertRaisesRegex(scaffold.ScaffoldError, "inside --vault"):
            scaffold.scaffold(
                repo_value=str(self.repo),
                vault_value=str(self.vault),
                map_dir_value=str(self.root / "outside/Demo Map"),
                project_value="Demo",
                includes=["src/**"],
                excludes=[],
            )

    def test_rejects_parent_of_actual_obsidian_vault(self) -> None:
        (self.vault / ".obsidian").rmdir()
        actual_vault = self.vault / "Actual Vault"
        (actual_vault / ".obsidian").mkdir(parents=True)

        with self.assertRaisesRegex(scaffold.ScaffoldError, "contain .obsidian"):
            self.create()

        self.assertFalse(self.map_dir.exists())

    def test_requires_reasoned_exclusions(self) -> None:
        with self.assertRaisesRegex(scaffold.ScaffoldError, "PATTERN=REASON"):
            scaffold.scaffold(
                repo_value=str(self.repo),
                vault_value=str(self.vault),
                map_dir_value=str(self.map_dir),
                project_value="Demo",
                includes=["src/**"],
                excludes=["tests/**"],
            )


if __name__ == "__main__":
    unittest.main()
