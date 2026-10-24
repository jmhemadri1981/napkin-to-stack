"""Offline tests: AWS clients are stubbed, so these run with no credentials (pytest -q)."""

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import whiteboard_core as core  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "whiteboard_sample.jpg"


def _det(text, conf=95.0, kind="LINE"):
    return {"DetectedText": text, "Type": kind, "Confidence": conf,
            "Geometry": {"BoundingBox": {"Left": 0.1, "Top": 0.1, "Width": 0.1, "Height": 0.05}}}


class FakeRekognition:
    def __init__(self, detections):
        self.detections = detections
        self.calls = []

    def detect_text(self, Image):
        self.calls.append(Image)
        return {"TextDetections": self.detections}


class FakeBedrock:
    def __init__(self, diagram):
        self.diagram = diagram
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return {"output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "t1", "name": "record_diagram", "input": self.diagram}}]}}}


def comp(cid, label, written=True, service=None, kind="compute"):
    return {"id": cid, "label": label, "label_is_written": written, "aws_service": service, "kind": kind, "group": None}


DIAGRAM = {
    "title": "Order Service v1",
    "components": [
        comp("c1", "API GW", service="Amazon API Gateway", kind="network"),
        comp("c2", "Lambda orders", service="AWS Lambda"),
        comp("c3", "DynamoDB", service="Amazon DynamoDB", kind="database"),
        comp("c4", "Kinesis", service="Amazon Kinesis", kind="messaging"),   # hallucinated: not on OCR
        comp("c5", "user icon", written=False, kind="client"),               # drawn, unlabeled
    ],
    "connections": [
        {"from": "c1", "to": "c2", "label": None, "bidirectional": False},
        {"from": "c2", "to": "c3", "label": "put/get", "bidirectional": False},
        {"from": "c2", "to": "c9", "label": None, "bidirectional": False},    # points at nothing
    ],
    "annotations": ["auth??"],
    "ambiguities": [],
}

OCR = [_det("Order Service v1"), _det("API GW"), _det("Lambda orders"), _det("DynamoD8", 81),
       _det("put/get"), _det("auth??", 88), _det("SQS"), _det("noise", 40), _det("API", kind="WORD")]


def test_referee_marks_evidence_and_flags_problems():
    lines = core.detect_text_lines(b"x", FakeRekognition(OCR))
    assert [ln["text"] for ln in lines] == ["Order Service v1", "API GW", "Lambda orders", "DynamoD8", "put/get", "auth??", "SQS"]

    out = core.referee(DIAGRAM, lines)
    ev = {c["id"]: c["evidence"] for c in out["components"]}
    assert ev == {"c1": "verified", "c2": "verified", "c3": "verified", "c4": "unverified", "c5": "inferred"}
    assert out["components"][2]["ocr_match"]["text"] == "DynamoD8"          # survives handwriting noise
    assert [c["to"] for c in out["referee"]["dropped_connections"]] == ["c9"]
    assert out["referee"]["unexplained_ocr_text"] == ["SQS"]                # written but not transcribed
    assert out["referee"]["evidence_counts"] == {"verified": 3, "unverified": 1, "inferred": 1}
    assert out["referee"]["needs_human_check"] is True


def test_small_fragment_does_not_verify_long_label():
    lines = [{"text": "db", "confidence": 99.0, "box": {}}]
    out = core.referee({"components": [comp("c1", "orders db")], "connections": []}, lines)
    assert out["components"][0]["evidence"] == "unverified"


def test_clean_diagram_needs_no_human_check():
    diagram = {"title": "t", "components": [comp("c1", "SQS")], "connections": [], "annotations": [], "ambiguities": []}
    out = core.referee(diagram, [{"text": "SQS", "confidence": 99.0, "box": {}}])
    assert out["referee"]["needs_human_check"] is False


def test_full_pipeline_with_stubs():
    rek, br = FakeRekognition(OCR), FakeBedrock(DIAGRAM)
    out = core.read_whiteboard(str(SAMPLE), rekognition_client=rek, bedrock_client=br, model_id="test-model")

    call = br.calls[0]
    assert call["modelId"] == "test-model"
    assert call["toolConfig"]["toolChoice"] == {"tool": {"name": "record_diagram"}}
    assert call["inferenceConfig"]["temperature"] == 0
    content = call["messages"][0]["content"]
    assert content[0]["image"]["format"] == "jpeg"
    assert '"DynamoD8"' in content[1]["text"]                     # OCR hints are passed to the vision model
    assert rek.calls[0]["Bytes"] == content[0]["image"]["source"]["bytes"]  # both readers see the same image
    assert out["source"] == str(SAMPLE) and len(out["components"]) == 5


def test_prepare_image_downscales_rotates_and_flattens():
    img = Image.new("RGBA", (5000, 2000), (255, 0, 0, 128))
    exif = Image.Exif()
    exif[0x0112] = 6  # EXIF orientation: rotate 90 (typical portrait phone photo)
    buf = io.BytesIO()
    img.save(buf, format="PNG", exif=exif)
    out = Image.open(io.BytesIO(core.prepare_image(buf.getvalue())))
    assert out.format == "JPEG" and out.mode == "RGB"
    assert max(out.size) == core.MAX_EDGE_PX
    assert out.size[1] > out.size[0]  # EXIF rotation applied -> portrait


def test_bad_inputs_raise_friendly_errors(tmp_path):
    with pytest.raises(core.WhiteboardError, match="No image found"):
        core.load_image_bytes(str(tmp_path / "missing.jpg"))
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    with pytest.raises(core.WhiteboardError, match="not a readable"):
        core.prepare_image(bad.read_bytes())


def test_s3_uri_uses_s3_client():
    class Body:
        def read(self):
            return b"img"

    class FakeS3:
        def get_object(self, Bucket, Key):
            assert (Bucket, Key) == ("my-bucket", "boards/day1.jpg")
            return {"Body": Body()}

    assert core.load_image_bytes("s3://my-bucket/boards/day1.jpg", FakeS3()) == b"img"


def test_strands_tool_wraps_errors(monkeypatch):
    import read_whiteboard_tool as t

    def boom(_):
        raise core.WhiteboardError("No image found at 'x'")

    monkeypatch.setattr(core, "read_whiteboard", boom)
    res = t.read_whiteboard("x")
    assert res["status"] == "error" and "No image found" in res["content"][0]["text"]
    assert t.read_whiteboard.tool_spec["name"] == "read_whiteboard"
    assert "image" in t.read_whiteboard.tool_spec["inputSchema"]["json"]["properties"]
