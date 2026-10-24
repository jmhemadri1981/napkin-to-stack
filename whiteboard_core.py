"""Core logic for the `read_whiteboard` tool.

Two independent readers look at the same photo, and a deterministic referee
compares them:

  1. Amazon Rekognition DetectText  -> what text is physically written (OCR)
  2. Amazon Bedrock (vision model)  -> what the diagram *means*
                                       (boxes, arrows, AWS services)
  3. Referee (plain Python)         -> cross-checks every handwritten label the
                                       vision model reported against the OCR
                                       evidence, drops arrows that point at
                                       nothing, and surfaces written text the
                                       vision model ignored.

Every component comes back with an evidence status:
  - "verified"   : label is handwritten and OCR found it
  - "unverified" : model says the label is written, but OCR could not find it
                   (possible misread -> the agent should ask the user)
  - "inferred"   : no written label; recognised from an icon/shape only

This module has no dependency on Strands so it can be unit-tested and reused
from Lambda, a CLI, or any other agent framework.
"""

from __future__ import annotations

import io
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"
MAX_EDGE_PX = 1568            # long-edge size vision models work best at
MAX_IMAGE_BYTES = 3_500_000   # stays under Bedrock (3.75 MB) and Rekognition (5 MB) limits
OCR_MIN_CONFIDENCE = 70.0     # handwriting scores lower than print; 70 keeps most real lines
MATCH_THRESHOLD = 0.72        # fuzzy-match score needed to call a label "verified"

KINDS = [
    "client", "edge", "network", "compute", "container", "storage", "database",
    "messaging", "integration", "security", "analytics", "ml", "observability",
    "external", "other",
]

# JSON schema the vision model is forced to fill in (Converse tool-use = structured output)
DIAGRAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Diagram title if one is written, else a short neutral description."},
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Short unique id, e.g. c1, c2."},
                    "label": {"type": "string", "description": "The label exactly as handwritten (keep the author's spelling). If nothing is written, a short description of the shape/icon."},
                    "label_is_written": {"type": "boolean", "description": "True only if the label text is physically written on the board."},
                    "aws_service": {"type": ["string", "null"], "description": "Canonical AWS service name if this is clearly an AWS service (e.g. 'Amazon DynamoDB'), else null."},
                    "kind": {"type": "string", "enum": KINDS},
                    "group": {"type": ["string", "null"], "description": "Enclosing boundary if drawn (e.g. 'VPC', 'private subnet', 'us-east-1'), else null."},
                },
                "required": ["id", "label", "label_is_written", "aws_service", "kind", "group"],
            },
        },
        "connections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string", "description": "Component id at the arrow tail."},
                    "to": {"type": "string", "description": "Component id at the arrow head."},
                    "label": {"type": ["string", "null"], "description": "Text written on/near the arrow, else null."},
                    "bidirectional": {"type": "boolean"},
                },
                "required": ["from", "to", "label", "bidirectional"],
            },
        },
        "annotations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Free-floating notes, question marks, TODOs, crossed-out items (prefix crossed-out ones with 'CROSSED OUT:').",
        },
        "ambiguities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything you could not read or interpret with confidence.",
        },
    },
    "required": ["title", "components", "connections", "annotations", "ambiguities"],
}

VISION_PROMPT = """You are transcribing a photo of a HAND-DRAWN software architecture diagram \
(whiteboard, notebook or napkin). Your job is faithful transcription, not design.

Rules:
- Report ONLY what is drawn. Never add components, arrows or services that are not on the board.
- Keep labels exactly as written, including abbreviations and misspellings (e.g. "Dynamo", "APIGW").
- Map a component to a canonical AWS service name only when it is clearly that service.
- Arrow direction matters: "from" is the tail, "to" is the arrowhead. If there is no clear head, set bidirectional=true.
- If something is illegible or ambiguous, say so in `ambiguities` instead of guessing.

An OCR engine independently read these text lines from the same image. Use them to \
disambiguate handwriting, but the drawing is the source of truth for structure:
{ocr_hint}

Call the `record_diagram` tool with your transcription."""


class WhiteboardError(Exception):
    """Raised for user-fixable problems (bad path, unreadable image, etc.)."""


# --------------------------------------------------------------------------- #
# Image loading / preparation
# --------------------------------------------------------------------------- #
_S3_RE = re.compile(r"^s3://([^/]+)/(.+)$")


def load_image_bytes(source: str, s3_client: Any = None) -> bytes:
    """Load raw bytes from a local path or an s3://bucket/key URI."""
    source = source.strip().strip('"').strip("'")
    m = _S3_RE.match(source)
    if m:
        if s3_client is None:
            import boto3
            s3_client = boto3.client("s3")
        bucket, key = m.groups()
        try:
            return s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as exc:  # botocore ClientError and friends
            raise WhiteboardError(f"Could not read {source} from S3: {exc}") from exc

    path = Path(source).expanduser()
    if not path.is_file():
        raise WhiteboardError(f"No image found at '{source}'. Pass a .jpg/.png path or an s3://bucket/key URI.")
    return path.read_bytes()


def prepare_image(raw: bytes, max_edge: int = MAX_EDGE_PX, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    """Normalise a phone photo: honour EXIF rotation, drop alpha, downscale, re-encode as JPEG.

    Phone photos are often 4000px+, sideways (EXIF orientation), or HEIC-converted PNGs
    with alpha. Both Rekognition and Bedrock need JPEG/PNG under a few MB.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
    except UnidentifiedImageError as exc:
        raise WhiteboardError("That file is not a readable JPEG or PNG image.") from exc

    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    img = img.convert("RGB")

    if max(img.size) > max_edge:
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)

    quality = 90
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= max_bytes or quality <= 50:
            return data
        quality -= 10


# --------------------------------------------------------------------------- #
# Reader 1: Amazon Rekognition OCR
# --------------------------------------------------------------------------- #
def detect_text_lines(image_bytes: bytes, rekognition_client: Any, min_confidence: float = OCR_MIN_CONFIDENCE) -> list[dict]:
    """Return handwritten/printed LINE detections from Rekognition, highest confidence first."""
    resp = rekognition_client.detect_text(Image={"Bytes": image_bytes})
    lines = []
    for det in resp.get("TextDetections", []):
        if det.get("Type") != "LINE" or det.get("Confidence", 0) < min_confidence:
            continue
        box = det.get("Geometry", {}).get("BoundingBox", {})
        lines.append({
            "text": det["DetectedText"],
            "confidence": round(det["Confidence"], 1),
            "box": {k: round(box.get(k, 0.0), 3) for k in ("Left", "Top", "Width", "Height")},
        })
    return lines


# --------------------------------------------------------------------------- #
# Reader 2: Amazon Bedrock vision (structured output via forced tool use)
# --------------------------------------------------------------------------- #
def extract_diagram(image_bytes: bytes, ocr_lines: list[dict], bedrock_client: Any, model_id: str) -> dict:
    """Ask a Bedrock vision model to transcribe the diagram into DIAGRAM_SCHEMA."""
    ocr_hint = "\n".join(f'- "{ln["text"]}" ({ln["confidence"]}%)' for ln in ocr_lines) or "- (OCR found no text)"
    resp = bedrock_client.converse(
        modelId=model_id,
        messages=[{
            "role": "user",
            "content": [
                {"image": {"format": "jpeg", "source": {"bytes": image_bytes}}},
                {"text": VISION_PROMPT.format(ocr_hint=ocr_hint)},
            ],
        }],
        toolConfig={
            "tools": [{"toolSpec": {
                "name": "record_diagram",
                "description": "Record the transcribed architecture diagram.",
                "inputSchema": {"json": DIAGRAM_SCHEMA},
            }}],
            "toolChoice": {"tool": {"name": "record_diagram"}},
        },
        inferenceConfig={"maxTokens": 4096, "temperature": 0},
    )
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise WhiteboardError("The vision model did not return a structured diagram. Try a clearer, closer photo.")


# --------------------------------------------------------------------------- #
# Referee: deterministic cross-check
# --------------------------------------------------------------------------- #
def _norm(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).split())


def _match_score(label: str, line: str) -> float:
    """Fuzzy similarity between a component label and one OCR line (0..1).

    Handles three cases: whole-line match ("API Gateway" vs "API Gateway"),
    label contained in a longer line ("Lambda" in "Lambda (orders)"), and
    handwriting noise ("Dynamo DB" vs "DynamoD8").
    """
    a, b = _norm(label), _norm(line)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Whole label appears inside a longer OCR line, e.g. "Lambda" in "Lambda (orders)"
    if re.search(rf"\b{re.escape(a)}\b", b):
        return 0.95
    # OCR line is a large fragment of the label (OCR split a line); tiny fragments
    # like "db" must not verify "orders db", so require 60% coverage.
    if re.search(rf"\b{re.escape(b)}\b", a) and len(b) >= 0.6 * len(a):
        return 0.9
    whole = SequenceMatcher(None, a, b).ratio()
    squashed = SequenceMatcher(None, a.replace(" ", ""), b.replace(" ", "")).ratio()
    return max(whole, squashed)


def referee(diagram: dict, ocr_lines: list[dict], threshold: float = MATCH_THRESHOLD) -> dict:
    """Cross-check the vision transcription against OCR. Pure function, no AWS calls."""
    components = []
    used_lines: set[int] = set()

    for comp in diagram.get("components", []):
        comp = dict(comp)
        if not comp.get("label_is_written"):
            comp["evidence"] = "inferred"
            comp["ocr_match"] = None
        else:
            best_idx, best_score = None, 0.0
            for i, ln in enumerate(ocr_lines):
                s = _match_score(comp.get("label", ""), ln["text"])
                if s > best_score:
                    best_idx, best_score = i, s
            if best_idx is not None and best_score >= threshold:
                used_lines.add(best_idx)
                comp["evidence"] = "verified"
                comp["ocr_match"] = {"text": ocr_lines[best_idx]["text"], "score": round(best_score, 2)}
            else:
                comp["evidence"] = "unverified"
                comp["ocr_match"] = None
        components.append(comp)

    ids = {c["id"] for c in components}
    connections, dropped = [], []
    for conn in diagram.get("connections", []):
        (connections if conn.get("from") in ids and conn.get("to") in ids else dropped).append(conn)

    # Mark OCR lines explained by arrow labels / annotations / title too
    explained_texts = [c.get("label") or "" for c in connections] + list(diagram.get("annotations", [])) + [diagram.get("title", "")]
    for i, ln in enumerate(ocr_lines):
        if i in used_lines:
            continue
        if any(_match_score(t, ln["text"]) >= threshold for t in explained_texts if t):
            used_lines.add(i)

    unexplained = [ln["text"] for i, ln in enumerate(ocr_lines) if i not in used_lines]

    counts = {k: sum(1 for c in components if c["evidence"] == k) for k in ("verified", "unverified", "inferred")}
    return {
        "title": diagram.get("title", ""),
        "components": components,
        "connections": connections,
        "annotations": diagram.get("annotations", []),
        "ambiguities": diagram.get("ambiguities", []),
        "referee": {
            "evidence_counts": counts,
            "dropped_connections": dropped,
            "unexplained_ocr_text": unexplained,
            "needs_human_check": bool(counts["unverified"] or dropped or unexplained or diagram.get("ambiguities")),
        },
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def read_whiteboard(
    source: str,
    *,
    rekognition_client: Any = None,
    bedrock_client: Any = None,
    s3_client: Any = None,
    model_id: str | None = None,
) -> dict:
    """Full pipeline: load -> prepare -> OCR -> vision -> referee."""
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    if rekognition_client is None or bedrock_client is None:
        import boto3
        rekognition_client = rekognition_client or boto3.client("rekognition", region_name=region)
        bedrock_client = bedrock_client or boto3.client("bedrock-runtime", region_name=region)
    model_id = model_id or os.getenv("NAPKIN_VISION_MODEL_ID") or os.getenv("NAPKIN_MODEL_ID") or DEFAULT_MODEL_ID

    image = prepare_image(load_image_bytes(source, s3_client))
    ocr_lines = detect_text_lines(image, rekognition_client)
    diagram = extract_diagram(image, ocr_lines, bedrock_client, model_id)
    result = referee(diagram, ocr_lines)
    result["source"] = source
    result["ocr_lines"] = [ln["text"] for ln in ocr_lines]
    return result
