#!/usr/bin/env python3
"""Virtual meeting runner (email-style) for Vyr mailings."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from provider_base import AgentConfig, AgentProvider
from providers import PROVIDERS


REPLY_RE = re.compile(r"^\s*<reply>(?P<body>.*)</reply>\s*$", re.DOTALL | re.IGNORECASE)
NEWMSG_RE = re.compile(r"^\s*<newmsg>(?P<body>.*)</newmsg>\s*$", re.DOTALL | re.IGNORECASE)
NEXT_RE = re.compile(r"^\s*<next\s*/>\s*$", re.IGNORECASE)


@dataclass
class AgentState:
    current_id: int
    initialized: bool = False


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
    if agent.provider == "deepseek" and "DeepSeek" in tokens:
        return tokens["DeepSeek"]
    if agent.provider == "mistral" and "Mistral" in tokens:
        return tokens["Mistral"]
    if agent.auth_env:
        return os.environ.get(agent.auth_env)
    return None


def list_message_ids(directory: Path) -> List[int]:
    ids: List[int] = []
    for path in directory.glob("msg*.txt"):
        match = re.match(r"msg(\d+)\.txt$", path.name)
        if match:
            ids.append(int(match.group(1)))
    return sorted(set(ids))


def read_message(directory: Path, message_id: int) -> str:
    path = directory / f"msg{message_id}.txt"
    if not path.exists():
        return "[missing message]"
    return path.read_text(encoding="utf-8")


def write_message(directory: Path, message_id: int, content: str) -> None:
    path = directory / f"msg{message_id}.txt"
    path.write_text(content, encoding="utf-8")


def build_intro(agent: AgentConfig, others: List[AgentConfig]) -> str:
    participants = "\n".join(f"    - {other.name}" for other in others)
    return (
        "START INTRO\n\n"
        f"You are {agent.name}.  You are particpating in a virtual meeting with:\n\n"
        f"{participants}\n\n"
        "The meeting is arranged into a series of messages in an email-like discussion format.\n\n"
        "You will interact with the meeting by responding with commands with a particular format.\n\n"
        "You will be informed how many unread messages and new messages you have in your inbox.\n\n"
        "The first message (message id #1) will then be displayed.\n\n"
        "You will then be given three options:\n\n"
        "1. Reply to the message\n"
        "2. Write a new message\n"
        "3. Mark this message as read and read the next message\n\n"
        "To reply to the current message (1.) you will format your response in the following format:\n\n"
        "<reply>\n"
        "  <subject>The title of your reply</subject>\n"
        "  <quote>Quote something from the message you are replying to if you like</quote>\n"
        "  <p>Write what you want to say in your reply here</p>\n"
        "  <quote>Quote some more stuff if you want</quote>\n"
        "  <p>Write some more stuff</p>\n"
        "  <p>And some more stuff</p>\n"
        "</reply>\n\n"
        "To write a new message format (2.) format it as follows:\n\n"
        "<newmsg>\n"
        "  <subject>Subject of your new message</subject>\n"
        "  <p>First paragraph of your new message</p>\n"
        "  <p>Second paragraph of your new message</p>\n"
        "  <p>And so on</p>\n"
        "</newmsg>\n\n"
        "Both of these message formats may use basic HTML tags within paragraphs <p> such as bold, "
        "italic, underordered/ordered lists, and so on.\n\n"
        "To archive the current message and read the next one, provide the following response:\n\n"
        "<next/>\n\n"
        "The next message will then be displayed and you will be given the three options again.\n\n"
        "If you provide a response other than of these three options you will receive an error message "
        "that your response is ill-formed and you will be prompted again.\n\n"
        "END INTRO\n"
    )


def build_prompt(
    agent: AgentConfig,
    state: AgentState,
    total_messages: int,
    message_body: str,
    include_intro: bool,
    others: List[AgentConfig],
) -> str:
    unread = max(total_messages - state.current_id, 0)
    prompt_parts = []
    if include_intro:
        prompt_parts.append(build_intro(agent, others))
    prompt_parts.append(f"You have {unread} unread messages.")
    if message_body:
        prompt_parts.append(f"Message #{state.current_id}:\n{message_body}")
    else:
        prompt_parts.append("There are no more messages to display.")
    prompt_parts.append(
        "Options:\n"
        "1. Reply to the message\n"
        "2. Write a new message\n"
        "3. Mark this message as read and read the next message"
    )
    return "\n\n".join(prompt_parts).strip()


def parse_response(text: str) -> Tuple[str, Optional[str]]:
    if NEXT_RE.match(text):
        return "next", None
    reply_match = REPLY_RE.match(text)
    if reply_match:
        return "reply", reply_match.group("body").strip()
    new_match = NEWMSG_RE.match(text)
    if new_match:
        return "newmsg", new_match.group("body").strip()
    return "invalid", None


def apply_reply(
    directory: Path,
    agent_name: str,
    current_id: int,
    total_messages: int,
    body: str,
) -> int:
    new_id = total_messages + 1
    content = (
        f"<reply id=\"{new_id}\" reply_to=\"{current_id}\">\n"
        f"  <from>{agent_name}</from>\n"
        f"{body}\n"
        f"</reply>\n"
    )
    write_message(directory, new_id, content)
    return new_id


def apply_newmsg(directory: Path, agent_name: str, total_messages: int, body: str) -> int:
    new_id = total_messages + 1
    content = (
        f"<newmsg id=\"{new_id}\">\n"
        f"  <from>{agent_name}</from>\n"
        f"{body}\n"
        f"</newmsg>\n"
    )
    write_message(directory, new_id, content)
    return new_id


def run_meeting(directory: Path, agents: List[AgentConfig], tokens: Dict[str, str]) -> None:
    if not agents:
        raise RuntimeError("No agents configured.")

    provider_map = {name: PROVIDERS[name] for name in PROVIDERS}
    ids = list_message_ids(directory)
    if not ids:
        raise RuntimeError("No msgN.txt files found in the directory.")

    total_messages = max(ids)
    states = {agent.name: AgentState(current_id=1) for agent in agents}

    while True:
        new_message_created = False
        for agent in agents:
            state = states[agent.name]
            provider = provider_map.get(agent.provider)
            if not provider:
                raise RuntimeError(f"Unknown provider: {agent.provider}")
            token = resolve_token(agent, tokens)

            if state.current_id <= total_messages:
                message_body = read_message(directory, state.current_id)
            else:
                message_body = ""

            include_intro = not state.initialized
            others = [other for other in agents if other.name != agent.name]
            prompt = build_prompt(agent, state, total_messages, message_body, include_intro, others)

            while True:
                print(f"[debug] calling {agent.name}", flush=True)
                response = provider.request(agent, prompt, token)
                print(f"[debug] completed response from {agent.name}", flush=True)
                action, body = parse_response(response.text)

                if action == "invalid":
                    prompt = (
                        "ERROR: Response ill-formed. Please respond with <reply>...</reply>, "
                        "<newmsg>...</newmsg>, or <next/>.\n\n"
                        + build_prompt(agent, state, total_messages, message_body, False, others)
                    )
                    continue

                if action == "next":
                    if state.current_id <= total_messages:
                        state.current_id += 1
                elif action == "reply":
                    apply_reply(directory, agent.name, state.current_id, total_messages, body or "")
                    total_messages += 1
                    new_message_created = True
                elif action == "newmsg":
                    apply_newmsg(directory, agent.name, total_messages, body or "")
                    total_messages += 1
                    new_message_created = True

                state.initialized = True
                break

        if not new_message_created and all(state.current_id > total_messages for state in states.values()):
            break


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an email-style Vyr meeting.")
    parser.add_argument("--dir", required=True, help="Directory containing msgN.txt files")
    parser.add_argument("--agents", required=True, help="Path to agents JSON config")
    parser.add_argument("--keys", default=None, help="Path to JSON file containing per-agent tokens")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    directory = Path(args.dir)
    if not directory.exists():
        raise RuntimeError(f"Directory not found: {directory}")

    agents = load_agents(args.agents)
    tokens = load_tokens(args.keys)
    run_meeting(directory, agents, tokens)
    print("Meeting complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
