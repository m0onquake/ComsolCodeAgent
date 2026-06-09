"""Runtime diagnostics for local COMSOL Agent installations."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from comsol_agent.cli.config import Config, get_config_dir, get_config_path, load_config


@dataclass(frozen=True)
class DiagnosticCheck:
    """One doctor check result."""

    name: str
    status: str
    message: str
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_doctor(config: Config | None = None) -> dict[str, Any]:
    """Run non-invasive diagnostics without starting COMSOL or calling APIs."""
    config = config or load_config()
    checks = [
        _check_config(config),
        _check_llm(config),
        _check_comsol_config(config),
        _check_python_dependencies(),
        _check_mph_discovery(config),
        _check_proxy_environment(),
        _check_archive(),
    ]
    status = _overall_status(checks)
    return {
        "success": status != "fail",
        "status": status,
        "python": sys.executable,
        "checks": [check.to_dict() for check in checks],
    }


async def run_deep_doctor(
    config: Config | None = None,
    *,
    check_llm: bool = True,
    check_comsol: bool = True,
    comsol_cores: int | None = 1,
    create_smoke: bool = False,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Run base diagnostics plus optional real LLM and COMSOL runtime checks."""
    config = config or load_config()
    result = run_doctor(config)
    checks = [DiagnosticCheck(**check) for check in result["checks"]]

    if check_llm:
        checks.append(await _check_llm_api(config, timeout_seconds=timeout_seconds))
    if check_comsol:
        checks.append(
            await asyncio.to_thread(
                _check_comsol_startup,
                config,
                cores=comsol_cores,
                create_smoke=create_smoke,
            )
        )

    status = _overall_status(checks)
    return {
        "success": status != "fail",
        "status": status,
        "python": sys.executable,
        "deep": True,
        "checks": [check.to_dict() for check in checks],
    }


def _check_config(config: Config) -> DiagnosticCheck:
    path = get_config_path()
    return DiagnosticCheck(
        name="config",
        status="ok" if path.exists() else "warn",
        message="Config file found." if path.exists() else "Config file not found; defaults/env are in use.",
        details={
            "path": str(path),
            "provider": config.llm.provider,
            "model": config.llm.model,
        },
    )


def _check_llm(config: Config) -> DiagnosticCheck:
    provider = config.llm.provider
    key_present = bool(config.llm.api_key)
    if provider == "deepseek":
        key_present = key_present or bool(os.environ.get("DEEPSEEK_API_KEY"))
    elif provider == "openai":
        key_present = key_present or bool(os.environ.get("OPENAI_API_KEY"))
    elif provider == "anthropic":
        key_present = key_present or bool(os.environ.get("ANTHROPIC_API_KEY"))

    return DiagnosticCheck(
        name="llm",
        status="ok" if key_present else "fail",
        message=(
            f"{provider} API key is configured."
            if key_present
            else f"{provider} API key is missing."
        ),
        details={
            "provider": provider,
            "model": config.llm.model,
            "base_url": config.llm.base_url,
            "api_key_present": key_present,
        },
    )


def _check_comsol_config(config: Config) -> DiagnosticCheck:
    executable = config.comsol.executable_path
    if not executable:
        return DiagnosticCheck(
            name="comsol_config",
            status="warn",
            message="COMSOL executable is not configured; MPh discovery will be used.",
            details={"version": config.comsol.version},
        )

    path = Path(executable).expanduser()
    exists = path.exists()
    return DiagnosticCheck(
        name="comsol_config",
        status="ok" if exists else "fail",
        message="Configured COMSOL executable exists." if exists else "Configured COMSOL executable not found.",
        details={
            "executable_path": str(path),
            "exists": exists,
            "is_file": path.is_file() if exists else False,
            "version": config.comsol.version,
        },
    )


def _check_python_dependencies() -> DiagnosticCheck:
    required = ["yaml", "openai", "mph", "jpype", "rich", "prompt_toolkit"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    return DiagnosticCheck(
        name="python_dependencies",
        status="ok" if not missing else "fail",
        message="Required Python packages are importable." if not missing else "Missing Python packages.",
        details={"missing": missing, "checked": required},
    )


def _check_mph_discovery(config: Config) -> DiagnosticCheck:
    try:
        import mph
        import mph.discovery as discovery
    except Exception as exc:
        return DiagnosticCheck(
            name="mph_discovery",
            status="fail",
            message=f"MPh import/discovery failed: {exc}",
        )

    try:
        backends = discovery.find_backends()
    except Exception as exc:
        return DiagnosticCheck(
            name="mph_discovery",
            status="fail",
            message=f"MPh backend discovery failed: {exc}",
            details={"mph_version": getattr(mph, "__version__", "unknown")},
        )

    version = config.comsol.version
    version_found = (
        True
        if not version
        else any(str(backend.get("name")) == str(version) for backend in backends)
    )
    status = "ok" if backends and version_found else "warn"
    message = "MPh discovered COMSOL backends."
    if not backends:
        message = "MPh did not discover any COMSOL backends."
    elif not version_found:
        message = f"MPh discovered COMSOL, but not configured version {version!r}."

    return DiagnosticCheck(
        name="mph_discovery",
        status=status,
        message=message,
        details={
            "mph_version": getattr(mph, "__version__", "unknown"),
            "configured_version": version,
            "backend_count": len(backends),
            "backends": [
                {
                    "name": backend.get("name"),
                    "root": str(backend.get("root")),
                    "server": str(backend.get("server")),
                }
                for backend in backends
            ],
        },
    )


def _check_proxy_environment() -> DiagnosticCheck:
    proxy_vars = {
        name: os.environ.get(name)
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
        if os.environ.get(name)
    }
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    launchctl_no_proxy = _launchctl_getenv("NO_PROXY") or _launchctl_getenv("no_proxy") or ""
    direct_target_present = "166.111.237.134" in no_proxy
    launchctl_direct_target_present = "166.111.237.134" in launchctl_no_proxy
    status = "ok"
    message = "Proxy environment is configured."
    if proxy_vars and not direct_target_present:
        status = "warn"
        message = "Proxy is configured, but the current process NO_PROXY does not include 166.111.237.134."
    elif not proxy_vars:
        status = "warn"
        message = "No proxy variables are set."

    return DiagnosticCheck(
        name="proxy",
        status=status,
        message=message,
        details={
            "proxy_vars": proxy_vars,
            "no_proxy": no_proxy,
            "launchctl_no_proxy": launchctl_no_proxy,
            "direct_target_present": direct_target_present,
            "launchctl_direct_target_present": launchctl_direct_target_present,
        },
    )


def _check_archive() -> DiagnosticCheck:
    archive_path = get_config_dir() / "archive" / "archive.sqlite3"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    writable = os.access(archive_path.parent, os.W_OK)
    return DiagnosticCheck(
        name="archive",
        status="ok" if writable else "fail",
        message="Archive directory is writable." if writable else "Archive directory is not writable.",
        details={
            "archive_path": str(archive_path),
            "exists": archive_path.exists(),
            "directory": str(archive_path.parent),
            "directory_writable": writable,
        },
    )


async def _check_llm_api(config: Config, *, timeout_seconds: float) -> DiagnosticCheck:
    provider_name = config.llm.provider
    try:
        from comsol_agent.llm.router import create_provider

        provider = create_provider(
            provider_name,
            model=config.llm.model,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
        )
        generate_kwargs: dict[str, Any] = {
            "temperature": 0,
            "max_tokens": 96,
        }
        if _is_deepseek_v4_config(config):
            generate_kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        response = await asyncio.wait_for(
            provider.generate(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a concise runtime diagnostics assistant.",
                    },
                    {
                        "role": "user",
                        "content": "Reply with exactly: COMSOL Agent LLM OK",
                    },
                ],
                **generate_kwargs,
            ),
            timeout=timeout_seconds,
        )
        text = (response.text or "").strip()
        expected = "COMSOL Agent LLM OK"
        ok = expected in text
        return DiagnosticCheck(
            name="llm_api",
            status="ok" if ok else "warn",
            message=(
                f"{provider_name} API responded."
                if ok
                else f"{provider_name} API responded, but with unexpected text."
            ),
            details={
                "provider": provider_name,
                "model": config.llm.model,
                "base_url": config.llm.base_url,
                "finish_reason": response.finish_reason,
                "usage": response.usage or {},
                "response_preview": text[:120],
            },
        )
    except Exception as exc:
        return DiagnosticCheck(
            name="llm_api",
            status="fail",
            message=f"{provider_name} API check failed: {exc}",
            details={
                "provider": provider_name,
                "model": config.llm.model,
                "base_url": config.llm.base_url,
            },
        )


def _check_comsol_startup(
    config: Config,
    *,
    cores: int | None,
    create_smoke: bool,
) -> DiagnosticCheck:
    try:
        import mph
    except Exception as exc:
        return DiagnosticCheck(
            name="comsol_runtime",
            status="fail",
            message=f"MPh import failed before startup: {exc}",
        )

    version = config.comsol.version
    executable_path = config.comsol.executable_path
    if executable_path:
        path = Path(executable_path).expanduser()
        if not path.exists():
            return DiagnosticCheck(
                name="comsol_runtime",
                status="fail",
                message=f"Configured COMSOL executable not found: {path}",
                details={"executable_path": str(path)},
            )

    client = None
    smoke_path = None
    try:
        kwargs: dict[str, Any] = {}
        if cores:
            kwargs["cores"] = cores
        if version:
            kwargs["version"] = version
        client = mph.start(**kwargs)

        if create_smoke:
            output_dir = Path("runtime_smoke/doctor")
            output_dir.mkdir(parents=True, exist_ok=True)
            smoke_path = output_dir / "comsol_doctor_smoke.mph"
            model = client.create("comsol_doctor_smoke")
            model.save(smoke_path)
            try:
                client.remove(model)
            except Exception:
                pass

        return DiagnosticCheck(
            name="comsol_runtime",
            status="ok",
            message="COMSOL runtime started successfully via MPh.",
            details={
                "requested_version": version,
                "client_version": str(getattr(client, "version", "unknown")),
                "cores": cores,
                "create_smoke": create_smoke,
                "smoke_path": str(smoke_path.resolve()) if smoke_path else None,
            },
        )
    except Exception as exc:
        return DiagnosticCheck(
            name="comsol_runtime",
            status="fail",
            message=f"COMSOL startup check failed: {exc}",
            details={
                "requested_version": version,
                "cores": cores,
                "create_smoke": create_smoke,
            },
        )
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass


def _is_deepseek_v4_config(config: Config) -> bool:
    provider = str(config.llm.provider or "").lower()
    model = str(config.llm.model or "").lower()
    base_url = str(config.llm.base_url or "").lower()
    return provider == "deepseek" and model.startswith("deepseek-v4") and (
        not base_url or "deepseek" in base_url
    )


def _overall_status(checks: list[DiagnosticCheck]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "ok"


def _launchctl_getenv(name: str) -> str:
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            ["launchctl", "getenv", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    return result.stdout.strip()
