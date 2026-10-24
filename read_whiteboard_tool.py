"""The ONE new tool: read_whiteboard.

This is the only file you need to copy into another Strands agent to give it
the ability to read hand-drawn architecture diagrams:

    from read_whiteboard_tool import read_whiteboard
    agent = Agent(tools=[..., read_whiteboard])
"""

from strands import tool

import whiteboard_core as core


@tool
def read_whiteboard(image: str) -> dict:
    """Read a photo of a hand-drawn architecture diagram (whiteboard, notebook, napkin) and return
    its components and connections as structured JSON.

    Use this whenever the user refers to an image file or S3 URI of an architecture sketch.

    Each component has an `evidence` field:
      - "verified":   its handwritten label was independently confirmed by OCR
      - "unverified": the label could not be confirmed by OCR (possible misread; confirm with the user)
      - "inferred":   no label was written; recognised from the shape/icon only
    The `referee` section lists arrows that pointed at nothing, written text the transcription
    did not account for, and whether a human should double-check anything.

    Args:
        image: Local path to a .jpg/.png photo, or an s3://bucket/key URI.
    """
    try:
        return core.read_whiteboard(image)
    except core.WhiteboardError as exc:
        return {"status": "error", "content": [{"text": str(exc)}]}
    except Exception as exc:  # AWS/network errors: report, don't crash the agent loop
        return {"status": "error", "content": [{"text": f"read_whiteboard failed: {type(exc).__name__}: {exc}"}]}
