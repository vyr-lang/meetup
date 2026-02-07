"""Gemini provider implementation."""

from typing import Any, Dict, Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


def extract_gemini_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.strip()
    return ""


class GeminiProvider(AgentProvider):
    def __init__(self) -> None:
        self._chats: Dict[str, Any] = {}
        self._client: Optional[Any] = None

    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not token:
            raise RuntimeError(
                f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "google-genai is required for the Gemini provider. Install in the venv with: "
                "/home/zos/meetup/.venv/bin/python -m pip install google-genai"
            ) from exc

        model = agent.model or "gemini-3-pro-preview"
        if self._client is None:
            self._client = genai.Client(api_key=token)
        client = self._client
        chat = self._chats.get(agent.name)
        if chat is None:
            chat = client.chats.create(model=model)
            self._chats[agent.name] = chat
        response = chat.send_message(
            prompt,
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(google_search=types.GoogleSearch()),
                    types.Tool(url_context=types.UrlContext()),
                ]
            ),
        )
        text = extract_gemini_text(response)
        return AgentResponse(agent=agent.name, text=text)
