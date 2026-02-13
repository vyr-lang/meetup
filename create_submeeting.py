#!/usr/bin/env python3
"""Create a per-paper submeeting directory and seed msg1.txt."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def parse_index(raw: str, prefix: str) -> int:
    """Parse values like '2', '0002', or 'm0002'/'v0002'."""
    value = raw.strip().lower()
    match = re.fullmatch(rf"(?:{re.escape(prefix)})?(\d+)", value)
    if not match:
        raise ValueError(f"Invalid {prefix}-index value: {raw!r}")
    number = int(match.group(1))
    if number <= 0:
        raise ValueError(f"{prefix}-index must be >= 1")
    return number


def default_doc_url(paper_num: int) -> str:
    return f"https://vyr-lang.org/papers/v{paper_num:04d}.html"


def fetch_doc_html(doc_url: str) -> str:
    request = Request(
        doc_url,
        headers={"User-Agent": "meetup-create-submeeting/1.0"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = response.read()
    except URLError as exc:
        raise RuntimeError(f"Failed to fetch document URL {doc_url}: {exc}") from exc
    return data.decode("utf-8")


def build_msg1(
    meeting_num: int,
    paper_num: int,
    from_name: str,
    doc_url: str,
    doc_html: str,
) -> str:
    meeting_id = f"M{meeting_num:04d}"
    paper_id = f"V{paper_num:04d}"
    subject = f"{meeting_id}/{paper_id} Submeeting Kickoff"
    attachment = doc_html.rstrip("\n")
    return (
        "<newmsg id=\"1\">\n"
        f"  <from>{from_name}</from>\n"
        f"  <subject>{subject}</subject>\n"
        f"  <p>This is a submeeting of {meeting_id}. We are discussing {paper_id}.</p>\n"
        f"  <p>{paper_id} is available here: {doc_url}</p>\n"
        "  <p>The full document is attached following for those that don't have web access...</p>\n"
        "  <p>Discussion goal: evaluate what is proposed in this paper, including tradeoffs, risks, and alternatives.</p>\n"
        "  <p>Each participant must post at least one explicit vote during the discussion using a scale from -5 (strongly oppose) to +5 (strongly support).</p>\n"
        "  <p>Please include a clear marker such as <b>Vote: +2</b> or <b>Vote: -3</b> along with brief rationale for your score.</p>\n"
        "  <attachment>\n"
        f"{attachment}\n"
        "  </attachment>\n"
        "</newmsg>\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create m000N/v000M submeeting dir and seed msg1.txt."
    )
    parser.add_argument(
        "--meeting",
        required=True,
        help="Meeting number, e.g. 2, 0002, or m0002",
    )
    parser.add_argument(
        "--paper",
        required=True,
        help="Paper number, e.g. 9, 0009, or v0009",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Root path of the meetup workspace (default: current directory)",
    )
    parser.add_argument(
        "--from-name",
        default="Codex",
        help="Value for the <from> tag in msg1.txt (default: Codex)",
    )
    parser.add_argument(
        "--doc-url",
        default=None,
        help="Public URL for the discussed paper (default: https://vyr-lang.org/papers/v000M.html)",
    )
    parser.add_argument(
        "--doc-html-file",
        default=None,
        help="Optional local HTML file to embed as attachment instead of fetching --doc-url",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite msg1.txt if it already exists",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    meeting_num = parse_index(args.meeting, "m")
    paper_num = parse_index(args.paper, "v")

    root = Path(args.root).resolve()
    meeting_dir = root / f"m{meeting_num:04d}"
    submeeting_dir = meeting_dir / f"v{paper_num:04d}"
    msg1_path = submeeting_dir / "msg1.txt"

    submeeting_dir.mkdir(parents=True, exist_ok=True)

    if msg1_path.exists() and not args.overwrite:
        raise RuntimeError(
            f"{msg1_path} already exists. Use --overwrite to replace it."
        )

    doc_url = args.doc_url or default_doc_url(paper_num)
    if args.doc_html_file:
        doc_html = Path(args.doc_html_file).read_text(encoding="utf-8")
    else:
        doc_html = fetch_doc_html(doc_url)

    msg1_path.write_text(
        build_msg1(meeting_num, paper_num, args.from_name, doc_url, doc_html),
        encoding="utf-8",
    )

    print(f"Created submeeting directory: {submeeting_dir}")
    print(f"Wrote initial message: {msg1_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
