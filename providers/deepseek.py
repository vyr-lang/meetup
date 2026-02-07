"""DeepSeek provider implementation."""

from typing import Dict, List, Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


class DeepSeekProvider(AgentProvider):
    def __init__(self) -> None:
        self._history: Dict[str, List[Dict[str, str]]] = {}

    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not token:
            raise RuntimeError(
                f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "openai is required for the DeepSeek provider. Install in the venv with: "
                "/home/zos/meetup/.venv/bin/python -m pip install openai"
            ) from exc

        model = agent.model or "deepseek-chat"
        history = self._history.setdefault(agent.name, [])
        history.append({"role": "user", "content": prompt})

        client = OpenAI(api_key=token, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model=model,
            messages=history,
            stream=False,
        )
        content = response.choices[0].message.content if response.choices else ""
        if content:
            history.append({"role": "assistant", "content": content})
        return AgentResponse(agent=agent.name, text=content.strip())
