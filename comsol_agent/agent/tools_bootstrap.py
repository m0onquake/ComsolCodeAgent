"""Bootstrap module that registers all available tools.

Import this module to register all tools with the tool registry.
Call register_all_tools() to ensure all tools are available.
"""

from __future__ import annotations

import asyncio

from comsol_agent.agent.tool_registry import register_sync
from comsol_agent.tools.comsol.model_ops import (
    comsol_close_model,
    comsol_create_model,
    comsol_list_models,
    comsol_list_parameters,
    comsol_load_model,
    comsol_save_model,
    comsol_set_parameter,
)
from comsol_agent.tools.comsol.solve import (
    comsol_evaluate,
    comsol_execute_java,
    comsol_get_model_summary,
    comsol_solve,
)
from comsol_agent.tools.comsol.evaluate import comsol_export_results, comsol_plot
from comsol_agent.tools.file_ops import file_list, file_read, file_write, shell_execute
from comsol_agent.tools.simulation import (
    simulation_compare_artifacts,
    simulation_export_template,
    simulation_export_artifact_report,
    simulation_list_artifacts,
    simulation_list_example_models,
    simulation_list_templates,
    simulation_plan_bearing_contact,
    simulation_plan_parameter_sweep,
    simulation_read_artifact,
    simulation_read_template,
    simulation_rerun_artifact,
    simulation_run_template,
    simulation_run_parameter_sweep,
    simulation_run_example_model,
    simulation_save_template,
    simulation_search_artifacts,
    simulation_search_local_docs,
    simulation_search_templates,
    simulation_retrieve_api_docs,
    simulation_validate_template,
)


def register_all_tools() -> None:
    """Register all available tools with the tool registry.

    This is idempotent — calling it multiple times is safe.
    """

    # --- COMSOL Model Operations ---

    register_sync(
        name="comsol_load_model",
        description="Load a COMSOL model from a .mph file. Returns model name, file path, and a structural summary.",
        parameters={
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Absolute or relative path to the .mph model file.",
                },
            },
            "required": ["filepath"],
        },
        handler=comsol_load_model,
    )

    register_sync(
        name="comsol_create_model",
        description="Create a new empty COMSOL model.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the new model (used as identifier in the session).",
                },
            },
            "required": ["name"],
        },
        handler=comsol_create_model,
    )

    register_sync(
        name="comsol_set_parameter",
        description="Set a parameter value in a COMSOL model. Creates the parameter if it doesn't exist.",
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "Name of the loaded model.",
                },
                "parameter_name": {
                    "type": "string",
                    "description": "Name of the parameter to set (e.g. 'L', 'freq', 'T0').",
                },
                "value": {
                    "type": "string",
                    "description": "Value including unit if applicable (e.g. '10[mm]', '100[degC]', '1e6[Pa]').",
                },
            },
            "required": ["model_name", "parameter_name", "value"],
        },
        handler=comsol_set_parameter,
    )

    register_sync(
        name="comsol_list_parameters",
        description="List all parameters in a COMSOL model with their current values.",
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "Name of the loaded model.",
                },
            },
            "required": ["model_name"],
        },
        handler=comsol_list_parameters,
    )

    register_sync(
        name="comsol_list_models",
        description="List all currently loaded COMSOL models in the session.",
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=comsol_list_models,
    )

    register_sync(
        name="comsol_close_model",
        description="Close a COMSOL model and remove it from the session.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the model to close.",
                },
                "save": {
                    "type": "boolean",
                    "description": "Whether to save the model before closing.",
                    "default": False,
                },
            },
            "required": ["name"],
        },
        handler=comsol_close_model,
    )

    register_sync(
        name="comsol_save_model",
        description="Save a COMSOL model to disk.",
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "Name of the model to save.",
                },
                "filepath": {
                    "type": "string",
                    "description": "Optional save path. Saves to original path if omitted.",
                },
            },
            "required": ["model_name"],
        },
        handler=comsol_save_model,
    )

    # --- COMSOL Solver & Evaluation ---

    register_sync(
        name="comsol_solve",
        description="Run a COMSOL study/solver on a loaded model. Returns solve status, timing, and convergence information.",
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "Name of the loaded model to solve.",
                },
                "study_name": {
                    "type": "string",
                    "description": "Name of the study to run. Uses the first study if not specified.",
                },
            },
            "required": ["model_name"],
        },
        handler=comsol_solve,
    )

    register_sync(
        name="comsol_evaluate",
        description="Evaluate an expression on the solved COMSOL model (e.g. 'T' for temperature, 'solid.rho', 'maxop1(T)'). Returns data with statistics.",
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "Name of the loaded model.",
                },
                "expression": {
                    "type": "string",
                    "description": "COMSOL expression to evaluate. Examples: 'T', 'solid.rho', 'maxop1(T)', 'd(T,x)'.",
                },
            },
            "required": ["model_name", "expression"],
        },
        handler=comsol_evaluate,
    )

    register_sync(
        name="comsol_execute_java",
        description="Execute arbitrary Java API code against a COMSOL model. Use 'model' variable to reference the model. For advanced operations.",
        parameters={
            "type": "object",
            "properties": {
                "java_code": {
                    "type": "string",
                    "description": "Java code to execute using the COMSOL API. The model object is available as 'model'.",
                },
                "model_name": {
                    "type": "string",
                    "description": "Target model name. Uses the first loaded model if omitted.",
                },
                "validate_first": {
                    "type": "boolean",
                    "description": "Run offline Java/API template validation before execution. Defaults to false.",
                },
            },
            "required": ["java_code"],
        },
        handler=comsol_execute_java,
    )

    register_sync(
        name="comsol_get_model_summary",
        description="Get a structural summary of a loaded COMSOL model showing geometries, physics, studies, and parameters.",
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "Name of the loaded model.",
                },
            },
            "required": ["model_name"],
        },
        handler=comsol_get_model_summary,
    )

    # --- COMSOL Export & Plot ---

    register_sync(
        name="comsol_export_results",
        description="Export results from a COMSOL model to a file (CSV data, PNG image, or .mph model).",
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "Name of the loaded model.",
                },
                "export_type": {
                    "type": "string",
                    "enum": ["data", "image", "model"],
                    "description": "Export type: 'data' (CSV), 'image' (PNG), or 'model' (.mph).",
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename. Auto-generated if omitted.",
                },
                "expression": {
                    "type": "string",
                    "description": "Expression to export (for 'data' type only).",
                },
            },
            "required": ["model_name", "export_type"],
        },
        handler=comsol_export_results,
    )

    register_sync(
        name="comsol_plot",
        description="Generate and save a plot image from COMSOL results.",
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "Name of the loaded model.",
                },
                "expression": {
                    "type": "string",
                    "description": "Expression to plot (e.g. 'T').",
                },
                "plot_type": {
                    "type": "string",
                    "description": "Plot type: 'surface', 'contour', 'arrow', etc.",
                },
                "filename": {
                    "type": "string",
                    "description": "Output image path. Auto-generated if omitted.",
                },
            },
            "required": ["model_name"],
        },
        handler=comsol_plot,
    )

    # --- File & Shell Operations ---

    register_sync(
        name="file_read",
        description="Read a file from the filesystem. Returns content with line numbers.",
        parameters={
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Absolute path to the file to read.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default 500).",
                },
            },
            "required": ["filepath"],
        },
        handler=file_read,
    )

    register_sync(
        name="file_write",
        description="Write content to a file on the filesystem.",
        parameters={
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Absolute path for the output file.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write.",
                },
            },
            "required": ["filepath", "content"],
        },
        handler=file_write,
    )

    register_sync(
        name="file_list",
        description="List files in a directory with optional glob pattern filtering.",
        parameters={
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory path to list (default: current directory).",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g. '*.mph', '*.java').",
                },
            },
        },
        handler=file_list,
    )

    register_sync(
        name="shell_execute",
        description="Execute a shell command. Useful for running COMSOL batch mode or other system operations.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Working directory for the command.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (max 600, default 120).",
                },
            },
            "required": ["command"],
        },
        handler=shell_execute,
    )

    # --- Simulation Planning ---

    register_sync(
        name="simulation_plan_bearing_contact",
        description=(
            "Plan a bearing-contact simulation from a natural-language request and known parameters. "
            "Returns whether to ask follow-up questions or use defaults, plus the recommended "
            "bearing_contact_hertz_seed template, resolved defaults, assumptions, and outputs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "user_request": {
                    "type": "string",
                    "description": "User's bearing/contact simulation request in natural language.",
                },
                "provided_params": {
                    "type": "object",
                    "description": (
                        "Known user parameters, e.g. {'inner_diameter': '25[mm]', "
                        "'outer_diameter': '52[mm]', 'radial_load': '1000[N]'}."
                    ),
                },
                "allow_defaults": {
                    "type": "boolean",
                    "description": "If true, prepare a quick default demo instead of asking for missing required parameters.",
                },
            },
            "required": ["user_request"],
        },
        handler=simulation_plan_bearing_contact,
    )

    register_sync(
        name="simulation_plan_parameter_sweep",
        description=(
            "Plan a parameter sweep without running COMSOL. Expands parameter axes "
            "into cases and recommends the runtime tool sequence."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "Name of the loaded model the sweep would run against.",
                },
                "parameters": {
                    "type": "object",
                    "description": "Mapping from parameter name to list of values with units.",
                },
                "output_expressions": {
                    "type": "array",
                    "description": "Optional COMSOL expressions to evaluate after each solve.",
                },
                "max_cases": {
                    "type": "integer",
                    "description": "Maximum number of expanded cases to include in the returned plan.",
                },
            },
            "required": ["model_name", "parameters"],
        },
        handler=simulation_plan_parameter_sweep,
    )

    register_sync(
        name="simulation_search_local_docs",
        description=(
            "Search local markdown documentation using offline keyword matching. "
            "Useful before COMSOL API docs RAG/embeddings are configured."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query, e.g. 'LLMRouter fallback' or 'COMSOL solve workflow'.",
                },
                "directory": {
                    "type": "string",
                    "description": "Workspace-relative directory to search. Defaults to docs.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern for documents. Defaults to *.md.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum search results to return.",
                },
            },
            "required": ["query"],
        },
        handler=simulation_search_local_docs,
    )

    register_sync(
        name="simulation_retrieve_api_docs",
        description=(
            "Retrieve compact, cited snippets from local COMSOL/project documentation for "
            "API repair, code generation, and simulation setup guidance without network access."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Retrieval query such as 'model.param().set Java API' or 'Heat Transfer physics setup'.",
                },
                "directory": {
                    "type": "string",
                    "description": "Workspace-relative directory to search. Defaults to docs.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern for documents. Defaults to *.md.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum snippets to return.",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter such as thermal, structural, fluid, electromagnetic, or general.",
                },
                "snippet_chars": {
                    "type": "integer",
                    "description": "Approximate maximum characters per returned snippet.",
                },
            },
            "required": ["query"],
        },
        handler=simulation_retrieve_api_docs,
    )

    register_sync(
        name="simulation_list_example_models",
        description=(
            "List built-in COMSOL example models available for high-level smoke tests "
            "and domain-specific demonstrations."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter such as thermal, structural, fluid, or electromagnetic.",
                },
            },
        },
        handler=simulation_list_example_models,
    )

    register_sync(
        name="simulation_list_templates",
        description=(
            "List archived simulation/code templates seeded from domain skills or saved by users. "
            "Use before drafting COMSOL Java/API setup code."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter such as thermal, structural, fluid, or electromagnetic.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of templates to return.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
        },
        handler=simulation_list_templates,
    )

    register_sync(
        name="simulation_read_template",
        description=(
            "Read one archived simulation/code template by exact name, including Java/API seed code "
            "and default parameters."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Template name, e.g. thermal_heat_transfer_seed.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
            "required": ["name"],
        },
        handler=simulation_read_template,
    )

    register_sync(
        name="simulation_search_templates",
        description=(
            "Search archived COMSOL Java/API templates by keyword, domain, code text, "
            "or default parameters. Use this before reading a specific template."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Template search query such as heat flux, Reynolds, voltage, or parameter name.",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain filter such as thermal, structural, fluid, or electromagnetic.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of templates to return.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
            "required": ["query"],
        },
        handler=simulation_search_templates,
    )

    register_sync(
        name="simulation_save_template",
        description=(
            "Save or update a reusable COMSOL Java/API template in the archive, including "
            "optional domain and default parameters."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Stable template name, e.g. custom_thermal_plate_seed.",
                },
                "java_code": {
                    "type": "string",
                    "description": "Reusable COMSOL Java/API seed code.",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain such as thermal, structural, fluid, or electromagnetic.",
                },
                "params": {
                    "type": "object",
                    "description": "Optional default parameter mapping.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
            "required": ["name", "java_code"],
        },
        handler=simulation_save_template,
    )

    register_sync(
        name="simulation_validate_template",
        description=(
            "Validate an archived COMSOL Java/API template or raw Java/API seed code offline "
            "before saving, exporting, or executing it in COMSOL."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Optional archived template name to validate.",
                },
                "java_code": {
                    "type": "string",
                    "description": "Optional raw Java/API code to validate instead of or in addition to an archive record.",
                },
                "params": {
                    "type": "object",
                    "description": "Optional parameter mapping to check against the code.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
        },
        handler=simulation_validate_template,
    )

    register_sync(
        name="simulation_export_template",
        description=(
            "Export an archived COMSOL Java/API template to a local .java seed file for editing, "
            "review, or later execution."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Template name to export.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional output .java path. Defaults to runtime_smoke/templates/<name>.java.",
                },
                "include_params_header": {
                    "type": "boolean",
                    "description": "Whether to include template metadata and params as Java comments.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite an existing output file. Defaults to true.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
            "required": ["name"],
        },
        handler=simulation_export_template,
    )

    register_sync(
        name="simulation_run_template",
        description=(
            "Validate and execute an archived or raw COMSOL Java/API template against an explicitly "
            "selected loaded model or a newly created model, then persist a template_execution artifact."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Optional archived template name to run.",
                },
                "java_code": {
                    "type": "string",
                    "description": "Optional raw Java/API code to run instead of an archive record.",
                },
                "params": {
                    "type": "object",
                    "description": "Optional parameter mapping for validation.",
                },
                "model_name": {
                    "type": "string",
                    "description": "Run against this already loaded model. Mutually exclusive with create_model_name.",
                },
                "create_model_name": {
                    "type": "string",
                    "description": "Create a new empty model with this name before running. Mutually exclusive with model_name.",
                },
                "validate_first": {
                    "type": "boolean",
                    "description": "Whether to reject execution when offline validation reports errors. Defaults to true.",
                },
                "close_model": {
                    "type": "boolean",
                    "description": "Whether to close the target model after execution. Defaults to closing models created by this tool.",
                },
                "persist_results": {
                    "type": "boolean",
                    "description": "Whether to write JSON/manifest artifacts. Defaults to true.",
                },
                "artifact_dir": {
                    "type": "string",
                    "description": "Optional artifact output directory. Defaults to runtime_smoke/template_runs.",
                },
                "artifact_name": {
                    "type": "string",
                    "description": "Optional artifact run-name prefix.",
                },
                "archive_results": {
                    "type": "boolean",
                    "description": "Whether to index artifacts in the archive. Defaults to true.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
        },
        handler=simulation_run_template,
    )

    register_sync(
        name="simulation_list_artifacts",
        description=(
            "List recent archived simulation artifacts such as parameter sweep JSON/CSV records."
        ),
        parameters={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Artifact kind filter. Defaults to parameter_sweep.",
                },
                "model_name": {
                    "type": "string",
                    "description": "Optional exact model name filter.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of artifacts to return.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
        },
        handler=simulation_list_artifacts,
    )

    register_sync(
        name="simulation_search_artifacts",
        description=(
            "Search archived simulation artifacts by run id, model name, source, file path, or metadata."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search text, e.g. a run prefix, model name, or example name.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of artifacts to return.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
            "required": ["query"],
        },
        handler=simulation_search_artifacts,
    )

    register_sync(
        name="simulation_read_artifact",
        description=(
            "Read a compact preview of an archived simulation artifact by run ID. "
            "For sweeps, returns manifest, JSON summary, and CSV rows. For reports, "
            "returns Markdown preview lines."
        ),
        parameters={
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Archived artifact run ID.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum Markdown lines or CSV rows to return. Defaults to 80.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
            "required": ["run_id"],
        },
        handler=simulation_read_artifact,
    )

    register_sync(
        name="simulation_compare_artifacts",
        description=(
            "Compare archived parameter sweep artifacts using their persisted CSV metrics. "
            "Use this to find best/worst cases, compare runs, or summarize parameter effects."
        ),
        parameters={
            "type": "object",
            "properties": {
                "run_ids": {
                    "type": "array",
                    "description": "Optional exact artifact run IDs to compare.",
                },
                "query": {
                    "type": "string",
                    "description": "Optional archive search query used to select artifacts when run_ids are omitted.",
                },
                "metric": {
                    "type": "string",
                    "description": "Numeric CSV metric to rank, such as mean, max, min, value, or solve_elapsed_seconds. Defaults to mean.",
                },
                "expression": {
                    "type": "string",
                    "description": "Optional expression filter, such as T or d(T,x).",
                },
                "direction": {
                    "type": "string",
                    "enum": ["max", "min"],
                    "description": "Whether larger or smaller metric values are better. Defaults to max.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum selected artifacts and ranked rows to return.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
        },
        handler=simulation_compare_artifacts,
    )

    register_sync(
        name="simulation_export_artifact_report",
        description=(
            "Generate a Markdown report from archived simulation artifacts. For parameter "
            "sweeps it compares numeric metrics; for template executions it summarizes "
            "validation/execution outcomes. Use this when the user asks to export, save, "
            "or share a readable experiment report."
        ),
        parameters={
            "type": "object",
            "properties": {
                "run_ids": {
                    "type": "array",
                    "description": "Optional exact artifact run IDs to include.",
                },
                "query": {
                    "type": "string",
                    "description": "Optional archive search query used when run_ids are omitted.",
                },
                "metric": {
                    "type": "string",
                    "description": "Numeric CSV metric to rank, such as mean, max, min, value, or solve_elapsed_seconds. Defaults to mean.",
                },
                "expression": {
                    "type": "string",
                    "description": "Optional expression filter, such as T or d(T,x).",
                },
                "direction": {
                    "type": "string",
                    "enum": ["max", "min"],
                    "description": "Whether larger or smaller metric values are better. Defaults to max.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum selected artifacts and ranked rows to include.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Optional output directory. Defaults to runtime_smoke/reports.",
                },
                "report_name": {
                    "type": "string",
                    "description": "Optional report filename prefix.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional report title.",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["markdown", "html", "both"],
                    "description": "Report output format. Markdown is always archived; html/both also write a self-contained HTML file.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["parameter_sweep", "template_execution"],
                    "description": "Artifact report type. Defaults to parameter_sweep; use template_execution for template run artifacts.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
        },
        handler=simulation_export_artifact_report,
    )

    register_sync(
        name="simulation_rerun_artifact",
        description=(
            "Replay an archived parameter sweep or template execution artifact. Sweeps support "
            "parameter/expression overrides; template executions support params/model target "
            "overrides. Use this when the user asks to rerun, reproduce, or extend a previous artifact."
        ),
        parameters={
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Archived sweep run ID to replay.",
                },
                "parameter_overrides": {
                    "type": "object",
                    "description": "Optional mapping from parameter name to replacement list of values.",
                },
                "expression_overrides": {
                    "type": "array",
                    "description": "Optional replacement list of COMSOL expressions to evaluate.",
                },
                "params_overrides": {
                    "type": "object",
                    "description": "Optional template parameter overrides when replaying a template_execution artifact.",
                },
                "model_name": {
                    "type": "string",
                    "description": "Optional loaded model name when replaying an artifact whose source was a loaded model.",
                },
                "create_model_name": {
                    "type": "string",
                    "description": "Optional new model name when replaying a template_execution artifact by creating a model.",
                },
                "max_cases": {
                    "type": "integer",
                    "description": "Optional safety cap for replayed cases.",
                },
                "validate_first": {
                    "type": "boolean",
                    "description": "Whether to validate template code before replaying a template_execution artifact.",
                },
                "artifact_name": {
                    "type": "string",
                    "description": "Optional prefix for the new replay artifact files.",
                },
                "artifact_dir": {
                    "type": "string",
                    "description": "Optional output directory for replay artifacts.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
                "close_model": {
                    "type": "boolean",
                    "description": "Whether to close the replayed model afterward. Defaults to the sweep tool behavior.",
                },
            },
            "required": ["run_id"],
        },
        handler=simulation_rerun_artifact,
    )

    register_sync(
        name="simulation_run_example_model",
        description=(
            "Run a built-in COMSOL example model through load, summary, solve, evaluate, "
            "and optional close using the real local COMSOL runtime."
        ),
        parameters={
            "type": "object",
            "properties": {
                "example_name": {
                    "type": "string",
                    "description": "Example name. Defaults to thermal_slab.",
                    "enum": ["thermal_slab", "thermal_heat_sink"],
                },
                "expression": {
                    "type": "string",
                    "description": "Optional COMSOL expression to evaluate. Defaults to the example's expression.",
                },
                "expressions": {
                    "type": "array",
                    "description": "Optional list of COMSOL expressions to evaluate after solving.",
                },
                "parameters": {
                    "type": "object",
                    "description": "Optional mapping of parameter names to values with units to set before solving.",
                },
                "study_name": {
                    "type": "string",
                    "description": "Optional study tag/name to solve.",
                },
                "solve": {
                    "type": "boolean",
                    "description": "Whether to solve before evaluating. Defaults to true.",
                },
                "close_model": {
                    "type": "boolean",
                    "description": "Whether to close the loaded model afterward. Defaults to true.",
                },
            },
        },
        handler=simulation_run_example_model,
    )

    register_sync(
        name="simulation_run_parameter_sweep",
        description=(
            "Execute a bounded COMSOL parameter sweep on a loaded model, a built-in example, "
            "or a .mph file. For each expanded case, set parameters, optionally solve, "
            "and evaluate requested expressions with compact statistics."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model_name": {
                    "type": "string",
                    "description": "Name of an already loaded model. Use exactly one of model_name, example_name, or model_file.",
                },
                "example_name": {
                    "type": "string",
                    "description": "Built-in example name. Use exactly one of model_name, example_name, or model_file.",
                    "enum": ["thermal_slab", "thermal_heat_sink"],
                },
                "model_file": {
                    "type": "string",
                    "description": "Path to a .mph file. Use exactly one of model_name, example_name, or model_file.",
                },
                "parameters": {
                    "type": "object",
                    "description": "Mapping from parameter name to list of values with units, e.g. {'L': ['1[mm]', '2[mm]']}.",
                },
                "expression": {
                    "type": "string",
                    "description": "Optional single COMSOL expression to evaluate after each solve.",
                },
                "expressions": {
                    "type": "array",
                    "description": "Optional list of COMSOL expressions to evaluate after each solve.",
                },
                "study_name": {
                    "type": "string",
                    "description": "Optional study tag/name to solve.",
                },
                "max_cases": {
                    "type": "integer",
                    "description": "Maximum number of cases to execute. Defaults to 25.",
                },
                "solve": {
                    "type": "boolean",
                    "description": "Whether to solve after setting each case. Defaults to true.",
                },
                "close_model": {
                    "type": "boolean",
                    "description": "Whether to close the model afterward. Defaults to true for models loaded by this tool and false for existing loaded models.",
                },
                "persist_results": {
                    "type": "boolean",
                    "description": "Whether to write JSON/CSV/manifest artifacts for the sweep. Defaults to true.",
                },
                "artifact_dir": {
                    "type": "string",
                    "description": "Optional output directory for artifacts. Defaults to runtime_smoke/sweeps.",
                },
                "artifact_name": {
                    "type": "string",
                    "description": "Optional run name prefix used in artifact filenames.",
                },
                "archive_results": {
                    "type": "boolean",
                    "description": "Whether to index persisted artifacts in the SQLite archive. Defaults to true.",
                },
                "archive_path": {
                    "type": "string",
                    "description": "Optional archive SQLite path. Defaults to ~/.comsol_agent/archive/archive.sqlite3.",
                },
            },
            "required": ["parameters"],
        },
        handler=simulation_run_parameter_sweep,
    )
