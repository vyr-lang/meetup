# meetup
Meetup runs a virtual meeting between AI agents to discuss a Vyr mailing.

## What it does
- Loads agents from a JSON config file (no secrets committed)
- Runs an agenda-driven meeting with hand-raise coordination
- Produces meeting notes as a Markdown transcript

## Setup
1. Copy and edit the example config: `agents.example.json`
2. Provide tokens via a JSON keys file or environment variables
3. Create an agenda file (one item per line)

## Run
```bash
python3 meetup.py --mailing M0001 --agents agents.example.json --agenda agenda.example.txt --notes meeting-notes.md --keys /path/to/keys.json
```

## Agent API expectations
The default `simple_http` provider sends a POST request to each agent's endpoint with JSON:
```json
{
  "prompt": "...",
  "agent": "Agent Name",
  "role": "participant",
  "model": "model-id"
}
```
It expects a JSON response with a `text` or `response` field. If a response is not JSON, the raw body is used as text.

## OpenAI provider
Use `"provider": "openai"` with `"model": "gpt-5.2"` (or another OpenAI model). The token can come from `--keys`
using the agent name (e.g., `"ChatGPT 5.2"`) or from `OPENAI_API_KEY`. Uses the official OpenAI Python SDK.
Conversation state is chained via `previous_response_id`.
Web search is enabled by default via the Responses API `web_search` tool.

## Gemini provider
Use `"provider": "gemini"` with `"model": "gemini-3-pro-preview"` (or another Gemini model). The token can come from
`--keys` using the agent name (e.g., `"Gemini 3 Pro"`) or from `GEMINI_API_KEY`. Uses the official Google Gen AI SDK.
Gemini chat sessions retain history but still send full history each turn.
Google Search grounding and URL Context fetching are enabled by default via `google_search` and `url_context` tools.

## Grok provider
Use `"provider": "grok"` with `"model": "grok-4-latest"` (or another Grok model). The token can come from `--keys`
using the agent name (e.g., `"Grok 4"`) or from `XAI_API_KEY`. Requires `xai-sdk` installed in the venv:
`/home/zos/meetup/.venv/bin/python -m pip install xai-sdk`.
Web search is enabled by default via the xAI `web_search` tool.

## Claude provider
Use `"provider": "claude"` with `"model": "claude-opus-4-6"` (or another Claude model). The token can come from
`--keys` using the agent name (e.g., `"Claude"`) or from `ANTHROPIC_API_KEY`. Requires `anthropic` installed in the venv:
`/home/zos/meetup/.venv/bin/python -m pip install anthropic`.
Web search is enabled by default via the Claude `web_search` tool, but it only works for supported models and requires
org-level enablement in Anthropic Console.

## Notes
- No API keys are stored in the repo. Use environment variables or a keys JSON file referenced by `--keys`.
- `mock` provider is included for dry runs.
