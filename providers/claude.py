"""Claude provider implementation."""

from typing import Dict, List, Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


class ClaudeProvider(AgentProvider):
    def __init__(self) -> None:
        self._history: Dict[str, List[Dict[str, str]]] = {}

    def list_models(self, token: Optional[str]) -> list[str]:
        if not token:
            raise RuntimeError("Missing auth token for Claude model listing.")
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "anthropic is required for the Claude provider. Install in the venv with: "
                "/home/zos/meetup/.venv/bin/python -m pip install anthropic"
            ) from exc
        client = anthropic.Anthropic(api_key=token)
        try:
            models_api = getattr(client, "models", None)
            if models_api and hasattr(models_api, "list"):
                response = models_api.list()
                models = []
                for item in getattr(response, "data", []) or []:
                    model_id = getattr(item, "id", None)
                    if isinstance(model_id, str):
                        models.append(model_id)
                    elif isinstance(item, dict) and isinstance(item.get("id"), str):
                        models.append(item["id"])
                return sorted(set(models))
        except Exception:
            return []
        return []

    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not token:
            raise RuntimeError(
                f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
            )

        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "anthropic is required for the Claude provider. Install in the venv with: "
                "/home/zos/meetup/.venv/bin/python -m pip install anthropic"
            ) from exc

        model = agent.model or "claude-opus-4-6"
        supported_web_search = {
            "claude-opus-4-1-20250805",
            "claude-opus-4-20250514",
            "claude-opus-4-5-20251101",
            "claude-sonnet-4-20250514",
            "claude-sonnet-4-5-20250929",
            "claude-3-7-sonnet-20250219",
            "claude-3-5-haiku-latest",
            "claude-haiku-4-5-20251001",
        }
        if model not in supported_web_search:
            print(
                f"[warn] Claude web_search may not be supported for model '{model}'.",
                flush=True,
            )
        client = anthropic.Anthropic(
            api_key=token,
            default_headers={"anthropic-beta": "web-fetch-2025-09-10"},
        )
        history = self._history.setdefault(agent.name, [])
        history.append({"role": "user", "content": prompt})
        response = client.messages.create(
            model=model,
            max_tokens=5000,
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5,
                },
                {
                    "type": "web_fetch_20250910",
                    "name": "web_fetch",
                    "max_uses": 5,
                },
            ],
            messages=history,
        )
        text = ""
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text":
                text += getattr(block, "text", "")
        if text:
            history.append({"role": "assistant", "content": text})
        return AgentResponse(agent=agent.name, text=text.strip())
