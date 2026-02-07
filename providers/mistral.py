"""Mistral provider implementation."""

from typing import Dict, List, Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


class MistralProvider(AgentProvider):
    def __init__(self) -> None:
        self._histories: Dict[str, List[Dict[str, str]]] = {}

    def list_models(self, token: Optional[str]) -> list[str]:
        if not token:
            raise RuntimeError("Missing auth token for Mistral model listing.")
        try:
            from mistralai import Mistral
        except ImportError as exc:
            raise RuntimeError(
                "mistralai is required for the Mistral provider. Install in the venv with: "
                "/home/zos/meetup/.venv/bin/python -m pip install mistralai"
            ) from exc
        client = Mistral(api_key=token)
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

    @staticmethod
    def _extract_text(response) -> str:
        if hasattr(response, "model_dump"):
            data = response.model_dump()
        else:
            data = getattr(response, "__dict__", {}) or {}

        choices = data.get("choices") or []
        if choices:
            choice0 = choices[0] or {}
            message = choice0.get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: List[str] = []
                for chunk in content:
                    if isinstance(chunk, dict):
                        if "text" in chunk and isinstance(chunk["text"], str):
                            parts.append(chunk["text"])
                        elif chunk.get("type") == "text" and isinstance(chunk.get("text"), str):
                            parts.append(chunk["text"])
                return "".join(parts).strip()

        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text.strip()

        return ""

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

        history = self._histories.setdefault(agent.name, [])
        history.append({"role": "user", "content": prompt})

        response = client.chat.complete(
            model=model,
            messages=history,
        )

        text = self._extract_text(response)
        if text:
            history.append({"role": "assistant", "content": text})

        return AgentResponse(agent=agent.name, text=text.strip())
