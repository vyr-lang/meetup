#!/usr/bin/env python3
"""Render msgN.txt files into a single threaded HTML page."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET


_ENTITY_RE = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);")
_ATTACHMENT_RE = re.compile(r"<attachment>.*?</attachment>", re.DOTALL | re.IGNORECASE)
_ROOT_RE = re.compile(r"<(reply|newmsg)\b([^>]*)>(.*)</\1>", re.DOTALL | re.IGNORECASE)


def sanitize_xml(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", cleaned)
    cleaned = _ENTITY_RE.sub(lambda m: m.group(0), cleaned)
    cleaned = re.sub(r"&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z]+;)", "&amp;", cleaned)
    return cleaned


class Message:
    def __init__(self, msg_id: int, reply_to: Optional[int], tag: str, raw_inner: str) -> None:
        self.msg_id = msg_id
        self.reply_to = reply_to
        self.tag = tag
        self.raw_inner = raw_inner
        self.children: List["Message"] = []

    @property
    def subject(self) -> str:
        value = extract_tag_text(self.raw_inner, "subject")
        return value or "(no subject)"

    @property
    def author(self) -> str:
        value = extract_tag_text(self.raw_inner, "from")
        return value or "(unknown)"


def extract_tag_text(fragment: str, tag: str) -> str:
    try:
        wrapper = ET.fromstring(f"<root>{fragment}</root>")
    except ET.ParseError:
        return ""
    element = wrapper.find(tag)
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def inner_xml(fragment: str) -> str:
    fragment = _ATTACHMENT_RE.sub("<attachment/>", fragment)
    try:
        wrapper = ET.fromstring(f"<root>{fragment}</root>")
    except ET.ParseError:
        return html.escape(fragment)
    parts = []
    for child in wrapper:
        if child.tag in {"from", "subject"}:
            continue
        if child.tag == "attachment":
            parts.append("<p><em>ATTACHMENT REMOVED</em></p>")
            continue
        parts.append(ET.tostring(child, encoding="unicode"))
    return "\n".join(parts)


def parse_message(path: Path) -> Message:
    text = path.read_text(encoding="utf-8")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        root = None

    if root is None:
        try:
            import lxml.etree as LET
        except Exception:
            LET = None
        if LET is not None:
            parser = LET.XMLParser(recover=True)
            try:
                root = LET.fromstring(text.encode("utf-8"), parser=parser)
            except Exception:
                root = None

    if root is None:
        sanitized = sanitize_xml(text)
        try:
            root = ET.fromstring(sanitized)
        except ET.ParseError as exc:
            root = None

    if root is None:
        match = _ROOT_RE.search(text)
        if not match:
            raise ValueError(f"Failed to parse {path.name}: not a valid message wrapper")
        tag = match.group(1).lower()
        attrs = match.group(2)
        inner = match.group(3)
        id_match = re.search(r"id\s*=\s*\"?(\d+)\"?", attrs)
        if not id_match:
            raise ValueError(f"{path.name} is missing id attribute")
        msg_id = int(id_match.group(1))
        reply_match = re.search(r"reply_to\s*=\s*\"?(\d+)\"?", attrs)
        reply_to_id = int(reply_match.group(1)) if reply_match else None
        return Message(msg_id, reply_to_id, tag, inner)

    msg_id_attr = root.attrib.get("id")
    if not msg_id_attr:
        raise ValueError(f"{path.name} is missing id attribute")
    msg_id = int(msg_id_attr)
    reply_to = root.attrib.get("reply_to")
    reply_to_id = int(reply_to) if reply_to else None
    raw_inner = "\n".join(ET.tostring(child, encoding="unicode") for child in root)
    return Message(msg_id, reply_to_id, root.tag, raw_inner)


def load_messages(directory: Path) -> Dict[int, Message]:
    messages: Dict[int, Message] = {}
    for path in sorted(directory.glob("msg*.txt")):
        match = re.match(r"msg(\d+)\.txt$", path.name)
        if not match:
            continue
        message = parse_message(path)
        messages[message.msg_id] = message
    return messages


def build_threads(messages: Dict[int, Message]) -> List[Message]:
    roots: List[Message] = []
    for message in messages.values():
        if message.reply_to and message.reply_to in messages:
            messages[message.reply_to].children.append(message)
        else:
            roots.append(message)
    for message in messages.values():
        message.children.sort(key=lambda m: m.msg_id)
    roots.sort(key=lambda m: m.msg_id)
    return roots


def render_message(message: Message, depth: int = 0) -> str:
    indent = "  " * depth
    body_html = inner_xml(message.raw_inner)
    return (
        f"{indent}<article class=\"message depth-{depth}\">\n"
        f"{indent}  <header>\n"
        f"{indent}    <div class=\"meta\">\n"
        f"{indent}      <span class=\"id\">#{message.msg_id}</span>\n"
        f"{indent}      <span class=\"type\">{html.escape(message.tag)}</span>\n"
        f"{indent}      <span class=\"author\">{html.escape(message.author)}</span>\n"
        f"{indent}    </div>\n"
        f"{indent}    <h3>{html.escape(message.subject)}</h3>\n"
        f"{indent}  </header>\n"
        f"{indent}  <div class=\"content\">\n{body_html}\n{indent}  </div>\n"
        f"{indent}</article>\n"
    )


def render_thread(message: Message, depth: int = 0) -> str:
    html_parts = [render_message(message, depth)]
    for child in message.children:
        html_parts.append(render_thread(child, depth + 1))
    return "".join(html_parts)


def render_page(messages: List[Message], title: str) -> str:
    threads_html = "\n".join(render_thread(msg, 0) for msg in messages)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f5f1;
      --card: #ffffff;
      --ink: #1c1c1c;
      --muted: #5b5b5b;
      --accent: #2949c6;
      --border: #e2ddd2;
    }}
    body {{
      margin: 0;
      font-family: "Source Serif 4", "Spectral", "Georgia", serif;
      background: var(--bg);
      color: var(--ink);
    }}
    main {{
      max-width: 960px;
      margin: 40px auto 80px;
      padding: 0 20px;
    }}
    h1 {{
      font-size: 2.2rem;
      margin-bottom: 8px;
    }}
    p.lead {{
      color: var(--muted);
      margin-top: 0;
    }}
    .message {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px 20px;
      margin: 16px 0;
      box-shadow: 0 4px 12px rgba(28, 28, 28, 0.06);
    }}
    .message header {{
      border-bottom: 1px solid var(--border);
      margin-bottom: 12px;
      padding-bottom: 8px;
    }}
    .message h3 {{
      margin: 8px 0 0;
      font-size: 1.2rem;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      font-size: 0.85rem;
      color: var(--muted);
    }}
    .meta .id {{
      font-weight: 700;
      color: var(--accent);
    }}
    .content p {{
      line-height: 1.6;
    }}
    .content quote, .content blockquote {{
      display: block;
      margin: 12px 0;
      padding: 12px 16px;
      border-left: 4px solid var(--accent);
      background: rgba(41, 73, 198, 0.08);
    }}
    .depth-1 {{ margin-left: 24px; }}
    .depth-2 {{ margin-left: 48px; }}
    .depth-3 {{ margin-left: 72px; }}
    .depth-4 {{ margin-left: 96px; }}
  </style>
</head>
<body>
  <main>
    <h1>{html.escape(title)}</h1>
    <p class=\"lead\">Threaded view of meetup messages.</p>
    {threads_html}
  </main>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render meetup messages to HTML.")
    parser.add_argument("--dir", required=True, help="Directory containing msgN.txt files")
    parser.add_argument("--out", required=True, help="Output HTML file")
    parser.add_argument("--title", default="Meetup Messages", help="Page title")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    directory = Path(args.dir)
    if not directory.exists():
        raise RuntimeError(f"Directory not found: {directory}")

    messages = load_messages(directory)
    roots = build_threads(messages)
    html_doc = render_page(roots, args.title)
    Path(args.out).write_text(html_doc, encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
