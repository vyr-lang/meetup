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
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from provider_base import AgentConfig, AgentProvider, AgentResponse
from providers import PROVIDERS


HAND_RAISE_PATTERN = re.compile(r"\braise\s*:\s*(yes|no)\b", re.IGNORECASE)


@dataclass
class MeetingContext:
    mailing_id: str
    agenda: List[str]
    chair: str
    notes_path: str
    context_limit: int
    seed: Optional[int]
    source_context: str



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


def load_url_context(path: Optional[str]) -> str:
    if not path:
        return ""
    url_file = Path(path)
    if not url_file.exists():
        raise FileNotFoundError(f"URL context file not found: {path}")
    urls = [line.strip() for line in url_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not urls:
        return ""

    blocks = []
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "meetup/1.0"})
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            body = f"[error] failed to fetch: {exc}"
        blocks.append(
            "\n".join(
                [
                    "----- BEGIN SOURCE -----",
                    f"URL: {url}",
                    body,
                    "----- END SOURCE -----",
                ]
            )
        )
    return "\n\n".join(blocks)


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
    if agent.provider == "deepseek" and "DeepSeek" in tokens:
        return tokens["DeepSeek"]
    if agent.provider == "mistral" and "Mistral" in tokens:
        return tokens["Mistral"]
    if agent.auth_env:
        return os.environ.get(agent.auth_env)
    return None


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

        Sources:
        {ctx.source_context}

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

        Sources:
        {ctx.source_context}

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

        Sources:
        {ctx.source_context}

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
    parser.add_argument(
        "--context-urls",
        default=None,
        help="Path to a file containing URLs to fetch and inject into prompts",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with open(args.agenda, "r", encoding="utf-8") as handle:
        agenda = [line.strip() for line in handle if line.strip()]

    agents = load_agents(args.agents)
    chair = resolve_chair(agents, args.chair)
    tokens = load_tokens(args.keys)
    source_context = load_url_context(args.context_urls)

    ctx = MeetingContext(
        mailing_id=args.mailing,
        agenda=agenda,
        chair=chair,
        notes_path=args.notes,
        context_limit=args.context_limit,
        seed=args.seed,
        source_context=source_context,
    )

    run_meeting(ctx, agents, tokens)
    print(f"Meeting complete. Notes written to {args.notes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
