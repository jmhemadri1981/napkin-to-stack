# Napkin-to-Stack: giving ArchBuddy eyes

ArchBuddy is a Strands Agents + Amazon Bedrock architecture-review agent. It reviews designs for
production gaps and saves a starter AWS CDK stack. This project adds **one tool**,
`read_whiteboard`, so it can work straight from a photo of a hand-drawn diagram.

```
photo ──► prepare_image (EXIF-rotate, resize, JPEG)
            ├─► Amazon Rekognition DetectText ──► what is WRITTEN   ─┐
            └─► Amazon Bedrock vision (forced JSON schema) ──► what it MEANS ─┤
                                                                    ▼
                                         referee (plain Python, deterministic)
                                         • verified / unverified / inferred per component
                                         • drops arrows that point at nothing
                                         • lists written text nobody accounted for
                                                                    ▼
                                         ArchBuddy reviews + writes CDK, and asks
                                         about anything the referee flagged
```

## Setup (about 5 minutes)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export AWS_REGION=us-east-1             # any region with Bedrock + Rekognition
# Bedrock console → Model access: enable Anthropic Claude Sonnet 4.6
# Attach iam-policy.json to the role/user you run as
```

Optional: `NAPKIN_MODEL_ID` changes the agent model, and `NAPKIN_VISION_MODEL_ID` changes the vision model.
Both default to `global.anthropic.claude-sonnet-4-6`.

## Run

```bash
python -m pytest -q tests                                # offline, no AWS needed
python samples/make_sample.py                            # regenerate the test sketch
python demo.py tool    samples/whiteboard_sample.jpg     # raw tool output (JSON)
python demo.py before  samples/whiteboard_sample.jpg     # agent without the tool
python demo.py after   samples/whiteboard_sample.jpg     # same agent + read_whiteboard
python demo.py compare samples/whiteboard_sample.jpg     # both, back to back
```

The tool also accepts `s3://bucket/key` URIs. Generated files go to `output/before/` and `output/after/`.

## Reuse the pattern in your own agent

```python
from read_whiteboard_tool import read_whiteboard
agent = Agent(tools=[...your tools..., read_whiteboard])
```

`whiteboard_core.py` has no Strands dependency, so you can also call it from Lambda or any other framework.

## Files

| File | What it is |
|---|---|
| `whiteboard_core.py` | The pipeline: image prep, Rekognition OCR, Bedrock vision, referee |
| `read_whiteboard_tool.py` | The Strands `@tool` wrapper (the one new tool) |
| `agent.py` | ArchBuddy: system prompt, existing `save_file` tool, `build_agent()` |
| `demo.py` | Before/after runner using the same prompt for both |
| `tests/` | Offline tests with stubbed AWS clients |
| `iam-policy.json` | Least-privilege policy |
| `SUBMISSION.md` / `DEMO_SCRIPT.md` | Builder Center write-up and video script |
