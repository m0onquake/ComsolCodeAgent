"""COMSOL result evaluation and export tools.

Re-exports core functions from solve.py and adds export/plot capabilities.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .client import COMSOLClient


def get_client() -> COMSOLClient:
    return COMSOLClient.get_instance()


def comsol_export_results(
    model_name: str,
    export_type: str = "data",
    filename: str | None = None,
    expression: str | None = None,
) -> dict:
    """Export results from a COMSOL model.

    Args:
        model_name: Name of the loaded model.
        export_type: Type of export - 'data' (CSV), 'image', or 'model' (.mph).
        filename: Output filename. Auto-generated if not specified.
        expression: Expression to export (for 'data' type).

    Returns:
        dict with export path and status.
    """
    try:
        client = get_client()
        handle = client.get_model(model_name)
        mph_model = handle.mph_model

        if filename is None:
            if export_type == "image":
                filename = f"{model_name}_plot.png"
            elif export_type == "data":
                filename = f"{model_name}_data.csv"
            else:
                filename = f"{model_name}.mph"

        export_path = Path(filename).expanduser().resolve()
        export_path.parent.mkdir(parents=True, exist_ok=True)

        if export_type == "image":
            mph_model.export("image", str(export_path))
        elif export_type == "data":
            if expression:
                data = mph_model.evaluate(expression)
                import numpy as np
                np.savetxt(str(export_path), data if isinstance(data, np.ndarray) else [data], delimiter=",")
            else:
                mph_model.export("data", str(export_path))
        elif export_type == "model":
            mph_model.save(str(export_path))
        else:
            return {"success": False, "error": f"Unknown export type: {export_type}"}

        return {
            "success": True,
            "model_name": model_name,
            "export_type": export_type,
            "filepath": str(export_path),
            "message": f"Exported to {export_path}.",
        }
    except KeyError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Export failed: {e}"}


def comsol_plot(
    model_name: str,
    expression: str | None = None,
    plot_type: str = "surface",
    filename: str | None = None,
) -> dict:
    """Generate a plot from COMSOL results.

    Args:
        model_name: Name of the loaded model.
        expression: Expression to plot (e.g. "T" for temperature).
        plot_type: Type of plot - 'surface', 'contour', 'arrow', etc.
        filename: Output image path. Auto-generated if not specified.

    Returns:
        dict with plot path and status.
    """
    try:
        if filename is None:
            filename = f"{model_name}_{plot_type}.png"

        # Use COMSOL's built-in export via MPh
        client = get_client()
        handle = client.get_model(model_name)
        mph_model = handle.mph_model

        export_path = Path(filename).expanduser().resolve()
        export_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            mph_model.export("image", str(export_path))
            export_method = "mph"
        except Exception as primary_exc:
            export_method = _export_plot_image_via_java(
                handle.java_model,
                export_path,
                expression=expression,
                plot_type=plot_type,
                primary_error=primary_exc,
            )

        return {
            "success": True,
            "model_name": model_name,
            "plot_type": plot_type,
            "expression": expression or "default",
            "filepath": str(export_path),
            "export_method": export_method,
            "message": f"Plot saved to {export_path}.",
        }
    except KeyError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Plot failed: {e}"}


def _export_plot_image_via_java(
    java_model: Any,
    export_path: Path,
    *,
    expression: str | None,
    plot_type: str,
    primary_error: Exception,
) -> str:
    """Fallback image export for generated models without MPh's default export node."""
    result = java_model.result()
    plot_group = _select_or_create_plot_group(
        java_model,
        result,
        expression=expression,
        plot_type=plot_type,
    )
    export = result.export()
    export_tag = _unique_tag(_tags(export), "img_codex")
    last_error: Exception | None = None
    for export_type in ("Image2D", "Image"):
        try:
            export.create(export_tag, export_type)
            image_export = result.export(export_tag)
            image_export.set("plotgroup", plot_group)
            _set_first_supported(image_export, ("pngfilename", "filename"), str(export_path))
            image_export.run()
            return f"java:{export_type}"
        except Exception as exc:
            last_error = exc
            try:
                export.remove(export_tag)
            except Exception:
                pass
    raise RuntimeError(f"{primary_error}; Java image export fallback failed: {last_error}")


def _select_or_create_plot_group(
    java_model: Any,
    result: Any,
    *,
    expression: str | None,
    plot_type: str,
) -> str:
    if expression:
        return _create_expression_plot_group(
            java_model,
            result,
            expression=expression,
            plot_type=plot_type,
        )

    tags = _tags(result)
    for tag in tags:
        if _looks_like_plot_group(java_model, tag):
            return tag
    return _create_expression_plot_group(
        java_model,
        result,
        expression=expression,
        plot_type=plot_type,
    )


def _create_expression_plot_group(
    java_model: Any,
    result: Any,
    *,
    expression: str | None,
    plot_type: str,
) -> str:
    plot_group = "pg_codex"
    plot_group = _unique_tag(_tags(result), plot_group)
    result.create(plot_group, "PlotGroup2D")
    if expression:
        feature_type = {
            "surface": "Surface",
            "contour": "Contour",
            "arrow": "ArrowSurface",
        }.get(plot_type.lower(), "Surface")
        java_model.result(plot_group).create("plot_codex", feature_type)
        java_model.result(plot_group).feature("plot_codex").set("expr", expression)
    try:
        java_model.result(plot_group).run()
    except Exception:
        pass
    return plot_group


def _looks_like_plot_group(java_model: Any, tag: str) -> bool:
    try:
        node = java_model.result(tag)
        return "PlotGroup" in str(node.getType())
    except Exception:
        return tag.startswith("pg")


def _set_first_supported(node: Any, keys: tuple[str, ...], value: str) -> None:
    last_error: Exception | None = None
    for key in keys:
        try:
            node.set(key, value)
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not set any of {keys}: {last_error}")


def _tags(node: Any) -> list[str]:
    try:
        return [str(tag) for tag in node.tags()]
    except Exception:
        return []


def _unique_tag(existing: list[str], prefix: str) -> str:
    if prefix not in existing:
        return prefix
    index = 1
    while f"{prefix}_{index}" in existing:
        index += 1
    return f"{prefix}_{index}"
