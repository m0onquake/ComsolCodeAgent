"""Safe manifest discovery, validation, and trusted Python loading."""

from __future__ import annotations

import importlib
import json
import sys
from importlib.machinery import PathFinder
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from .errors import ExtensionValidationError
from .interfaces import Extension
from .models import (
    CandidateState,
    ExtensionCandidate,
    ExtensionManifest,
    ValidationIssue,
    ValidationResult,
)
from .policy import CompatibilityPolicy, PermissionPolicy

_MANIFEST_NAMES = frozenset(
    {"extension.yaml", "extension.yml", "extension.json", "manifest.yaml", "manifest.yml"}
)


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    return any(resolved.is_relative_to(root.resolve()) for root in roots)


class ExtensionLoader:
    """Discovers declarations without importing code, then loads only trusted entrypoints."""

    def __init__(
        self,
        *,
        compatibility: CompatibilityPolicy,
        permissions: PermissionPolicy,
        trusted_manifest_roots: tuple[Path, ...],
        trusted_code_roots: tuple[Path, ...],
    ) -> None:
        self.compatibility = compatibility
        self.permissions = permissions
        self.trusted_manifest_roots = tuple(path.resolve() for path in trusted_manifest_roots)
        self.trusted_code_roots = tuple(path.resolve() for path in trusted_code_roots)

    def discover(self, paths: list[Path]) -> list[ExtensionCandidate]:
        candidates: list[ExtensionCandidate] = []
        seen: set[Path] = set()
        for requested in paths:
            requested = requested.resolve()
            discovered = [requested] if requested.is_file() else sorted(requested.rglob("*"))
            for path in discovered:
                if path.name not in _MANIFEST_NAMES or path in seen:
                    continue
                seen.add(path)
                try:
                    raw = self._read(path)
                except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
                    raw = {"_discovery_error": f"{type(exc).__name__}: {exc}"}
                candidates.append(ExtensionCandidate(path=path, raw_manifest=raw))
        return candidates

    def validate(self, candidate: ExtensionCandidate) -> ValidationResult:
        issues: list[ValidationIssue] = []
        if not _inside(candidate.path, self.trusted_manifest_roots):
            issues.append(
                ValidationIssue(
                    code="untrusted_manifest_path",
                    location=str(candidate.path),
                    message="manifest is outside configured trusted roots",
                )
            )
        discovery_error = candidate.raw_manifest.get("_discovery_error")
        if discovery_error:
            issues.append(ValidationIssue(code="manifest_parse_error", message=discovery_error))
            return self._result(candidate, issues)
        try:
            manifest = ExtensionManifest.model_validate(candidate.raw_manifest)
            candidate.manifest = manifest
        except ValidationError as exc:
            issues.extend(
                ValidationIssue(
                    code="manifest_schema_error",
                    location=".".join(str(part) for part in error["loc"]),
                    message=error["msg"],
                )
                for error in exc.errors()
            )
            return self._result(candidate, issues)

        issues.extend(self.compatibility.issues(manifest))
        issues.extend(self.permissions.issues(manifest.permissions))
        issues.extend(self._validate_config(candidate.path, manifest))
        issues.extend(self._validate_entrypoint_origin(manifest.entrypoint))
        return self._result(candidate, issues)

    def load(self, candidate: ExtensionCandidate) -> Extension:
        result = self.validate(candidate)
        if not result.valid or candidate.manifest is None:
            raise ExtensionValidationError(result.issues)
        module_name, attribute = candidate.manifest.entrypoint.split(":", 1)
        expected_origin, issue = self._resolve_entrypoint_origin(module_name)
        if issue is not None or expected_origin is None:
            raise ExtensionValidationError([issue] if issue is not None else [])
        module = importlib.import_module(module_name)
        actual_origin = self._module_origin(module)
        if actual_origin != expected_origin or not _inside(
            actual_origin, self.trusted_code_roots
        ):
            raise ExtensionValidationError(
                [
                    ValidationIssue(
                        code="entrypoint_origin_changed",
                        location="entrypoint",
                        message=(
                            f"validated {expected_origin}, but import resolved to {actual_origin}"
                        ),
                    )
                ]
            )
        factory = getattr(module, attribute)
        extension = factory(manifest=candidate.manifest, config=candidate.manifest.config)
        return extension

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        value = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
        if not isinstance(value, dict):
            raise ValueError("manifest root must be an object")
        return value

    def _validate_config(
        self, manifest_path: Path, manifest: ExtensionManifest
    ) -> list[ValidationIssue]:
        schema = manifest.config_schema
        if schema is None:
            return []
        if isinstance(schema, str):
            schema_path = (manifest_path.parent / schema).resolve()
            if not schema_path.is_relative_to(manifest_path.parent.resolve()):
                return [
                    ValidationIssue(
                        code="untrusted_config_schema",
                        location="config_schema",
                        message="config schema escapes the manifest directory",
                    )
                ]
            try:
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return [
                    ValidationIssue(
                        code="config_schema_error",
                        location="config_schema",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                ]
        try:
            Draft202012Validator.check_schema(schema)
            errors = sorted(
                Draft202012Validator(schema).iter_errors(manifest.config),
                key=lambda error: list(error.path),
            )
        except Exception as exc:
            return [
                ValidationIssue(
                    code="config_schema_error", location="config_schema", message=str(exc)
                )
            ]
        return [
            ValidationIssue(
                code="invalid_config",
                location="config." + ".".join(str(part) for part in error.path),
                message=error.message,
            )
            for error in errors
        ]

    def _validate_entrypoint_origin(self, entrypoint: str) -> list[ValidationIssue]:
        module_name, _ = entrypoint.split(":", 1)
        _, issue = self._resolve_entrypoint_origin(module_name)
        return [issue] if issue is not None else []

    def _resolve_entrypoint_origin(
        self, module_name: str
    ) -> tuple[Path | None, ValidationIssue | None]:
        """Resolve exactly what import_module would use, without importing package code."""
        search_path: list[str] | None = None
        parts = module_name.split(".")
        for index in range(len(parts)):
            prefix = ".".join(parts[: index + 1])
            loaded = sys.modules.get(prefix)
            if loaded is not None:
                origin = self._module_origin(loaded, required=index == len(parts) - 1)
                if origin is not None and not _inside(origin, self.trusted_code_roots):
                    return None, self._untrusted_origin_issue(prefix, origin, cached=True)
                if index == len(parts) - 1:
                    if origin is None:
                        return None, self._not_found_issue(
                            module_name, "cached module has no concrete filesystem origin"
                        )
                    return origin, None
                module_path = getattr(loaded, "__path__", None)
                if module_path is None:
                    return None, self._not_found_issue(
                        module_name, f"cached parent {prefix} is not a package"
                    )
                search_path = [str(path) for path in module_path]
                continue

            spec = PathFinder.find_spec(prefix, search_path)
            if spec is None:
                return None, self._not_found_issue(
                    module_name, f"Python import resolution stopped at {prefix}"
                )
            origin = self._spec_origin(spec.origin)
            if origin is not None and not _inside(origin, self.trusted_code_roots):
                return None, self._untrusted_origin_issue(prefix, origin, cached=False)
            if index == len(parts) - 1:
                if origin is None:
                    return None, self._not_found_issue(
                        module_name, "entrypoint resolves to a namespace without code"
                    )
                return origin, None
            locations = spec.submodule_search_locations
            if locations is None:
                return None, self._not_found_issue(
                    module_name, f"resolved parent {prefix} is not a package"
                )
            search_path = [str(path) for path in locations]
        return None, self._not_found_issue(module_name, "module cannot be resolved")

    @staticmethod
    def _module_origin(module: ModuleType, *, required: bool = True) -> Path | None:
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None) or getattr(module, "__file__", None)
        resolved = ExtensionLoader._spec_origin(origin)
        if required and resolved is None:
            return None
        return resolved

    @staticmethod
    def _spec_origin(origin: str | None) -> Path | None:
        if not origin or origin in {"built-in", "frozen", "namespace"}:
            return None
        return Path(origin).resolve()

    @staticmethod
    def _not_found_issue(module_name: str, detail: str) -> ValidationIssue:
        return ValidationIssue(
            code="entrypoint_not_found",
            location="entrypoint",
            message=f"{module_name}: {detail}",
        )

    @staticmethod
    def _untrusted_origin_issue(
        module_name: str, origin: Path, *, cached: bool
    ) -> ValidationIssue:
        source = "cached module" if cached else "effective import target"
        return ValidationIssue(
            code="untrusted_entrypoint",
            location="entrypoint",
            message=f"{source} {module_name} resolves outside trusted roots: {origin}",
        )

    @staticmethod
    def _result(
        candidate: ExtensionCandidate, issues: list[ValidationIssue]
    ) -> ValidationResult:
        candidate.state = CandidateState.REJECTED if issues else CandidateState.VALIDATED
        return ValidationResult(valid=not issues, candidate=candidate, issues=issues)
