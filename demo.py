"""Before/after demo runner for ArchBuddy.

    python demo.py before  samples/whiteboard_sample.jpg   # agent WITHOUT read_whiteboard
    python demo.py after   samples/whiteboard_sample.jpg   # same agent + read_whiteboard
    python demo.py compare samples/whiteboard_sample.jpg   # both, back to back
    python demo.py tool    samples/whiteboard_sample.jpg   # just the tool's JSON output

Both agent runs get the exact same system prompt and the exact same user prompt.
Outputs land in output/before/ and output/after/ so they never overwrite each other.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import agent as archbuddy

PROMPT = (
    "Here's a photo of the architecture my team sketched in today's design session: {image}\n"
    "Review it, tell me the top gaps before we go to production, and save a starter CDK stack."
)

BAR = "=" * 78


def run_agent(mode: str, image: str) -> None:
    with_tool = mode == "after"
    archbuddy.OUTPUT_DIR = Path(archbuddy.__file__).parent / "output" / mode
    label = "AFTER  (+ read_whiteboard)" if with_tool else "BEFORE (no vision tool)"
    print(f"\n{BAR}\n  ArchBuddy {label}\n{BAR}")
    print(f"USER: {PROMPT.format(image=image)}\n")

    agent = archbuddy.build_agent(with_whiteboard=with_tool)
    started = time.time()
    result = agent(PROMPT.format(image=image))
    elapsed = time.time() - started

    tools_used = {name: m.call_count for name, m in result.metrics.tool_metrics.items()}
    files = sorted(p.name for p in archbuddy.OUTPUT_DIR.glob("*")) if archbuddy.OUTPUT_DIR.exists() else []
    print(f"\n{'-' * 78}")
    print(f"  mode={mode}  time={elapsed:.1f}s  tools_called={tools_used or 'none'}  files={files or 'none'}")
    print("-" * 78)


def run_tool(image: str) -> None:
    import whiteboard_core as core

    started = time.time()
    result = core.read_whiteboard(image)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    ref = result["referee"]
    print(f"\n# {len(result['components'])} components {ref['evidence_counts']}, "
          f"{len(result['connections'])} connections, needs_human_check={ref['needs_human_check']} "
          f"({time.time() - started:.1f}s)", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["before", "after", "compare", "tool"])
    parser.add_argument("image", help="Path to a .jpg/.png photo or s3://bucket/key")
    args = parser.parse_args()

    if args.mode == "tool":
        run_tool(args.image)
    elif args.mode == "compare":
        run_agent("before", args.image)
        run_agent("after", args.image)
    else:
        run_agent(args.mode, args.image)


if __name__ == "__main__":
    main()
