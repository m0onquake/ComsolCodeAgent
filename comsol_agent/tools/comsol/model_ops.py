"""COMSOL model operation tools — load, create, parameter management."""

from __future__ import annotations

from pathlib import Path

from .client import COMSOLClient


def get_client() -> COMSOLClient:
    """Get the COMSOL client singleton."""
    return COMSOLClient.get_instance()


# --- Tool Functions ---

def comsol_load_model(filepath: str) -> dict:
    """Load a COMSOL model from a .mph file.

    Args:
        filepath: Path to the .mph model file.

    Returns:
        dict with model name, summary, and status.
    """
    try:
        client = get_client()
        handle = client.load(filepath)
        summary = client.get_model_summary(handle.name)
        return {
            "success": True,
            "model_name": handle.name,
            "filepath": str(handle.path),
            "summary": summary,
        }
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Failed to load model: {e}"}


def comsol_create_model(name: str) -> dict:
    """Create a new empty COMSOL model.

    Args:
        name: Name for the new model.

    Returns:
        dict with model name and status.
    """
    try:
        client = get_client()
        handle = client.create(name)
        return {
            "success": True,
            "model_name": handle.name,
            "message": f"Model '{handle.name}' created successfully.",
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to create model: {e}"}


def comsol_set_parameter(model_name: str, parameter_name: str, value: str) -> dict:
    """Set a parameter value in a COMSOL model.

    Args:
        model_name: Name of the loaded model.
        parameter_name: Name of the parameter to set.
        value: Value to set, including unit if applicable (e.g. "10[mm]").

    Returns:
        dict with success status.
    """
    try:
        client = get_client()
        handle = client.get_model(model_name)
        mph_model = handle.mph_model

        mph_model.parameter(parameter_name, value)

        handle.is_modified = True
        return {
            "success": True,
            "model_name": model_name,
            "parameter": parameter_name,
            "value": value,
            "message": f"Parameter '{parameter_name}' set to '{value}'.",
        }
    except KeyError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Failed to set parameter: {e}"}


def comsol_list_parameters(model_name: str) -> dict:
    """List all parameters in a COMSOL model.

    Args:
        model_name: Name of the loaded model.

    Returns:
        dict with parameter list.
    """
    try:
        client = get_client()
        handle = client.get_model(model_name)
        mph_model = handle.mph_model
        parameters = mph_model.parameters()
        params = [
            {
                "name": name,
                "value": value,
                "description": "",
            }
            for name, value in parameters.items()
        ]
        return {"success": True, "model_name": model_name, "parameters": params}
    except KeyError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Failed to list parameters: {e}"}


def comsol_list_models() -> dict:
    """List all currently loaded COMSOL models.

    Returns:
        dict with model list.
    """
    try:
        client = get_client()
        models = []
        for name, handle in client.models.items():
            models.append({
                "name": name,
                "filepath": handle.path,
                "is_modified": handle.is_modified,
            })
        return {"success": True, "models": models, "count": len(models)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def comsol_close_model(name: str, save: bool = False) -> dict:
    """Close a COMSOL model.

    Args:
        name: Name of the model to close.
        save: Whether to save before closing.

    Returns:
        dict with status.
    """
    try:
        client = get_client()
        client.close(name, save=save)
        return {"success": True, "message": f"Model '{name}' closed."}
    except KeyError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Failed to close model: {e}"}


def comsol_save_model(model_name: str, filepath: str | None = None) -> dict:
    """Save a COMSOL model to disk.

    Args:
        model_name: Name of the model to save.
        filepath: Optional save path. Uses original path if not specified.

    Returns:
        dict with save path.
    """
    try:
        client = get_client()
        saved_path = client.save(model_name, filepath)
        return {
            "success": True,
            "model_name": model_name,
            "saved_to": saved_path,
            "message": f"Model saved to {saved_path}.",
        }
    except KeyError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Failed to save model: {e}"}
