#!/usr/bin/env python3
"""Create and verify deterministic mental-map validation receipts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


RECEIPT_SCHEMA = 2
DEFAULT_RECEIPT_NAME = ".mental-map-validation.json"
DEFAULT_SYNC_STATE_NAME = ".mental-map-state.json"
MAP_ARTIFACT_SUFFIXES = {".md", ".canvas", ".base"}
SCRIPT_CONTRACT_FILES = (
    "sync_map_state.py",
    "validate_mental_map.py",
    "validation_receipt.py",
)


class ValidationReceiptError(RuntimeError):
    """A validation receipt is absent, malformed, or stale."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def prefixed_sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def artifact_manifest(map_dir: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(map_dir.rglob("*")):
        if not path.is_file() or path.suffix not in MAP_ARTIFACT_SUFFIXES:
            continue
        relative = path.relative_to(map_dir).as_posix()
        manifest[relative] = prefixed_sha256(path.read_bytes())
    return manifest


def map_digest(map_dir: Path) -> str:
    return prefixed_sha256(canonical_bytes(artifact_manifest(map_dir)))


def resolve_map_path(
    map_dir: Path,
    value: str | Path | None,
    *,
    default_name: str | None,
    label: str,
    allowed_suffixes: set[str] | None = None,
    require_file: bool = False,
    forbidden_paths: tuple[Path, ...] = (),
) -> Path:
    """Resolve a user-supplied map path without permitting map-directory escape."""

    root = map_dir.expanduser().resolve()
    if value is None:
        if default_name is None:
            raise ValidationReceiptError(f"{label} path is required")
        candidate = Path(default_name)
    else:
        candidate = Path(value).expanduser()
    destination = (
        candidate.resolve()
        if candidate.is_absolute()
        else (root / candidate).resolve()
    )
    try:
        destination.relative_to(root)
    except ValueError as error:
        raise ValidationReceiptError(
            f"{label} must stay inside the map directory: {destination}"
        ) from error

    suffix = destination.suffix.casefold()
    if allowed_suffixes is not None and suffix not in {
        item.casefold() for item in allowed_suffixes
    }:
        expected = ", ".join(sorted(allowed_suffixes))
        raise ValidationReceiptError(
            f"{label} must use one of these suffixes: {expected}"
        )
    if suffix in MAP_ARTIFACT_SUFFIXES and allowed_suffixes == {".json"}:
        raise ValidationReceiptError(
            f"{label} cannot overwrite a mental-map artifact: {destination.name}"
        )
    forbidden = {path.expanduser().resolve() for path in forbidden_paths}
    if destination in forbidden:
        raise ValidationReceiptError(
            f"{label} collides with another map control file: {destination.name}"
        )
    if require_file and not destination.is_file():
        raise ValidationReceiptError(f"{label} does not exist: {destination}")
    return destination


def resolve_sidecar_path(
    map_dir: Path,
    value: str | Path | None,
    *,
    default_name: str,
    label: str,
    forbidden_paths: tuple[Path, ...] = (),
) -> Path:
    return resolve_map_path(
        map_dir,
        value,
        default_name=default_name,
        label=label,
        allowed_suffixes={".json"},
        forbidden_paths=forbidden_paths,
    )


def validation_contract_digest(script_dir: Path) -> str:
    script_dir = script_dir.expanduser().resolve()
    skill_dir = script_dir.parent
    manifest: dict[str, str] = {}
    for name in SCRIPT_CONTRACT_FILES:
        path = script_dir / name
        if not path.is_file():
            raise ValidationReceiptError(f"validation contract file is missing: {path}")
        manifest[f"scripts/{name}"] = prefixed_sha256(path.read_bytes())
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.is_file():
        raise ValidationReceiptError(
            f"validation contract file is missing: {skill_path}"
        )
    manifest["SKILL.md"] = prefixed_sha256(skill_path.read_bytes())
    references = sorted((skill_dir / "references").glob("*.md"))
    if not references:
        raise ValidationReceiptError(
            f"validation contract references are missing: {skill_dir / 'references'}"
        )
    for path in references:
        manifest[path.relative_to(skill_dir).as_posix()] = prefixed_sha256(
            path.read_bytes()
        )
    return prefixed_sha256(canonical_bytes(manifest))


def status_context_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Extract the baseline and trust facts that make a delta meaningful."""

    baseline = report.get("baseline")
    baseline_fingerprint = (
        baseline.get("targetFingerprint") if isinstance(baseline, dict) else None
    )
    fallbacks = report.get("fallbackReasons")
    if not isinstance(fallbacks, list) or not all(
        isinstance(item, str) for item in fallbacks
    ):
        raise ValidationReceiptError("sync status omitted fallback reasons")
    trusted = report.get("trusted")
    comparison_available = report.get("comparisonAvailable")
    if not isinstance(trusted, bool) or not isinstance(comparison_available, bool):
        raise ValidationReceiptError("sync status omitted trust context")
    if baseline_fingerprint is not None and not isinstance(
        baseline_fingerprint, str
    ):
        raise ValidationReceiptError("sync status has an invalid baseline fingerprint")
    return {
        "baselineTargetFingerprint": baseline_fingerprint,
        "trusted": trusted,
        "comparisonAvailable": comparison_available,
        "fallbackReasons": sorted(set(fallbacks)),
    }


def fsync_parent_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(path.parent, flags)
        os.fsync(descriptor)
    except OSError:
        # Atomic replacement is still valid where directory fsync is unsupported.
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(
        value,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    previous_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as stream:
            temporary_name = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_name, previous_mode)
        os.replace(temporary_name, path)
        temporary_name = None
        fsync_parent_directory(path)
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def build_receipt(
    map_dir: Path,
    script_dir: Path,
    *,
    target_fingerprint: str,
    coverage_contract_sha256: str,
    changed_paths: list[str],
    status_context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": RECEIPT_SCHEMA,
        "targetFingerprint": target_fingerprint,
        "coverageContractSha256": coverage_contract_sha256,
        "changedPaths": sorted(changed_paths),
        "statusContext": status_context,
        "mapDigest": map_digest(map_dir),
        "validationContractDigest": validation_contract_digest(script_dir),
    }


def write_receipt(
    map_dir: Path,
    script_dir: Path,
    *,
    target_fingerprint: str,
    coverage_contract_sha256: str,
    changed_paths: list[str],
    status_context: dict[str, Any],
    receipt_path: Path | None = None,
    forbidden_paths: tuple[Path, ...] = (),
) -> Path:
    destination = resolve_sidecar_path(
        map_dir,
        receipt_path,
        default_name=DEFAULT_RECEIPT_NAME,
        label="validation receipt",
        forbidden_paths=(
            *forbidden_paths,
            map_dir / DEFAULT_SYNC_STATE_NAME,
        ),
    )
    atomic_write_json(
        destination,
        build_receipt(
            map_dir,
            script_dir,
            target_fingerprint=target_fingerprint,
            coverage_contract_sha256=coverage_contract_sha256,
            changed_paths=changed_paths,
            status_context=status_context,
        ),
    )
    return destination


def verify_receipt(
    map_dir: Path,
    script_dir: Path,
    *,
    target_fingerprint: str,
    coverage_contract_sha256: str,
    changed_paths: list[str],
    status_context: dict[str, Any],
    receipt_path: Path | None = None,
    forbidden_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    source = resolve_sidecar_path(
        map_dir,
        receipt_path,
        default_name=DEFAULT_RECEIPT_NAME,
        label="validation receipt",
        forbidden_paths=(
            *forbidden_paths,
            map_dir / DEFAULT_SYNC_STATE_NAME,
        ),
    )
    if not source.is_file():
        raise ValidationReceiptError(f"validation receipt does not exist: {source}")
    try:
        receipt = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValidationReceiptError(f"validation receipt is invalid JSON: {source}") from error
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValidationReceiptError("validation receipt has an unsupported schema")

    expected = build_receipt(
        map_dir,
        script_dir,
        target_fingerprint=target_fingerprint,
        coverage_contract_sha256=coverage_contract_sha256,
        changed_paths=changed_paths,
        status_context=status_context,
    )
    for field, expected_value in expected.items():
        if receipt.get(field) != expected_value:
            raise ValidationReceiptError(
                f"validation receipt is stale: {field} does not match the current target"
            )
    return receipt
