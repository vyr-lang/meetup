"""Grok provider implementation."""

from typing import Any, Dict, Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


class GrokProvider(AgentProvider):
    def __init__(self) -> None:
        self._chats: Dict[str, Any] = {}

    def list_models(self, token: Optional[str]) -> list[str]:
        if not token:
            raise RuntimeError("Missing auth token for Grok model listing.")
        try:
            from xai_sdk import Client
        except ImportError as exc:
            raise RuntimeError(
                "xai-sdk is required for Grok. Install it in the venv with: "
                "/home/zos/meetup/.venv/bin/python -m pip install xai-sdk"
            ) from exc
        client = Client(api_key=token, timeout=30)
        models = []
        try:
            models_api = getattr(client, "models", None)
            if models_api and hasattr(models_api, "list"):
                response = models_api.list()
                for item in getattr(response, "data", []) or []:
                    model_id = getattr(item, "id", None)
                    if isinstance(model_id, str):
                        models.append(model_id)
                    elif isinstance(item, dict) and isinstance(item.get("id"), str):
                        models.append(item["id"])
        except Exception:
            return []
        return sorted(set(models))

    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not token:
            raise RuntimeError(
                f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
            )

        try:
            from xai_sdk import Client
            from xai_sdk.chat import assistant, user
            from xai_sdk.tools import web_search
        except ImportError as exc:
            raise RuntimeError(
                "xai-sdk is required for Grok. Install it in the venv with: "
                "/home/zos/meetup/.venv/bin/python -m pip install xai-sdk"
            ) from exc

        model = agent.model or "grok-4-latest"
        chat = self._chats.get(agent.name)
        if chat is None:
            client = Client(api_key=token, timeout=300)
            chat = client.chat.create(model=model, tools=[web_search()])
            self._chats[agent.name] = chat
        chat.append(user(prompt))
        response = chat.sample()

        content = getattr(response, "content", "") or ""
        if content:
            chat.append(assistant(content))
        return AgentResponse(agent=agent.name, text=content.strip())
