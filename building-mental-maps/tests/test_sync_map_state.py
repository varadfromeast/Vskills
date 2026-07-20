#!/usr/bin/env python3
"""Focused tests for sync_map_state.py."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import sync_map_state as sync  # noqa: E402
import validation_receipt  # noqa: E402


class SyncMapStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.repo = root / "repo"
        self.map_dir = root / "vault" / "Project Map"
        self.repo.mkdir(parents=True)
        self.map_dir.mkdir(parents=True)
        self.git("init", "--quiet")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test User")
        self.write_repo("src/a.py", "print('a')\n")
        self.write_repo("src/generated/schema.py", "GENERATED = True\n")
        self.write_repo("config/app.toml", "name = 'test'\n")
        self.write_repo(".gitignore", "src/ignored.py\n")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "initial")
        self.coverage = self.map_dir / "Project Code Coverage.md"
        self.write_coverage(revision="initial")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repo), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def write_repo(self, relative: str, content: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_coverage(
        self,
        *,
        revision: str,
        include: tuple[str, ...] = ("src/**",),
        exclude: tuple[tuple[str, str], ...] = (
            ("src/generated/**", "generated from schema"),
            ("config/**", "deployment configuration is outside the code map"),
            (".gitignore", "repository metadata is outside the code map"),
            ("notes.txt", "local notes are outside the code map"),
        ),
        comment: str = "",
    ) -> None:
        include_lines = "\n".join(f"- `{pattern}`" for pattern in include)
        exclude_lines = "\n".join(
            f"- `{pattern}` -> {reason}" for pattern, reason in exclude
        )
        self.coverage.write_text(
            "---\n"
            "type: mental-map-coverage\n"
            "project: Project\n"
            f"revision: {revision}\n"
            "---\n\n"
            "# Project Code Coverage\n\n"
            f"{comment}"
            "Include:\n"
            f"{include_lines}\n\n"
            "Exclude:\n"
            f"{exclude_lines}\n",
            encoding="utf-8",
        )

    def status(self) -> dict:
        return sync.build_status(self.repo, self.map_dir, self.coverage.name)

    def write_validation_receipt(self, status: dict | None = None) -> Path:
        report = status or self.status()
        return validation_receipt.write_receipt(
            self.map_dir,
            SCRIPT_DIR,
            target_fingerprint=report["targetFingerprint"],
            coverage_contract_sha256=report["target"]["coverage"][
                "contractSha256"
            ],
            changed_paths=report["changedPaths"]["all"],
            status_context=validation_receipt.status_context_from_report(report),
        )

    def checkpoint(self, fingerprint: str) -> dict:
        self.write_validation_receipt()
        return sync.checkpoint(
            self.repo,
            self.map_dir,
            self.coverage.name,
            require_fingerprint=fingerprint,
        )

    def test_checkpoint_requires_an_exact_validation_receipt(self) -> None:
        status = self.status()
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME

        with self.assertRaisesRegex(
            sync.SyncStateError, "validation receipt does not exist"
        ):
            sync.checkpoint(
                self.repo,
                self.map_dir,
                self.coverage.name,
                require_fingerprint=status["targetFingerprint"],
            )

        self.assertFalse(state_path.exists())

    def test_relative_receipt_path_is_map_relative_for_checkpoint(self) -> None:
        status = self.status()
        relative = Path("receipts/exact.json")
        validation_receipt.write_receipt(
            self.map_dir,
            SCRIPT_DIR,
            target_fingerprint=status["targetFingerprint"],
            coverage_contract_sha256=status["target"]["coverage"][
                "contractSha256"
            ],
            changed_paths=status["changedPaths"]["all"],
            status_context=validation_receipt.status_context_from_report(status),
            receipt_path=self.map_dir / relative,
        )

        result = sync.checkpoint(
            self.repo,
            self.map_dir,
            self.coverage.name,
            receipt_value=relative,
            require_fingerprint=status["targetFingerprint"],
        )

        self.assertEqual(
            str((self.map_dir / relative).resolve()), result["validationReceipt"]
        )

    def test_sidecars_are_json_files_inside_map_and_cannot_collide(self) -> None:
        status = self.status()
        atlas = self.map_dir / "Project Atlas.md"
        atlas.write_text("# Do not overwrite\n", encoding="utf-8")
        original = atlas.read_bytes()

        with self.assertRaisesRegex(
            validation_receipt.ValidationReceiptError,
            "validation receipt must use one of these suffixes",
        ):
            validation_receipt.write_receipt(
                self.map_dir,
                SCRIPT_DIR,
                target_fingerprint=status["targetFingerprint"],
                coverage_contract_sha256=status["target"]["coverage"][
                    "contractSha256"
                ],
                changed_paths=status["changedPaths"]["all"],
                status_context=validation_receipt.status_context_from_report(status),
                receipt_path=atlas,
            )
        self.assertEqual(original, atlas.read_bytes())

        with self.assertRaisesRegex(
            validation_receipt.ValidationReceiptError,
            "validation receipt must stay inside the map directory",
        ):
            validation_receipt.write_receipt(
                self.map_dir,
                SCRIPT_DIR,
                target_fingerprint=status["targetFingerprint"],
                coverage_contract_sha256=status["target"]["coverage"][
                    "contractSha256"
                ],
                changed_paths=status["changedPaths"]["all"],
                status_context=validation_receipt.status_context_from_report(status),
                receipt_path=self.repo / "receipt.json",
            )

        collision = self.map_dir / "same.json"
        validation_receipt.write_receipt(
            self.map_dir,
            SCRIPT_DIR,
            target_fingerprint=status["targetFingerprint"],
            coverage_contract_sha256=status["target"]["coverage"][
                "contractSha256"
            ],
            changed_paths=status["changedPaths"]["all"],
            status_context=validation_receipt.status_context_from_report(status),
            receipt_path=collision,
        )
        before = collision.read_bytes()
        with self.assertRaisesRegex(
            sync.SyncStateError, "collides with another map control file"
        ):
            sync.checkpoint(
                self.repo,
                self.map_dir,
                self.coverage.name,
                state_value=collision,
                receipt_value=collision,
                require_fingerprint=status["targetFingerprint"],
            )
        self.assertEqual(before, collision.read_bytes())

    def test_coverage_path_cannot_escape_map_directory(self) -> None:
        outside = Path(self.temporary.name) / "Outside Coverage.md"
        outside.write_text(self.coverage.read_text(encoding="utf-8"), encoding="utf-8")

        with self.assertRaisesRegex(
            sync.SyncStateError, "coverage note must stay inside the map directory"
        ):
            sync.build_status(self.repo, self.map_dir, outside)

    def test_stale_map_receipt_leaves_checkpoint_byte_identical(self) -> None:
        atlas = self.map_dir / "Project Atlas.md"
        atlas.write_text("# Project Atlas\n", encoding="utf-8")
        initial = self.status()
        self.write_validation_receipt(initial)
        sync.checkpoint(
            self.repo,
            self.map_dir,
            self.coverage.name,
            require_fingerprint=initial["targetFingerprint"],
        )
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME
        original = state_path.read_bytes()
        self.write_validation_receipt(self.status())
        atlas.write_text("# Project Atlas\n\nChanged after validation.\n", encoding="utf-8")
        current = self.status()
        self.assertEqual(initial["targetFingerprint"], current["targetFingerprint"])

        with self.assertRaisesRegex(sync.SyncStateError, "mapDigest"):
            sync.checkpoint(
                self.repo,
                self.map_dir,
                self.coverage.name,
                require_fingerprint=current["targetFingerprint"],
            )

        self.assertEqual(original, state_path.read_bytes())

    def test_stale_target_receipt_leaves_checkpoint_byte_identical(self) -> None:
        initial = self.status()
        self.write_validation_receipt(initial)
        sync.checkpoint(
            self.repo,
            self.map_dir,
            self.coverage.name,
            require_fingerprint=initial["targetFingerprint"],
        )
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME
        original = state_path.read_bytes()
        self.write_repo("src/a.py", "print('changed after validation')\n")
        current = self.status()

        with self.assertRaisesRegex(sync.SyncStateError, "targetFingerprint"):
            sync.checkpoint(
                self.repo,
                self.map_dir,
                self.coverage.name,
                require_fingerprint=current["targetFingerprint"],
            )

        self.assertEqual(original, state_path.read_bytes())

    def test_stale_validation_contract_receipt_cannot_create_state(self) -> None:
        status = self.status()
        self.write_validation_receipt(status)
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME

        with mock.patch.object(
            validation_receipt,
            "validation_contract_digest",
            return_value="sha256:" + "0" * 64,
        ):
            with self.assertRaisesRegex(sync.SyncStateError, "validationContractDigest"):
                sync.checkpoint(
                    self.repo,
                    self.map_dir,
                    self.coverage.name,
                    require_fingerprint=status["targetFingerprint"],
                )

        self.assertFalse(state_path.exists())

    def test_validation_contract_digest_rejects_missing_script(self) -> None:
        incomplete = Path(self.temporary.name) / "incomplete-validator"
        incomplete.mkdir()
        (incomplete / "sync_map_state.py").write_text("# present\n", encoding="utf-8")

        with self.assertRaisesRegex(
            validation_receipt.ValidationReceiptError,
            "validation contract file is missing",
        ):
            validation_receipt.validation_contract_digest(incomplete)

    def test_validation_contract_digest_binds_skill_and_reference_docs(self) -> None:
        skill = Path(self.temporary.name) / "contract-skill"
        scripts = skill / "scripts"
        references = skill / "references"
        scripts.mkdir(parents=True)
        references.mkdir()
        for name in validation_receipt.SCRIPT_CONTRACT_FILES:
            (scripts / name).write_text(f"# {name}\n", encoding="utf-8")
        (skill / "SKILL.md").write_text("# Contract\n", encoding="utf-8")
        reference = references / "MODEL.md"
        reference.write_text("v1\n", encoding="utf-8")
        before = validation_receipt.validation_contract_digest(scripts)

        reference.write_text("v2\n", encoding="utf-8")
        after = validation_receipt.validation_contract_digest(scripts)

        self.assertNotEqual(before, after)

    def test_stale_coverage_contract_receipt_cannot_create_state(self) -> None:
        initial = self.status()
        self.write_validation_receipt(initial)
        self.write_coverage(
            revision="changed-scope",
            include=("src/**", "config/**"),
            exclude=(
                ("src/generated/**", "generated from schema"),
                (".gitignore", "repository metadata is outside the code map"),
                ("notes.txt", "local notes are outside the code map"),
            ),
        )
        current = self.status()
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME

        with self.assertRaisesRegex(sync.SyncStateError, "targetFingerprint"):
            sync.checkpoint(
                self.repo,
                self.map_dir,
                self.coverage.name,
                require_fingerprint=current["targetFingerprint"],
            )

        self.assertFalse(state_path.exists())

    def test_atomic_write_survives_unsupported_directory_fsync(self) -> None:
        destination = self.map_dir / "portable.json"
        original_open = validation_receipt.os.open

        def reject_directory(path: object, flags: int, mode: int = 0o777) -> int:
            if Path(path) == destination.parent:
                raise PermissionError("directory handles unsupported")
            return original_open(path, flags, mode)

        with mock.patch.object(
            validation_receipt.os, "open", side_effect=reject_directory
        ):
            validation_receipt.atomic_write_json(destination, {"ok": True})

        self.assertEqual(
            {"ok": True}, json.loads(destination.read_text(encoding="utf-8"))
        )

    def test_status_is_read_only_and_checkpoint_is_deterministic(self) -> None:
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME
        first = self.status()

        self.assertFalse(state_path.exists())
        self.assertFalse(first["trusted"])
        self.assertIn("state-missing", first["fallbackReasons"])
        self.assertEqual(["src/a.py"], first["changedPaths"]["added"])
        self.assertEqual(self.git("rev-parse", "HEAD"), first["target"]["head"])
        self.assertEqual(
            self.git("rev-parse", "HEAD^{tree}"), first["target"]["tree"]
        )
        content_digest = "sha256:" + hashlib.sha256(b"print('a')\n").hexdigest()
        expected_digest = "sha256:" + hashlib.sha256(
            json.dumps(
                {
                    "contentSha256": content_digest,
                    "executableBits": 0,
                    "kind": "file",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(expected_digest, first["target"]["files"]["src/a.py"])
        self.assertNotIn("src/generated/schema.py", first["target"]["files"])

        self.checkpoint(first["targetFingerprint"])
        original_bytes = state_path.read_bytes()
        second = self.status()
        self.assertTrue(second["trusted"])
        self.assertEqual([], second["changedPaths"]["all"])
        self.assertEqual(first["targetFingerprint"], second["targetFingerprint"])

        self.checkpoint(second["targetFingerprint"])
        self.assertEqual(original_bytes, state_path.read_bytes())
    def test_checkpoint_api_requires_an_inspected_fingerprint(self) -> None:
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME

        with self.assertRaises(TypeError):
            sync.checkpoint(self.repo, self.map_dir, self.coverage.name)  # type: ignore[call-arg]

        self.assertFalse(state_path.exists())

    def test_checkpoint_cli_requires_an_inspected_fingerprint(self) -> None:
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "sync_map_state.py"),
                "checkpoint",
                "--repo",
                str(self.repo),
                "--map-dir",
                str(self.map_dir),
                "--coverage",
                self.coverage.name,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("--require-fingerprint", result.stderr)
        self.assertFalse(state_path.exists())

    def test_dirty_and_untracked_changes_are_reported_and_guarded(self) -> None:
        initial = self.status()
        self.checkpoint(initial["targetFingerprint"])
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME
        original_state = state_path.read_bytes()

        self.write_repo("src/a.py", "print('changed')\n")
        self.write_repo("src/new.py", "NEW = True\n")
        self.write_repo("src/ignored.py", "IGNORED = True\n")
        self.write_repo("notes.txt", "out of scope but non-ignored\n")
        dirty = self.status()

        self.assertTrue(dirty["trusted"])
        self.assertTrue(dirty["target"]["workingTree"]["dirty"])
        self.assertEqual(["src/new.py"], dirty["changedPaths"]["added"])
        self.assertEqual(["src/a.py"], dirty["changedPaths"]["modified"])
        self.assertNotIn("src/ignored.py", dirty["target"]["files"])
        self.assertNotIn("notes.txt", dirty["changedPaths"]["all"])

        with self.assertRaises(sync.FingerprintMismatch):
            self.checkpoint(initial["targetFingerprint"])
        self.assertEqual(original_state, state_path.read_bytes())

        self.checkpoint(dirty["targetFingerprint"])
        self.assertEqual([], self.status()["changedPaths"]["all"])

    def test_staged_index_only_change_changes_working_tree_fingerprint(self) -> None:
        initial = self.status()
        self.checkpoint(initial["targetFingerprint"])
        original = (self.repo / "src/a.py").read_text(encoding="utf-8")
        self.write_repo("src/a.py", "print('staged only')\n")
        self.git("add", "src/a.py")
        self.write_repo("src/a.py", original)

        staged_only = self.status()

        self.assertTrue(staged_only["target"]["workingTree"]["dirty"])
        self.assertNotEqual(
            initial["target"]["workingTree"]["fingerprint"],
            staged_only["target"]["workingTree"]["fingerprint"],
        )
        self.assertNotEqual(
            initial["targetFingerprint"], staged_only["targetFingerprint"]
        )

    def test_checkpoint_rejects_replayed_receipt_from_different_baseline(self) -> None:
        initial = self.status()
        self.checkpoint(initial["targetFingerprint"])
        self.write_repo("src/a.py", "print('target b')\n")
        target_b = self.status()
        self.write_validation_receipt(target_b)

        self.write_repo("src/a.py", "print('baseline c')\n")
        target_c, _fallbacks = sync.capture_target(
            self.repo,
            self.map_dir,
            self.coverage.name,
            self.map_dir / sync.DEFAULT_STATE_NAME,
        )
        sync.atomic_write_json(self.map_dir / sync.DEFAULT_STATE_NAME, target_c)
        self.write_repo("src/a.py", "print('target b')\n")
        replay = self.status()
        self.assertEqual(
            target_b["targetFingerprint"], replay["targetFingerprint"]
        )
        self.assertEqual(
            target_b["changedPaths"]["all"], replay["changedPaths"]["all"]
        )

        with self.assertRaisesRegex(sync.SyncStateError, "statusContext"):
            sync.checkpoint(
                self.repo,
                self.map_dir,
                self.coverage.name,
                require_fingerprint=replay["targetFingerprint"],
            )

    def test_checkpoint_recaptures_target_after_first_receipt_verification(self) -> None:
        status = self.status()
        self.write_validation_receipt(status)
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME
        original_verify = sync.verify_status_receipt
        calls = 0

        def mutate_after_verify(*args: object, **kwargs: object) -> None:
            nonlocal calls
            original_verify(*args, **kwargs)
            calls += 1
            if calls == 1:
                self.write_repo("src/a.py", "print('raced')\n")

        with mock.patch.object(
            sync, "verify_status_receipt", side_effect=mutate_after_verify
        ):
            with self.assertRaises(sync.FingerprintMismatch):
                sync.checkpoint(
                    self.repo,
                    self.map_dir,
                    self.coverage.name,
                    require_fingerprint=status["targetFingerprint"],
                )

        self.assertFalse(state_path.exists())

    def test_unclassified_inventory_path_is_rejected(self) -> None:
        self.write_coverage(
            revision="narrow",
            exclude=(("src/generated/**", "generated from schema"),),
        )

        with self.assertRaisesRegex(
            sync.SyncStateError, "repository files unclassified"
        ):
            self.status()

    def test_map_directory_inside_repository_is_rejected(self) -> None:
        inside_map = self.repo / "docs" / "Project Map"
        inside_map.mkdir(parents=True)
        coverage = inside_map / "Project Code Coverage.md"
        coverage.write_text(
            "---\n"
            "type: mental-map-coverage\n"
            "project: Project\n"
            "revision: current\n"
            "---\n\n"
            "Include:\n- `**`\n\nExclude:\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            sync.SyncStateError, "must not overlap"
        ):
            sync.build_status(self.repo, inside_map, coverage.name)

    def test_auto_detected_coverage_symlink_cannot_escape_map(self) -> None:
        external = self.map_dir.parent / "External Coverage.md"
        external.write_bytes(self.coverage.read_bytes())
        self.coverage.unlink()
        self.coverage.symlink_to(external)

        with self.assertRaisesRegex(sync.SyncStateError, "must stay inside"):
            sync.build_status(self.repo, self.map_dir)

    def test_assume_unchanged_index_flag_fails_closed(self) -> None:
        self.git("update-index", "--assume-unchanged", "config/app.toml")
        self.write_repo("config/app.toml", "name = 'silently changed'\n")

        with self.assertRaisesRegex(sync.SyncStateError, "assume-unchanged"):
            self.status()

    def test_unborn_repo_fingerprint_binds_excluded_file_content(self) -> None:
        root = Path(self.temporary.name)
        unborn_repo = root / "unborn-repo"
        unborn_map = root / "unborn-vault/Map"
        unborn_repo.mkdir()
        unborn_map.mkdir(parents=True)
        subprocess.run(["git", "-C", str(unborn_repo), "init", "--quiet"], check=True)
        (unborn_repo / "src").mkdir()
        (unborn_repo / "config").mkdir()
        (unborn_repo / "src/app.py").write_text("print('app')\n", encoding="utf-8")
        excluded = unborn_repo / "config/app.toml"
        excluded.write_text("name = 'one'\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(unborn_repo), "add", "src/app.py", "config/app.toml"],
            check=True,
        )
        coverage = unborn_map / "Coverage.md"
        coverage.write_text(
            "---\ntype: mental-map-coverage\nproject: Demo\nrevision: unborn\n---\n\n"
            "Include:\n- `src/**`\n\n"
            "Exclude:\n- `config/**` -> outside map\n",
            encoding="utf-8",
        )

        before = sync.build_status(unborn_repo, unborn_map, coverage.name)
        excluded.write_text("name = 'two'\n", encoding="utf-8")
        after = sync.build_status(unborn_repo, unborn_map, coverage.name)

        self.assertNotEqual(before["targetFingerprint"], after["targetFingerprint"])

    def test_coverage_contract_hash_ignores_revision_and_formatting(self) -> None:
        first = self.status()
        self.checkpoint(first["targetFingerprint"])
        first_contract = first["target"]["coverage"]["contractSha256"]
        first_note = first["target"]["coverage"]["noteSha256"]

        self.write_coverage(
            revision="later",
            comment="<!-- formatting-only comment -->\n\n",
        )
        formatting_only = self.status()
        self.assertTrue(formatting_only["trusted"])
        self.assertEqual(
            first_contract,
            formatting_only["target"]["coverage"]["contractSha256"],
        )
        self.assertNotEqual(
            first_note, formatting_only["target"]["coverage"]["noteSha256"]
        )
        self.assertNotEqual(
            first["targetFingerprint"], formatting_only["targetFingerprint"]
        )

        self.write_coverage(
            revision="later",
            include=("src/**", "config/**"),
            exclude=(
                ("src/generated/**", "generated from schema"),
                (".gitignore", "repository metadata is outside the code map"),
                ("notes.txt", "local notes are outside the code map"),
            ),
        )
        changed_contract = self.status()
        self.assertFalse(changed_contract["trusted"])
        self.assertIn("coverage-contract-changed", changed_contract["fallbackReasons"])
        self.assertIn("config/app.toml", changed_contract["changedPaths"]["added"])

    def test_invalid_state_fails_closed_without_losing_target(self) -> None:
        state_path = self.map_dir / sync.DEFAULT_STATE_NAME
        state_path.write_text("{not json", encoding="utf-8")

        report = self.status()

        self.assertFalse(report["trusted"])
        self.assertFalse(report["comparisonAvailable"])
        self.assertIn("state-invalid-json", report["fallbackReasons"])
        self.assertRegex(report["targetFingerprint"], sync.SHA256_RE)

    def test_state_path_outside_map_directory_is_rejected_before_creation(self) -> None:
        state_path = self.repo / "src" / "future-state.json"
        self.assertFalse(state_path.exists())

        with self.assertRaisesRegex(
            sync.SyncStateError, "sync state must stay inside the map directory"
        ):
            sync.build_status(
                self.repo,
                self.map_dir,
                self.coverage.name,
                state_value=state_path,
            )
        with self.assertRaisesRegex(
            sync.SyncStateError, "sync state must stay inside the map directory"
        ):
            sync.checkpoint(
                self.repo,
                self.map_dir,
                self.coverage.name,
                state_value=state_path,
                require_fingerprint="sha256:" + "0" * 64,
            )

        self.assertFalse(state_path.exists())

    @unittest.skipIf(os.name == "nt", "executable mode bits are not portable on Windows")
    def test_committed_chmod_is_reported_as_a_modified_path(self) -> None:
        initial = self.status()
        self.checkpoint(initial["targetFingerprint"])
        source = self.repo / "src" / "a.py"
        source.chmod(stat.S_IMODE(source.stat().st_mode) | stat.S_IXUSR)
        self.git("add", "src/a.py")
        self.git("commit", "--quiet", "-m", "make executable")

        changed = self.status()

        self.assertEqual(["src/a.py"], changed["changedPaths"]["modified"])
        self.assertFalse(changed["target"]["workingTree"]["dirty"])
        self.assertNotEqual(
            initial["target"]["files"]["src/a.py"],
            changed["target"]["files"]["src/a.py"],
        )


if __name__ == "__main__":
    unittest.main()
