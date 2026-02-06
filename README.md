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

## Notes
- No API keys are stored in the repo. Use environment variables or a keys JSON file referenced by `--keys`.
- `mock` provider is included for dry runs.
