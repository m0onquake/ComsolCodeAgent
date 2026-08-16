"""COMSOL solve and evaluation tools."""

from __future__ import annotations

import time

from .client import COMSOLClient


def _safe_exception_text(error: BaseException) -> str:
    try:
        return str(error)
    except Exception as stringify_error:
        return (
            f"{type(error).__name__} "
            f"(exception stringification failed: {type(stringify_error).__name__}: {stringify_error!r})"
        )


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
        return {"success": False, "error": _safe_exception_text(e)}
    except Exception as e:
        return {"success": False, "error": f"Solve failed: {_safe_exception_text(e)}"}


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
    java_code: str,
    model_name: str | None = None,
    validate_first: bool = False,
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
        if validate_first:
            validation = _validate_java_code_before_execution(java_code, model_name)
            if validation.get("validation", {}).get("errors"):
                return {
                    "success": False,
                    "output": "",
                    "stdout": "",
                    "error": "Java/API validation failed.",
                    "exception_type": "ValidationError",
                    "error_type": "VALIDATION_ERROR",
                    "modified": False,
                    "validation": validation.get("validation"),
                    **({"model_name": model_name} if model_name else {}),
                }

        client = get_client()
        target_model_name = _resolve_execution_model_name(client, model_name)
        output = client.execute_java(java_code, model_name)
        parsed = _parse_java_execution_output(output)

        result = {
            "success": parsed["success"],
            "output": output,
            "stdout": parsed["stdout"],
            "error": parsed["error"],
            "exception_type": parsed["exception_type"],
            "error_type": parsed["error_type"],
            "modified": False,
        }
        if validate_first:
            result["validation"] = validation.get("validation")
        if target_model_name:
            result["model_name"] = target_model_name
            # Mark model as modified because Java code may have partially changed it.
            try:
                handle = client.get_model(target_model_name)
                handle.is_modified = True
                result["modified"] = True
            except Exception:
                pass

        return result
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "stdout": "",
            "error": f"Java execution failed: {e}",
            "exception_type": type(e).__name__,
            "error_type": "RUNTIME_ERROR",
            "modified": False,
            **({"model_name": model_name} if model_name else {}),
        }


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


def _resolve_execution_model_name(client: COMSOLClient, model_name: str | None) -> str | None:
    if model_name:
        return model_name
    models = client.models
    if not models:
        return None
    return next(iter(models))


def _validate_java_code_before_execution(java_code: str, model_name: str | None) -> dict:
    from comsol_agent.tools.simulation import simulation_validate_template

    return simulation_validate_template(
        name=model_name or "java_execution",
        java_code=java_code,
    )


def _parse_java_execution_output(output: str) -> dict:
    if output.startswith("Execution Error:"):
        error = output.removeprefix("Execution Error:").strip()
        exception_type, message = _split_exception_message(error)
        return {
            "success": False,
            "stdout": "",
            "error": message,
            "exception_type": exception_type,
            "error_type": _classify_java_execution_error(exception_type, message, wrapper_error=True),
        }
    if output.startswith("Error:"):
        error = output.removeprefix("Error:").strip()
        exception_type, message = _split_exception_message(error)
        return {
            "success": False,
            "stdout": "",
            "error": message,
            "exception_type": exception_type,
            "error_type": _classify_java_execution_error(exception_type, message, wrapper_error=False),
        }
    return {
        "success": True,
        "stdout": output,
        "error": None,
        "exception_type": None,
        "error_type": None,
    }


def _split_exception_message(error: str) -> tuple[str | None, str]:
    if ":" not in error:
        return None, error
    maybe_type, message = error.split(":", 1)
    maybe_type = maybe_type.strip()
    if maybe_type and maybe_type.replace("_", "").replace(".", "").isalnum():
        return maybe_type, message.strip()
    return None, error


def _classify_java_execution_error(
    exception_type: str | None,
    message: str,
    *,
    wrapper_error: bool,
) -> str:
    lowered = message.lower()
    if exception_type == "SyntaxError" or "invalid syntax" in lowered:
        return "SYNTAX_ERROR"
    if exception_type in {"AttributeError", "TypeError"}:
        return "API_ERROR"
    if any(pattern in lowered for pattern in ("no method", "has no attribute", "not found")):
        return "API_ERROR"
    if wrapper_error:
        return "WRAPPER_ERROR"
    return "RUNTIME_ERROR"
