"""ArchBuddy: an AWS architecture-review agent built with the Strands Agents SDK + Amazon Bedrock.

BEFORE: ArchBuddy reviews architectures you *describe in text*, points out production gaps,
        and saves a starter AWS CDK stack with its existing `save_file` tool.
AFTER:  the same agent, same prompt, plus ONE new tool, `read_whiteboard`, so it can work
        straight from a photo of the sketch your team drew in the design session.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from strands import Agent, tool
from strands.models import BedrockModel

from whiteboard_core import DEFAULT_MODEL_ID

OUTPUT_DIR = Path(__file__).parent / "output"

SYSTEM_PROMPT = """You are ArchBuddy, a pragmatic AWS solutions architect.

What you do:
1. Understand the user's architecture.
2. Review it for production readiness (security, reliability, cost, operations) and list the
   most important gaps, highest-impact first. Be concrete and brief.
3. Write a starter AWS CDK stack (TypeScript) and save it with `save_file` as `stack.ts`.

Honesty rules (these matter more than being helpful):
- Never pretend to have seen something you have not seen. If you cannot access an input,
  say so plainly and say what you would need.
- Keep what the user DREW separate from what you SUGGEST. In the CDK stack, only create
  resources that are in the user's design; put your suggestions as `// TODO(suggested): ...`
  comments.
- When a diagram reading marks a component "unverified", or lists dropped arrows or
  unexplained text, tell the user exactly what to double-check instead of silently guessing.
"""


@tool
def save_file(filename: str, content: str) -> str:
    """Save generated content (e.g. a CDK stack or a review) to the local ./output folder.

    Args:
        filename: File name only, e.g. "stack.ts" or "review.md". Directories are ignored.
        content: Full file contents.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "output.txt"
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / safe
    path.write_text(content, encoding="utf-8")
    return f"Saved {len(content)} characters to output/{safe}"


def build_agent(with_whiteboard: bool, callback_handler=None) -> Agent:
    """Build ArchBuddy. The ONLY difference between before/after is the tool list."""
    model = BedrockModel(
        model_id=os.getenv("NAPKIN_MODEL_ID", DEFAULT_MODEL_ID),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        temperature=0.2,
    )
    tools = [save_file]
    if with_whiteboard:
        from read_whiteboard_tool import read_whiteboard  # the one new tool
        tools.append(read_whiteboard)

    kwargs = {} if callback_handler is None else {"callback_handler": callback_handler}
    return Agent(model=model, tools=tools, system_prompt=SYSTEM_PROMPT, name="ArchBuddy", **kwargs)
