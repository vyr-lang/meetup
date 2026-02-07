"""Mistral provider implementation."""

from typing import Dict, Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


class MistralProvider(AgentProvider):
    def __init__(self) -> None:
        self._conversation_ids: Dict[str, str] = {}

    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not token:
            raise RuntimeError(
                f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
            )

        try:
            from mistralai import Mistral
        except ImportError as exc:
            raise RuntimeError(
                "mistralai is required for the Mistral provider. Install in the venv with: "
                "/home/zos/meetup/.venv/bin/python -m pip install mistralai"
            ) from exc

        model = agent.model or "mistral-medium-2505"
        client = Mistral(api_key=token)

        conv_id = self._conversation_ids.get(agent.name)
        if conv_id:
            response = client.beta.conversations.append(
                conversation_id=conv_id,
                inputs=prompt,
            )
        else:
            response = client.beta.conversations.start(
                model=model,
                inputs=prompt,
                tools=[{"type": "web_search"}],
            )
            conv_id = getattr(response, "conversation_id", None)
            if conv_id:
                self._conversation_ids[agent.name] = conv_id

        text = ""
        outputs = getattr(response, "outputs", None)
        if outputs is None and hasattr(response, "model_dump"):
            outputs = response.model_dump().get("outputs", [])
        for entry in outputs or []:
            if isinstance(entry, dict) and entry.get("type") == "message.output":
                for chunk in entry.get("content", []) or []:
                    if isinstance(chunk, dict) and chunk.get("type") == "text":
                        text += chunk.get("text", "")
        return AgentResponse(agent=agent.name, text=text.strip())
