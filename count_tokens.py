#!/usr/bin/env python3
"""Count tokens from stdin using tiktoken."""

from __future__ import annotations

import argparse
import sys

import tiktoken


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count tokens from stdin using a model or encoding."
    )
    parser.add_argument(
        "--model",
        default="gpt-5.2",
        help="Model name for tokenizer lookup (default: gpt-5.2).",
    )
    parser.add_argument(
        "--encoding",
        help="Encoding name (overrides --model), e.g. o200k_base or cl100k_base.",
    )
    parser.add_argument(
        "--fallback-encoding",
        default="o200k_base",
        help=(
            "Fallback encoding if --model is unknown and --encoding is not set "
            "(default: o200k_base)."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print model/encoding and character count in addition to token count.",
    )
    return parser.parse_args()


def resolve_encoding(args: argparse.Namespace) -> tuple[tiktoken.Encoding, str]:
    if args.encoding:
        return tiktoken.get_encoding(args.encoding), args.encoding

    try:
        enc = tiktoken.encoding_for_model(args.model)
        return enc, enc.name
    except KeyError:
        if not args.fallback_encoding:
            print(
                f"Unknown model {args.model!r}; pass --encoding or --fallback-encoding.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        enc = tiktoken.get_encoding(args.fallback_encoding)
        return enc, enc.name


def main() -> int:
    args = parse_args()
    text = sys.stdin.read()
    encoding, encoding_name = resolve_encoding(args)
    token_count = len(encoding.encode(text))

    if args.verbose:
        print(f"model={args.model}")
        print(f"encoding={encoding_name}")
        print(f"characters={len(text)}")
        print(f"tokens={token_count}")
    else:
        print(token_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
