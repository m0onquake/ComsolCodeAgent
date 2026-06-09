"""COMSOL client management via MPh.

Manages the lifecycle of the COMSOL session — start, stop, and model tracking.
"""

from __future__ import annotations

import threading
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from comsol_agent.utils.logger import log


@dataclass
class ModelHandle:
    """Tracks a loaded COMSOL model."""

    name: str
    path: str | None = None
    java_model: Any = None
    mph_model: Any = None  # MPh Model wrapper
    is_modified: bool = False


class COMSOLClient:
    """Manages a COMSOL session via MPh.

    Uses a singleton pattern to ensure only one COMSOL session exists.
    Thread-safe for basic operations.

    Usage:
        client = COMSOLClient.get_instance()
        client.start()
        model = client.load("path/to/model.mph")
        client.solve(model)
        client.stop()
    """

    _instance: COMSOLClient | None = None
    _lock = threading.Lock()

    def __init__(self):
        self._mph_client: Any = None  # mph.Client
        self._models: dict[str, ModelHandle] = {}
        self._started = False

    @classmethod
    def get_instance(cls) -> COMSOLClient:
        """Get or create the singleton COMSOL client."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (primarily for testing)."""
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.stop()
                except Exception:
                    pass
                cls._instance = None

    @property
    def is_running(self) -> bool:
        return self._started and self._mph_client is not None

    @property
    def models(self) -> dict[str, ModelHandle]:
        return dict(self._models)

    def start(
        self,
        cores: int | None = None,
        version: str | None = None,
        executable_path: str | Path | None = None,
    ) -> None:
        """Start the COMSOL session via MPh.

        Args:
            cores: Number of CPU cores to use.
            version: COMSOL version string (e.g. "6.2").
            executable_path: Optional configured COMSOL executable path. MPh still
                performs backend discovery, but this is validated early to catch
                stale configuration before starting a COMSOL process.
        """
        if self._started:
            return

        if executable_path:
            executable = Path(executable_path).expanduser().resolve()
            if not executable.exists():
                raise FileNotFoundError(f"Configured COMSOL executable not found: {executable}")
            if not executable.is_file():
                raise ValueError(f"Configured COMSOL executable is not a file: {executable}")

        try:
            import mph
        except ImportError:
            raise RuntimeError(
                "MPh is not installed. Install it with: pip install MPh\n"
                "Also ensure COMSOL is installed and licensed on this machine."
            )

        log.info("Starting COMSOL session via MPh...")
        if executable_path:
            log.info("Using configured COMSOL executable hint: %s", executable_path)
        kwargs = {}
        if cores:
            kwargs["cores"] = cores
        if version:
            kwargs["version"] = version

        self._mph_client = mph.start(**kwargs)
        self._started = True
        log.info(f"COMSOL session started (version={self._mph_client.version})")

    def stop(self) -> None:
        """Stop the COMSOL session."""
        if not self._started:
            return
        log.info("Stopping COMSOL session...")
        self._models.clear()
        try:
            if self._mph_client:
                # MPh client cleanup
                self._mph_client = None
        except Exception as e:
            log.warning(f"Error during COMSOL cleanup: {e}")
        self._started = False
        log.info("COMSOL session stopped.")

    def load(self, filepath: str | Path) -> ModelHandle:
        """Load a COMSOL model file (.mph).

        Args:
            filepath: Path to the .mph file.

        Returns:
            ModelHandle for the loaded model.
        """
        self._ensure_started()
        filepath = Path(filepath).expanduser().resolve()
        if not filepath.exists():
            raise FileNotFoundError(f"Model file not found: {filepath}")

        log.info(f"Loading model: {filepath}")
        mph_model = self._mph_client.load(str(filepath))
        name = filepath.stem

        # Deduplicate name
        base_name = name
        counter = 1
        while name in self._models:
            name = f"{base_name}_{counter}"
            counter += 1

        java_model = mph_model.java
        handle = ModelHandle(
            name=name,
            path=str(filepath),
            java_model=java_model,
            mph_model=mph_model,
        )
        self._models[name] = handle
        log.info(f"Model loaded: {name} (from {filepath})")
        return handle

    def create(self, name: str) -> ModelHandle:
        """Create a new empty COMSOL model.

        Args:
            name: Name for the new model.

        Returns:
            ModelHandle for the new model.
        """
        self._ensure_started()

        # Deduplicate name
        base_name = name
        counter = 1
        while name in self._models:
            name = f"{base_name}_{counter}"
            counter += 1

        mph_model = self._mph_client.create()
        java_model = mph_model.java

        handle = ModelHandle(
            name=name,
            java_model=java_model,
            mph_model=mph_model,
        )
        self._models[name] = handle
        log.info(f"Model created: {name}")
        return handle

    def get_model(self, name: str) -> ModelHandle:
        """Get a loaded model by name.

        Raises:
            KeyError: If model not found.
        """
        if name not in self._models:
            raise KeyError(
                f"Model '{name}' not found. Loaded models: {list(self._models.keys())}"
            )
        return self._models[name]

    def save(self, name: str, filepath: str | Path | None = None) -> str:
        """Save a model to disk.

        Args:
            name: Model name.
            filepath: Save path. If None, saves to original path.

        Returns:
            The path where the model was saved.
        """
        handle = self.get_model(name)
        filepath = Path(filepath).expanduser().resolve() if filepath else None

        if filepath is None:
            if handle.path:
                filepath = Path(handle.path)
            else:
                filepath = Path.cwd() / f"{name}.mph"

        filepath.parent.mkdir(parents=True, exist_ok=True)
        handle.mph_model.save(str(filepath))
        handle.path = str(filepath)
        handle.is_modified = False
        log.info(f"Model saved: {filepath}")
        return str(filepath)

    def close(self, name: str, save: bool = False) -> None:
        """Close a model.

        Args:
            name: Model name.
            save: Whether to save before closing.
        """
        handle = self.get_model(name)
        if save and handle.is_modified:
            self.save(name)
        # MPh doesn't have explicit close; just remove reference
        del self._models[name]
        log.info(f"Model closed: {name}")

    def execute_java(self, java_code: str, model_name: str | None = None) -> str:
        """Execute Java code against a COMSOL model.

        Args:
            java_code: Java code string to execute.
            model_name: Target model name. If None, uses 'model' as the variable.

        Returns:
            Output from the Java execution.
        """
        self._ensure_started()
        if model_name:
            handle = self.get_model(model_name)
            java_model = handle.java_model
        else:
            # Use first available model
            if not self._models:
                raise RuntimeError("No models loaded. Load or create a model first.")
            java_model = next(iter(self._models.values())).java_model

        import io

        # Redirect Java stdout
        old_out = None
        output_buffer = io.StringIO()

        try:
            # Prepare and execute the code using the model's Java object
            # The Java code can reference 'model' as the current model object
            local_vars: dict[str, Any] = {"model": java_model, "output": output_buffer}
            executable_code = _strip_java_line_comments(java_code)
            indented_code = textwrap.indent(executable_code, "    ")
            exec(
                f"""
_result = None
try:
    # Execute the Java code using JPype/JNI
{indented_code}
except Exception as _e:
    output.write(f"Error: {{type(_e).__name__}}: {{_e}}")
""",
                {"model": java_model},
                local_vars,
            )
            result = output_buffer.getvalue()
            if not result:
                result = "Code executed successfully (no output)."
            return result
        except Exception as e:
            log.error(f"Java execution error: {e}")
            return f"Execution Error: {type(e).__name__}: {e}"

    def java_to_python(self, java_code: str) -> str:
        """Convert Java API code to MPh Python equivalent.

        This is a best-effort converter for common patterns.
        Full conversion is handled by the LLM when needed.

        Args:
            java_code: Java code using COMSOL API.

        Returns:
            Equivalent Python code using MPh.
        """
        # Simple pattern replacements for common COMSOL Java API calls
        mappings = [
            ("model.geom().create(", "model.create('geom', "),
            ("model.geom(", "model.component('"),
            ("model.physics().create(", "model.create('physics', "),
            ("model.mesh().create(", "model.create('mesh', "),
            ("model.study().create(", "model.create('study', "),
            ("model.sol(", "model.solution('"),
            ("model.result().", "model.result()."),
            ("int[]", ""),
            ("double[]", ""),
            ("String[]", ""),
        ]
        python_code = java_code
        for java_pat, py_pat in mappings:
            python_code = python_code.replace(java_pat, py_pat)

        if java_code != python_code:
            log.info("Applied basic Java-to-Python conversions.")
        else:
            log.info("No automatic conversions applied (use LLM for complex code).")

        return python_code

    def get_model_summary(self, name: str) -> str:
        """Get a text summary of a model's structure.

        Args:
            name: Model name.

        Returns:
            Human-readable model summary.
        """
        handle = self.get_model(name)
        mph_model = handle.mph_model

        lines = [f"Model: {name}"]
        if handle.path:
            lines.append(f"File: {handle.path}")

        # Parameters
        try:
            params = list(mph_model.parameters())
            if params:
                lines.append("\nParameters:")
                for p in params:
                    lines.append(f"  - {p}")
        except Exception:
            pass

        # Components (geometries)
        try:
            java_model = handle.java_model
            for geom_name in java_model.geom().tags():
                lines.append(f"\nGeometry: {geom_name}")
                geom = java_model.geom(geom_name)
                # Get feature count
                try:
                    features = geom.feature().tags()
                    lines.append(f"  Features: {', '.join(features)}")
                except Exception:
                    pass
        except Exception:
            pass

        # Physics
        try:
            java_model = handle.java_model
            for phys_name in java_model.physics().tags():
                lines.append(f"\nPhysics: {phys_name}")
        except Exception:
            pass

        # Studies
        try:
            java_model = handle.java_model
            for study_name in java_model.study().tags():
                lines.append(f"\nStudy: {study_name}")
        except Exception:
            pass

        return "\n".join(lines) if len(lines) > 1 else f"Model '{name}' is empty."

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError("COMSOL session not started. Call client.start() first.")


def _strip_java_line_comments(java_code: str) -> str:
    """Remove Java-style line comments while preserving string literals."""
    cleaned_lines = []
    for line in java_code.splitlines():
        in_single = False
        in_double = False
        escaped = False
        comment_at = None
        for index, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
            elif (
                char == "/"
                and index + 1 < len(line)
                and line[index + 1] == "/"
                and not in_single
                and not in_double
            ):
                comment_at = index
                break
        cleaned_lines.append(line[:comment_at] if comment_at is not None else line)
    return "\n".join(cleaned_lines)
