# LLM API Setup

This project can talk to any OpenAI-compatible chat-completions endpoint.
Use the local mock server first to verify request wiring, then switch to a
real provider such as DeepSeek.

## Local mock server

Start a deterministic local OpenAI-compatible endpoint:

```bash
python3 -m comsol_agent.dev.mock_llm_server --port 8008
```

Configure the CLI to use it:

```bash
export COMSOL_AGENT_PROVIDER=openai
export COMSOL_AGENT_MODEL=mock-llm
export OPENAI_API_KEY=mock
export COMSOL_AGENT_BASE_URL=http://127.0.0.1:8008/v1
python3 -m comsol_agent.main
```

The server accepts:

- `GET /health`
- `GET /v1/health`
- `POST /chat/completions`
- `POST /v1/chat/completions`

It returns a deterministic assistant message and token-usage fields. It does
not stream responses and does not generate real tool calls.

## DeepSeek

DeepSeek is supported through the OpenAI-compatible provider path:

```bash
export COMSOL_AGENT_PROVIDER=deepseek
export COMSOL_AGENT_MODEL=deepseek-v4-flash
export DEEPSEEK_API_KEY=sk-...
python3 -m comsol_agent.main
```

Optional custom endpoint:

```bash
export DEEPSEEK_BASE_URL=https://api.deepseek.com
```

Run a small smoke test before starting the interactive CLI:

```bash
python3 scripts/test_deepseek_api.py
```

Do not write real API keys into source files, docs, shell scripts, or committed
configuration. Prefer a fresh key stored only in the shell environment.

For mock-compatible testing with the DeepSeek provider name:

```bash
export COMSOL_AGENT_PROVIDER=deepseek
export COMSOL_AGENT_MODEL=deepseek-v4-flash
export DEEPSEEK_API_KEY=mock
export COMSOL_AGENT_BASE_URL=http://127.0.0.1:8008/v1
```

`COMSOL_AGENT_BASE_URL` overrides the provider endpoint and is useful for
local gateways, proxies, and API record/replay services.
