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
    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not token:
            raise RuntimeError(
                f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
            )

        model = agent.model or "gpt-5.2"
        payload = {
            "model": model,
            "input": prompt,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenAI API error: {exc.code} {exc.reason}. {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to reach OpenAI API: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Unexpected OpenAI response: {body}") from exc

        text = extract_openai_text(parsed)
        return AgentResponse(agent=agent.name, text=text)


class GeminiProvider(AgentProvider):
    def request(self, agent: AgentConfig, prompt: str, token: Optional[str]) -> AgentResponse:
        if not token:
            raise RuntimeError(
                f"Missing auth token for {agent.name}. Provide --keys or set ${agent.auth_env}."
            )

        model = agent.model or "gemini-3-pro-preview"
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ]
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "x-goog-api-key": token,
            "Content-Type": "application/json",
        }

        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Gemini API error: {exc.code} {exc.reason}. {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Failed to reach Gemini API: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Unexpected Gemini response: {body}") from exc

        text = extract_gemini_text(parsed)
        return AgentResponse(agent=agent.name, text=text)


def extract_gemini_text(payload: Dict[str, Any]) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        return ""
    return str(parts[0].get("text", "")).strip()


def extract_openai_text(payload: Dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()

    chunks: List[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


PROVIDERS: Dict[str, AgentProvider] = {
    "simple_http": SimpleHttpProvider(),
    "openai": OpenAIProvider(),
    "gemini": GeminiProvider(),
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
    prompt = textwrap.dedent(
        f"""
        You are {agent.name}, a participant in the Vyr meeting for {ctx.mailing_id}.
        Agenda item: {agenda_item}

        Speak concisely (max 180 words). Provide concrete points and, if applicable, cite paper numbers.

        Recent context:
        {log}
        """
    ).strip()
    return provider.request(agent, prompt, token)


def chair_summary(
    provider: AgentProvider,
    chair: AgentConfig,
    ctx: MeetingContext,
    agenda_item: str,
    log: str,
    token: Optional[str],
) -> AgentResponse:
    prompt = textwrap.dedent(
        f"""
        You are {chair.name}, chairing the Vyr meeting for {ctx.mailing_id}.
        Agenda item: {agenda_item}

        Summarize the discussion in 5-8 bullet points. Note decisions, open questions, and action items.

        Recent context:
        {log}
        """
    ).strip()
    return provider.request(chair, prompt, token)


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
            log = build_context_log(messages, ctx.context_limit)

        chair_provider = provider_map[chair_agent.provider]
        chair_token = resolve_token(chair_agent, tokens)
        summary = chair_summary(chair_provider, chair_agent, ctx, agenda_item, log, chair_token)
        messages.append({"speaker": f"{chair_name} (Chair Summary)", "text": summary.text})

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
