"""COMSOL solve and evaluation tools."""

from __future__ import annotations

import time

from .client import COMSOLClient


def get_client() -> COMSOLClient:
    """Get the COMSOL client singleton."""
    return COMSOLClient.get_instance()


def comsol_solve(model_name: str, study_name: str | None = None) -> dict:
    """Run a COMSOL study/solver.

    Args:
        model_name: Name of the loaded model.
        study_name: Name of the study to run. If None, runs the first study.

    Returns:
        dict with solve status, timing, and convergence info.
    """
    try:
        client = get_client()
        handle = client.get_model(model_name)
        mph_model = handle.mph_model

        start_time = time.monotonic()

        if study_name:
            mph_model.solve(study_name)
        else:
            mph_model.solve()

        elapsed = time.monotonic() - start_time

        # Get convergence info
        convergence_info = ""
        try:
            java_model = handle.java_model
            if study_name:
                sol = java_model.sol(study_name)
            else:
                studies = java_model.study().tags()
                if studies:
                    sol = java_model.sol(studies[0])
                else:
                    sol = None
            if sol is not None:
                try:
                    convergence_info = (
                        f"Converged: {sol.getSolveStatus()}"
                    )
                except Exception:
                    convergence_info = "Solve completed."
        except Exception:
            convergence_info = "Solve completed (status unknown)."

        handle.is_modified = True

        return {
            "success": True,
            "model_name": model_name,
            "study": study_name or "default",
            "elapsed_seconds": round(elapsed, 1),
            "status": convergence_info,
            "message": f"Solve completed in {elapsed:.1f}s.",
        }
    except KeyError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Solve failed: {e}"}


def comsol_evaluate(model_name: str, expression: str) -> dict:
    """Evaluate an expression on the COMSOL model results.

    Args:
        model_name: Name of the loaded model.
        expression: COMSOL expression to evaluate (e.g. "T", "solid.rho", "maxop1(T)").

    Returns:
        dict with evaluation results.
    """
    try:
        client = get_client()
        handle = client.get_model(model_name)
        mph_model = handle.mph_model

        result = mph_model.evaluate(expression)

        # Convert to Python-friendly format
        import numpy as np

        if isinstance(result, np.ndarray):
            data = result.tolist()
            shape = result.shape
            stats = {}
            if result.size > 0:
                stats = {
                    "min": float(result.min()),
                    "max": float(result.max()),
                    "mean": float(result.mean()),
                }
            return {
                "success": True,
                "model_name": model_name,
                "expression": expression,
                "shape": list(shape),
                "statistics": stats,
                "data_sample": _sample_array(result),
            }
        else:
            return {
                "success": True,
                "model_name": model_name,
                "expression": expression,
                "value": result,
            }
    except KeyError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Evaluation failed: {e}"}


def comsol_execute_java(
    java_code: str, model_name: str | None = None
) -> dict:
    """Execute Java code against a COMSOL model.

    Use this for advanced operations not covered by higher-level tools.
    Reference the model object as 'model' in your Java code.

    Args:
        java_code: Java code to execute using the COMSOL API.
        model_name: Target model name. Uses first loaded model if None.

    Returns:
        dict with execution output.
    """
    try:
        client = get_client()
        output = client.execute_java(java_code, model_name)
        is_error = output.startswith("Error:") or output.startswith("Execution Error:")

        result = {
            "success": not is_error,
            "output": output,
        }
        if model_name:
            result["model_name"] = model_name
            # Mark model as modified (Java code may have changed it)
            try:
                handle = client.get_model(model_name)
                handle.is_modified = True
            except Exception:
                pass

        return result
    except Exception as e:
        return {"success": False, "error": f"Java execution failed: {e}"}


def comsol_get_model_summary(model_name: str) -> dict:
    """Get a structural summary of a loaded COMSOL model.

    Args:
        model_name: Name of the loaded model.

    Returns:
        dict with model summary.
    """
    try:
        client = get_client()
        summary = client.get_model_summary(model_name)
        return {"success": True, "model_name": model_name, "summary": summary}
    except KeyError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Failed to get summary: {e}"}


def _sample_array(result, max_values: int = 10) -> list:
    """Return a compact sample from a NumPy array without dumping large rows."""
    flattened = result.ravel().tolist()
    if len(flattened) <= max_values:
        return flattened
    half = max(1, max_values // 2)
    return flattened[:half] + ["..."] + flattened[-half:]
