#!/usr/bin/env python3
"""Interactive CLI chat for provider testing."""

from __future__ import annotations

import argparse
import json
import os
import sys
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
    parser = argparse.ArgumentParser(description="Interactive provider chat.")
    parser.add_argument("provider", nargs="?", help="Provider name to use")
    parser.add_argument("--model", default=None, help="Model override")
    parser.add_argument("--endpoint", default=None, help="Endpoint override")
    parser.add_argument("--name", default="testchat", help="Agent name")
    parser.add_argument("--auth-env", default=None, help="Environment variable with API key")
    parser.add_argument("--keys", default=None, help="Path to JSON file containing tokens")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.provider:
        print("Available providers:")
        for name in sorted(PROVIDERS.keys()):
            print(f"- {name}")
        return 0

    provider_name = args.provider
    provider = PROVIDERS.get(provider_name)
    if not provider:
        print(f"Unknown provider: {provider_name}", file=sys.stderr)
        return 2

    agent = AgentConfig(
        name=args.name,
        role="participant",
        provider=provider_name,
        endpoint=args.endpoint,
        auth_env=args.auth_env,
        model=args.model,
    )
    tokens = load_tokens(args.keys)
    token = resolve_token(agent, tokens)

    if not args.model:
        try:
            models = provider.list_models(token)
        except Exception as exc:
            print(f"Failed to list models: {exc}", file=sys.stderr)
            return 1
        if models:
            print("Available models:")
            for name in models:
                print(f"- {name}")
        else:
            print("No models available or model listing unsupported.")
        return 0

    print(f"Chatting with provider '{provider_name}'. Press Ctrl-D to exit.")
    try:
        for line in sys.stdin:
            prompt = line.rstrip("\n")
            if not prompt:
                continue
            print(f"[debug] calling {agent.name}", flush=True)
            response = provider.request(agent, prompt, token)
            print(f"[debug] completed response from {agent.name}", flush=True)
            print(response.text, flush=True)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
