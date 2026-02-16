#!/usr/bin/env python3
"""Render the paper prompt template with mailing/document substitutions."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


def parse_index(raw: str, prefix: str) -> str:
    """Parse values like '10', '0010', or 'v0010'/'m0003' and normalize."""
    value = raw.strip().upper()
    match = re.fullmatch(rf"(?:{re.escape(prefix)})?(\d+)", value)
    if not match:
        raise ValueError(f"Invalid {prefix}-index value: {raw!r}")
    number = int(match.group(1))
    if number <= 0:
        raise ValueError(f"{prefix}-index must be >= 1")
    return f"{prefix}{number:04d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render paper_prompt_template.txt for a specific document, mailing, "
            "and CFP paper, writing the final prompt to stdout."
        )
    )
    parser.add_argument(
        "--paper",
        required=True,
        help="Allocated paper number, e.g. V0011, v11, or 11.",
    )
    parser.add_argument(
        "--mailing",
        required=True,
        help="Mailing number, e.g. M0003, m3, or 3.",
    )
    parser.add_argument(
        "--cfp",
        required=True,
        help="CFP paper number for this mailing, e.g. V0009 or 9.",
    )
    parser.add_argument(
        "--template",
        default=str(Path(__file__).resolve().with_name("paper_prompt_template.txt")),
        help="Path to prompt template file (default: paper_prompt_template.txt next to this script).",
    )
    return parser.parse_args()


def render_template(template_text: str, values: dict[str, str]) -> str:
    rendered = template_text
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)

    missing = sorted(set(PLACEHOLDER_RE.findall(rendered)))
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"Template contains unresolved placeholders: {names}")
    return rendered


def main() -> int:
    args = parse_args()
    paper_doc = parse_index(args.paper, "V")
    mailing = parse_index(args.mailing, "M")
    cfp_doc = parse_index(args.cfp, "V")

    template_path = Path(args.template).resolve()
    template_text = template_path.read_text(encoding="utf-8")

    values = {
        "PAPER_DOC": paper_doc,
        "MAILING": mailing,
        "CFP_DOC": cfp_doc,
        "CFP_URL": f"https://vyr-lang.org/papers/{cfp_doc.lower()}.html",
    }
    rendered = render_template(template_text, values)

    sys.stdout.write(rendered)
    if not rendered.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
