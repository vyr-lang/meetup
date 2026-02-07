"""Grok provider implementation."""

from typing import Any, Dict, Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


class GrokProvider(AgentProvider):
    def __init__(self) -> None:
        self._chats: Dict[str, Any] = {}

    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not token:
            raise RuntimeError(
                f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
            )

        try:
            from xai_sdk import Client
            from xai_sdk.chat import user
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
        return AgentResponse(agent=agent.name, text=content.strip())
