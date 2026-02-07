"""Mock provider implementation."""

import textwrap
from typing import Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


class MockProvider(AgentProvider):
    def list_models(self, token: Optional[str]) -> list[str]:
        return []

    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        text = textwrap.dedent(
            f"""
            RAISE: yes
            {agent.name} acknowledges the prompt and offers a concise, placeholder response.
            """
        ).strip()
        return AgentResponse(agent=agent.name, text=text)
