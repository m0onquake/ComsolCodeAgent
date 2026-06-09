"""COMSOL result evaluation and export tools.

Re-exports core functions from solve.py and adds export/plot capabilities.
"""

from __future__ import annotations

from pathlib import Path

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

        mph_model.export("image", str(export_path))

        return {
            "success": True,
            "model_name": model_name,
            "plot_type": plot_type,
            "expression": expression or "default",
            "filepath": str(export_path),
            "message": f"Plot saved to {export_path}.",
        }
    except KeyError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Plot failed: {e}"}
