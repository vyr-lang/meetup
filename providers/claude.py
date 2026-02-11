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
        client = anthropic.Anthropic(
            api_key=token,
            default_headers={"anthropic-beta": "web-fetch-2025-09-10"},
        )
        history = self._history.setdefault(agent.name, [])
        history.append({"role": "user", "content": prompt})
        text = ""
        with client.messages.stream(
            model=model,
            max_tokens=50000,
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
        ) as stream:
            for chunk in stream.text_stream:
                text += chunk
            _ = stream.get_final_message()
        if text:
            history.append({"role": "assistant", "content": text})
        return AgentResponse(agent=agent.name, text=text.strip())
