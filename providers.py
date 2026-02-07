"""Provider implementations for meetup."""

from __future__ import annotations

import json
import textwrap
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse


class SimpleHttpProvider(AgentProvider):
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


class MockProvider(AgentProvider):
    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        text = textwrap.dedent(
            f"""
            RAISE: yes
            {agent.name} acknowledges the prompt and offers a concise, placeholder response.
            """
        ).strip()
        return AgentResponse(agent=agent.name, text=text)


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


class ClaudeProvider(AgentProvider):
    def __init__(self) -> None:
        self._history: Dict[str, List[Dict[str, str]]] = {}

    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not token:
            raise RuntimeError(
                f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
            )

        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "anthropic is required for the Claude provider. Install in the venv with: "
                "/home/zos/meetup/.venv/bin/python -m pip install anthropic"
            ) from exc

        model = agent.model or "claude-opus-4-6"
        supported_web_search = {
            "claude-opus-4-1-20250805",
            "claude-opus-4-20250514",
            "claude-opus-4-5-20251101",
            "claude-sonnet-4-20250514",
            "claude-sonnet-4-5-20250929",
            "claude-3-7-sonnet-20250219",
            "claude-3-5-haiku-latest",
            "claude-haiku-4-5-20251001",
        }
        if model not in supported_web_search:
            print(
                f"[warn] Claude web_search may not be supported for model '{model}'.",
                flush=True,
            )
        client = anthropic.Anthropic(
            api_key=token,
            default_headers={"anthropic-beta": "web-fetch-2025-09-10"},
        )
        history = self._history.setdefault(agent.name, [])
        history.append({"role": "user", "content": prompt})
        response = client.messages.create(
            model=model,
            max_tokens=500,
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5,
                },
                {
                    "type": "web_fetch_20250910",
                    "name": "web_fetch",
                    "max_uses": 5,
                },
            ],
            messages=history,
        )
        text = ""
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text":
                text += getattr(block, "text", "")
        if text:
            history.append({"role": "assistant", "content": text})
        return AgentResponse(agent=agent.name, text=text.strip())


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


def extract_gemini_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.strip()
    return ""


def extract_openai_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text.strip()
    return ""


PROVIDERS: Dict[str, AgentProvider] = {
    "simple_http": SimpleHttpProvider(),
    "openai": OpenAIProvider(),
    "gemini": GeminiProvider(),
    "grok": GrokProvider(),
    "claude": ClaudeProvider(),
    "deepseek": DeepSeekProvider(),
    "mistral": MistralProvider(),
    "mock": MockProvider(),
}
