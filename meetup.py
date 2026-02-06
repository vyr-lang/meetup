#!/usr/bin/env python3
"""Virtual meeting runner for Vyr mailings."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


HAND_RAISE_PATTERN = re.compile(r"\braise\s*:\s*(yes|no)\b", re.IGNORECASE)


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


@dataclass
class MeetingContext:
    mailing_id: str
    agenda: List[str]
    chair: str
    notes_path: str
    context_limit: int
    seed: Optional[int]


class AgentProvider:
    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        raise NotImplementedError


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
                f\"[warn] Claude web_search may not be supported for model '{model}'.\",
                flush=True,
            )
        client = anthropic.Anthropic(
            api_key=token,
            default_headers={"anthropic-beta": "web-fetch-2025-09-10"},
        )
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
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text":
                text += getattr(block, "text", "")
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
    "mock": MockProvider(),
}


def load_agents(path: str) -> List[AgentConfig]:
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    agents: List[AgentConfig] = []
    for entry in raw.get("agents", []):
        agents.append(
            AgentConfig(
                name=entry["name"],
                role=entry.get("role", "participant"),
                provider=entry.get("provider", "simple_http"),
                endpoint=entry.get("endpoint"),
                auth_env=entry.get("auth_env"),
                model=entry.get("model"),
                extra_headers=entry.get("extra_headers", {}),
            )
        )
    return agents


def resolve_chair(agents: List[AgentConfig], chair: Optional[str]) -> str:
    if chair:
        return chair
    for agent in agents:
        if agent.role.lower() == "chair":
            return agent.name
    return agents[0].name if agents else "chair"


def build_context_log(messages: List[Dict[str, str]], limit: int) -> str:
    if limit <= 0:
        return ""
    tail = messages[-limit:]
    return "\n".join(f"{m['speaker']}: {m['text']}" for m in tail)


def ask_hand_raise(
    provider: AgentProvider,
    agent: AgentConfig,
    ctx: MeetingContext,
    agenda_item: str,
    log: str,
    token: Optional[str],
) -> bool:
    print(f"[debug] calling {agent.name} for hand-raise", flush=True)
    prompt = textwrap.dedent(
        f"""
        You are {agent.name}, a participant in the Vyr meeting for {ctx.mailing_id}.
        Agenda item: {agenda_item}

        Respond with:
        - A line 'RAISE: yes' or 'RAISE: no'
        - One sentence why you should or should not speak.

        Recent context:
        {log}
        """
    ).strip()
    response = provider.request(agent, prompt, token)
    print(f"[debug] completed hand-raise for {agent.name}", flush=True)
    match = HAND_RAISE_PATTERN.search(response.text)
    return bool(match and match.group(1).lower() == "yes")


def ask_to_speak(
    provider: AgentProvider,
    agent: AgentConfig,
    ctx: MeetingContext,
    agenda_item: str,
    log: str,
    token: Optional[str],
) -> AgentResponse:
    print(f"[debug] calling {agent.name} to speak", flush=True)
    prompt = textwrap.dedent(
        f"""
        You are {agent.name}, a participant in the Vyr meeting for {ctx.mailing_id}.
        Agenda item: {agenda_item}

        Speak concisely (max 180 words). Provide concrete points and, if applicable, cite paper numbers.

        Recent context:
        {log}
        """
    ).strip()
    response = provider.request(agent, prompt, token)
    print(f"[debug] completed response from {agent.name}", flush=True)
    return response


def chair_summary(
    provider: AgentProvider,
    chair: AgentConfig,
    ctx: MeetingContext,
    agenda_item: str,
    log: str,
    token: Optional[str],
) -> AgentResponse:
    print(f"[debug] calling {chair.name} for chair summary", flush=True)
    prompt = textwrap.dedent(
        f"""
        You are {chair.name}, chairing the Vyr meeting for {ctx.mailing_id}.
        Agenda item: {agenda_item}

        Summarize the discussion in 5-8 bullet points. Note decisions, open questions, and action items.

        Recent context:
        {log}
        """
    ).strip()
    response = provider.request(chair, prompt, token)
    print(f"[debug] completed chair summary for {chair.name}", flush=True)
    return response


def write_notes(path: str, ctx: MeetingContext, messages: List[Dict[str, str]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"# Meeting Notes — {ctx.mailing_id}\n\n")
        handle.write(f"Date: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        handle.write("## Agenda\n")
        for item in ctx.agenda:
            handle.write(f"- {item}\n")
        handle.write("\n## Transcript\n")
        for msg in messages:
            handle.write(f"\n### {msg['speaker']}\n")
            handle.write(f"{msg['text']}\n")


def load_tokens(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    tokens = raw.get("tokens", {})
    if not isinstance(tokens, dict):
        raise ValueError("keys file must contain a 'tokens' object")
    return {str(k): str(v) for k, v in tokens.items()}


def resolve_token(agent: AgentConfig, tokens: Dict[str, str]) -> Optional[str]:
    if agent.name in tokens:
        return tokens[agent.name]
    if agent.provider == "openai" and "ChatGPT" in tokens:
        return tokens["ChatGPT"]
    if agent.provider == "gemini" and "Gemini" in tokens:
        return tokens["Gemini"]
    if agent.provider == "grok" and "Grok" in tokens:
        return tokens["Grok"]
    if agent.provider == "claude" and "Claude" in tokens:
        return tokens["Claude"]
    if agent.auth_env:
        return os.environ.get(agent.auth_env)
    return None


def run_meeting(ctx: MeetingContext, agents: List[AgentConfig], tokens: Dict[str, str]) -> None:
    if not agents:
        raise RuntimeError("No agents configured.")

    provider_map = {name: PROVIDERS[name] for name in PROVIDERS}
    messages: List[Dict[str, str]] = []

    chair_name = ctx.chair
    chair_agent = next((a for a in agents if a.name == chair_name), agents[0])

    if ctx.seed is not None:
        random.seed(ctx.seed)

    for agenda_item in ctx.agenda:
        print(f"\n=== Agenda Item ===\n{agenda_item}\n", flush=True)
        log = build_context_log(messages, ctx.context_limit)
        raised: List[AgentConfig] = []
        for agent in agents:
            provider = provider_map.get(agent.provider)
            if not provider:
                raise RuntimeError(f"Unknown provider: {agent.provider}")
            if agent.name == chair_name:
                continue
            token = resolve_token(agent, tokens)
            if ask_hand_raise(provider, agent, ctx, agenda_item, log, token):
                raised.append(agent)

        if not raised:
            raised = [agent for agent in agents if agent.name != chair_name]

        for agent in raised:
            provider = provider_map[agent.provider]
            token = resolve_token(agent, tokens)
            response = ask_to_speak(provider, agent, ctx, agenda_item, log, token)
            messages.append({"speaker": agent.name, "text": response.text})
            print(f"\n[{agent.name}]\n{response.text}\n", flush=True)
            log = build_context_log(messages, ctx.context_limit)

        chair_provider = provider_map[chair_agent.provider]
        chair_token = resolve_token(chair_agent, tokens)
        summary = chair_summary(chair_provider, chair_agent, ctx, agenda_item, log, chair_token)
        messages.append({"speaker": f"{chair_name} (Chair Summary)", "text": summary.text})
        print(f"\n[{chair_name} (Chair Summary)]\n{summary.text}\n", flush=True)

    write_notes(ctx.notes_path, ctx, messages)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Vyr mailing meeting.")
    parser.add_argument("--mailing", required=True, help="Mailing identifier (e.g., M0001)")
    parser.add_argument("--agents", required=True, help="Path to agents JSON config")
    parser.add_argument("--agenda", required=True, help="Path to agenda text file (one item per line)")
    parser.add_argument("--notes", default="meeting-notes.md", help="Output file for meeting notes")
    parser.add_argument("--chair", default=None, help="Name of chair agent")
    parser.add_argument("--context-limit", type=int, default=10, help="Number of prior messages to include")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for deterministic ordering")
    parser.add_argument("--keys", default=None, help="Path to JSON file containing per-agent tokens")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with open(args.agenda, "r", encoding="utf-8") as handle:
        agenda = [line.strip() for line in handle if line.strip()]

    agents = load_agents(args.agents)
    chair = resolve_chair(agents, args.chair)
    tokens = load_tokens(args.keys)

    ctx = MeetingContext(
        mailing_id=args.mailing,
        agenda=agenda,
        chair=chair,
        notes_path=args.notes,
        context_limit=args.context_limit,
        seed=args.seed,
    )

    run_meeting(ctx, agents, tokens)
    print(f"Meeting complete. Notes written to {args.notes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
