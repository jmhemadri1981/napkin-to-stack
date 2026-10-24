# Napkin-to-Stack: I gave my architecture agent eyes, and a referee so it can't fake what it sees

> **Before you post:** replace every `[[...]]` with numbers from your own runs. Don't publish any number you haven't measured.

**Tags:** `#strands-agents` `#amazon-bedrock` `#amazon-rekognition` `#agentic-ai` `#architecture`

---

## The agent I started with

**ArchBuddy** is an architecture-review agent built with the **Strands Agents SDK** on **Amazon Bedrock**
(Claude Sonnet 4.6). You describe a system in text, and it:

- reviews the design for production gaps (security, reliability, cost, operations), and
- writes a starter **AWS CDK** stack, saved with its one existing tool, `save_file`.

**The gap:** real designs don't start as text. They start as boxes and arrows on a whiteboard at
the end of a meeting. To use ArchBuddy, someone had to retype the whiteboard into a paragraph,
and that someone never does.

When I sent it a photo, it said it couldn't see the image. That was the honest answer, and also a dead end.

## The one new tool: `read_whiteboard`

`read_whiteboard(image)` accepts a phone photo (local path or `s3://` URI) and returns the diagram as
structured JSON: components, AWS service mapping, arrows with direction and labels, boundaries, and
side notes like "auth??".

**Why this tool?** Out of everything ArchBuddy could gain, this one removes the first step of every
design review: turning a sketch into something a tool can read. Everything else ArchBuddy does
was already there.

### How it works (and why it's two readers, not one)

A vision model alone can be confidently wrong. It might "see" a Kinesis box that isn't there, or
read `DynamoD8` as something else entirely. So the tool uses two independent readers and a referee:

1. **Amazon Rekognition `DetectText`** reads what is physically *written* on the board.
2. **Amazon Bedrock (Claude vision)** reads what the diagram *means*. It is forced into a strict JSON
   schema through Converse tool-use, at temperature 0, and gets the OCR lines as hints.
3. **A deterministic referee in plain Python** cross-checks them:
   - every handwritten label is fuzzy-matched against the OCR evidence and marked **verified**,
     **unverified** (possible misread), or **inferred** (an icon with no written label);
   - arrows that point at non-existent components are dropped;
   - written text the vision model ignored gets surfaced.

ArchBuddy's system prompt tells it to treat `unverified` items as questions for the user, not facts.
It also keeps *what you drew* separate from *what it suggests*. Only drawn components become CDK
resources, and suggestions become `// TODO(suggested)` comments.

**Image hygiene matters for phone photos.** EXIF rotation is applied, the image is resized to 1568 px,
alpha is flattened, and it is re-encoded as JPEG under the size limits, so a sideways 12 MP photo just works.

## AWS services used

- **Amazon Bedrock**: the agent model, plus the vision model inside the tool
- **Amazon Rekognition**: handwriting/text detection, the independent second reader
- **Amazon S3** (optional): diagrams can be read straight from a bucket
- **Strands Agents SDK**: the agent loop and the `@tool` integration

## Before vs after (same agent, same system prompt, same user prompt)

Prompt: *"Here's a photo of the architecture my team sketched in today's design session: whiteboard.jpg.
Review it, tell me the top gaps before we go to production, and save a starter CDK stack."*

| | **Before** | **After** |
|---|---|---|
| Tools available | `save_file` | `save_file`, `read_whiteboard` |
| Could it see the design? | No. It said so and asked me to describe it | Yes: [[N]] components, [[M]] arrows |
| Evidence | none | [[x]] verified · [[y]] unverified · [[z]] inferred |
| Gaps found | generic checklist | [[e.g. no auth on API Gateway (the "auth??" note), no DLQ on SQS, no alarms ("TODO: monitoring"), no DynamoDB PITR]] |
| CDK stack | none / placeholder | `output/after/stack.ts` with [[N]] resources + TODO suggestions |
| Time | [[s]] | [[s]] |

## How it plugs into a Strands agent (the reusable pattern)

```python
from strands import Agent
from read_whiteboard_tool import read_whiteboard

agent = Agent(model=..., tools=[save_file, read_whiteboard], system_prompt=SYSTEM_PROMPT)
```

That's the whole integration: one import and one list entry. `whiteboard_core.py` has no Strands
dependency, so the same pipeline drops into a Lambda, a Slack bot, or any other agent framework.

**The pattern you can steal:** *pair a generative reader with an independent deterministic one,
and let plain code referee the disagreement.* It applies well beyond diagrams: receipts, forms,
lab notes, meter photos.

## Engineering notes

- Structured output comes from Converse `toolChoice` forcing a JSON schema, so there's no regex-parsing of prose.
- The tool returns Strands-native `{"status": "error"}` results for bad paths and AWS errors, so the agent explains the problem instead of crashing.
- The 8 offline tests use stubbed Rekognition and Bedrock clients. They cover the referee logic, handwriting noise (`DynamoD8` → DynamoDB), hallucinated components, dangling arrows, EXIF rotation, and S3 input.
- A least-privilege IAM policy is included.

## What I'd do next

- An `explain_diff` mode: photograph the board again after a meeting and get only what changed.
- Export the verified diagram to draw.io or Mermaid for docs.

**Demo video:** [[YouTube link, under 3 min]]
**Code:** [[GitHub link]]
