"""OpenAI provider implementation."""

from typing import Dict, Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


def extract_openai_text(response) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text.strip()
    return ""


class OpenAIProvider(AgentProvider):
    def __init__(self) -> None:
        self._previous_response_ids: Dict[str, str] = {}

    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not token:
            raise RuntimeError(
                f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai is required for the OpenAI provider. Install in the venv with: "
                "/home/zos/meetup/.venv/bin/python -m pip install openai"
            ) from exc

        model = agent.model or "gpt-5.2"
        client = OpenAI(api_key=token)
        previous_response_id = self._previous_response_ids.get(agent.name)
        response = client.responses.create(
            model=model,
            input=prompt,
            previous_response_id=previous_response_id,
            tools=[{"type": "web_search"}],
        )
        if getattr(response, "id", None):
            self._previous_response_ids[agent.name] = response.id
        text = extract_openai_text(response)
        return AgentResponse(agent=agent.name, text=text)
