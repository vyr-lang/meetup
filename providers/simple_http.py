"""Simple HTTP provider implementation."""

import json
import urllib.error
import urllib.request
from typing import Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


class SimpleHttpProvider(AgentProvider):
    def list_models(self, token: Optional[str]) -> list[str]:
        return []

    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not agent.endpoint:
            raise ValueError(f"Agent {agent.name} is missing endpoint")

        payload = {
            "prompt": prompt,
            "agent": agent.name,
            "role": agent.role,
            "model": agent.model,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        headers.update(agent.extra_headers or {})

        if agent.auth_env:
            if not token:
                raise RuntimeError(
                    f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
                )
            headers["Authorization"] = f"Bearer {token}"

        request = urllib.request.Request(agent.endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP error from {agent.endpoint}: {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to reach {agent.endpoint}: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return AgentResponse(agent=agent.name, text=body.strip())

        text = parsed.get("text") or parsed.get("response") or ""
        return AgentResponse(agent=agent.name, text=str(text).strip())
