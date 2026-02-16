#!/usr/bin/env python3
"""Single-shot provider chat: read prompt from file and write response to file."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from provider_base import AgentConfig
from providers import PROVIDERS


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read an input file as the prompt, send one request to a provider, "
            "and write the model response to an output file."
        )
    )
    parser.add_argument("provider", help="Provider name to use")
    parser.add_argument("--model", default=None, help="Model override")
    parser.add_argument("--endpoint", default=None, help="Endpoint override")
    parser.add_argument("--name", default="filechat", help="Agent name")
    parser.add_argument(
        "--auth-env",
        default=None,
        help="Environment variable containing API key",
    )
    parser.add_argument(
        "--keys",
        default=None,
        help="Path to JSON file containing tokens",
    )
    parser.add_argument(
        "--input-file",
        required=True,
        help="Path to input prompt file",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Path to output response file",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    provider = PROVIDERS.get(args.provider)
    if not provider:
        print(f"Unknown provider: {args.provider}", file=sys.stderr)
        print("Available providers:", file=sys.stderr)
        for name in sorted(PROVIDERS.keys()):
            print(f"- {name}", file=sys.stderr)
        return 2

    agent = AgentConfig(
        name=args.name,
        role="participant",
        provider=args.provider,
        endpoint=args.endpoint,
        auth_env=args.auth_env,
        model=args.model,
    )

    try:
        tokens = load_tokens(args.keys)
        token = resolve_token(agent, tokens)
        prompt = Path(args.input_file).read_text(encoding="utf-8")
        response = provider.request(agent, prompt, token)
    except Exception as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(response.text, encoding="utf-8")
    print(f"Wrote response to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
