"""Provider interfaces for meetup."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class AgentConfig:
    name: str
    role: str
    provider: str
    endpoint: Optional[str] = None
    auth_env: Optional[str] = None
    model: Optional[str] = None
    extra_headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class AgentResponse:
    agent: str
    text: str


class AgentProvider:
    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        raise NotImplementedError

    def list_models(self, token: Optional[str]) -> list[str]:
        return []
