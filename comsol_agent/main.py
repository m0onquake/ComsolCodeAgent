"""Entry point for the COMSOL Agent CLI.

Usage:
    comsol-agent                    # Start interactive REPL
    comsol-agent --config <path>    # Use custom config file
    comsol-agent --version          # Show version
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from comsol_agent import __version__


@click.command()
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a custom config.yaml file.",
)
@click.option(
    "--provider",
    "-p",
    help="LLM provider: 'openai' or 'anthropic'.",
)
@click.option(
    "--model",
    "-m",
    help="Model name (e.g. 'gpt-4o', 'claude-sonnet-4-20250514').",
)
@click.option(
    "--version",
    "-v",
    "show_version",
    is_flag=True,
    help="Show version and exit.",
)
def main(
    config_path: Path | None,
    provider: str | None,
    model: str | None,
    show_version: bool,
) -> None:
    """COMSOL Agent — AI-powered simulation assistant.

    An interactive CLI agent that helps you create, modify, and run
    COMSOL Multiphysics simulations using natural language.
    """
    if show_version:
        click.echo(f"COMSOL Agent v{__version__}")
        return

    # Load config
    from comsol_agent.cli.config import Config, load_config

    if config_path:
        config = load_config(config_path)
    else:
        config = load_config()

    # CLI overrides
    if provider:
        config.llm.provider = provider
    if model:
        config.llm.model = model

    # Run the CLI app
    from comsol_agent.cli.app import CLIApp

    app = CLIApp(config)

    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        # Handled gracefully in the REPL
        pass
    finally:
        asyncio.run(app.stop())


if __name__ == "__main__":
    main()
