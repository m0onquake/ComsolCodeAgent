# COMSOL Agent

新架构的 COMSOL 生成式仿真智能体。

AI-powered code agent for automated COMSOL Multiphysics simulation workflows.

## Overview

COMSOL Agent is an interactive CLI tool that enables engineers and researchers to create, modify, and run COMSOL Multiphysics simulations using natural language. It combines LLM-powered code generation with direct COMSOL API integration.

### Key Features (MVP)

- 🗣️ **Natural Language Interface** — Describe your simulation in plain language
- 🔧 **COMSOL Integration** — Automatically loads, modifies, solves, and evaluates COMSOL models via MPh
- 🛠️ **Tool-based Architecture** — Agent uses specialized tools for each COMSOL operation
- 💬 **Conversational Memory** — Maintains context across multiple turns
- 🎨 **Rich Terminal UI** — Codex-like interface with syntax highlighting and status indicators
- 🖥️ **Local Showcase UI** — FastAPI/SSE dashboard for recorded demos and live Agent runs

### Roadmap

- **Phase 2**: Self-healing (auto-debug and repair), Long-term memory, Context compression
- **Phase 3**: RAG (COMSOL API docs), Parameter sweeps, Skills system
- **Phase 4**: Local model support, Web UI, Production packaging

Current development status and the next engineering plan are recorded in
[`docs/development_progress_roadmap.md`](docs/development_progress_roadmap.md).

## Installation

### Prerequisites

1. **Python 3.11+**
2. **COMSOL Multiphysics 5.6–6.3** installed and licensed
3. **LLM API key** (OpenAI or Anthropic)

### Install

```bash
pip install -e .
```

### Configure

Set your API key:

```bash
export OPENAI_API_KEY='sk-...'
# or
export ANTHROPIC_API_KEY='sk-ant-...'
```

Optional: Create `~/.comsol_agent/config.yaml`:

```yaml
llm:
  provider: openai
  model: gpt-4o

comsol:
  version: "6.2"
```

## Usage

```bash
# Start interactive REPL
comsol-agent

# With custom model
comsol-agent --provider openai --model gpt-4o

# Show help inside the REPL
> /help

# Runtime checks
> /doctor
> /doctor --deep

# Inspect saved sessions and artifacts inside the REPL
> /templates
> /templates search heat thermal
> /templates show thermal_heat_transfer_seed
> /templates validate thermal_heat_transfer_seed
> /templates run thermal_heat_transfer_seed create template_smoke_model
> /templates export thermal_heat_transfer_seed runtime_smoke/templates/thermal_heat_transfer_seed.java
> /templates save custom_thermal thermal runtime_smoke/templates/custom_thermal.java
> /sessions
> /sessions show session_20260608_194443_628426
> /sessions show session_20260608_194443_628426 50
> /archive export runtime_smoke/archive_exports/latest.json 100 timelines
> /archive cleanup 100
> /artifacts
> /artifacts report agent_sweep_smoke mean T max html
```

### Web showcase

The repository includes a local presentation UI with two modes:

- **Case replay** uses the existing strict 12-roller COMSOL artifacts under
  `runtime_smoke/` and completes deterministically for screen recording.
- **Live run** sends the requirement to the same `AgentLoop` used by the CLI and
  streams tool calls, results, generated code, images, and audit artifacts over SSE.

```bash
pip install -e '.[web]'
comsol-agent-web
```

Open <http://127.0.0.1:7860>. Set `COMSOL_AGENT_WEB_DEMO_DELAY=0` for an
instant replay, or `COMSOL_AGENT_WEB_AUTOSTART_COMSOL=0` when demonstrating a
live LLM conversation without starting COMSOL automatically.

### Example Session

```
> Load the heat_sink.mph model and tell me about it

🤖 Let me load that model for you...

  ↳ comsol_load_model(filepath='heat_sink.mph')
  ✅ Model loaded: heat_sink

  This model contains:
  - Geometry: heat_sink_geom (aluminum heat sink)
  - Physics: Heat Transfer in Solids
  - Study: Stationary thermal analysis
  - Parameters: power=10[W], T_ambient=25[degC]

> Change the power to 50W and solve

🤖 Updating parameter and running the study...

  ↳ comsol_set_parameter(model_name='heat_sink', parameter_name='power', value='50[W]')
  ↳ comsol_solve(model_name='heat_sink')
  ✅ Solved in 2.1s

  Maximum temperature: 87.3°C (was 42.1°C at 10W)
  Temperature distribution is within safe operating range.
```

## Architecture

```
User Input → [CLI/REPL] → Agent Loop → LLM → Tool Calls → COMSOL (MPh)
                ↑              ↓                          ↓
                └── Rich Output ←── Response ←── Results ─┘
```

## Project Structure

```
comsol_agent/
├── cli/           # CLI interface (REPL, rendering, config)
├── agent/         # Agent loop, prompt, tool registry
├── tools/         # Tool implementations (COMSOL, file, shell)
│   └── comsol/    # COMSOL-specific tools (MPh integration)
├── llm/           # LLM provider abstraction (OpenAI, Anthropic)
├── memory/        # Memory system (Phase 2)
├── repair/        # Self-healing system (Phase 2)
├── simulation/    # Domain knowledge, templates, RAG
└── utils/         # Token counting, logging, sandbox
```

## License

MIT
