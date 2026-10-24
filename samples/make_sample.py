"""Generate a synthetic 'whiteboard sketch' for testing (python samples/make_sample.py).

For the demo video, use a REAL phone photo of a hand-drawn diagram instead; this file is just
so the pipeline can be exercised without a whiteboard. The design deliberately has production
gaps (no auth, no DLQ, no monitoring, no backups) for ArchBuddy to find.
"""

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

random.seed(7)
W, H = 1600, 1000
img = Image.new("RGB", (W, H), (246, 245, 240))
d = ImageDraw.Draw(img)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/lato/Lato-Medium.ttf",
    "/System/Library/Fonts/Supplemental/Chalkboard.ttc",       # macOS
    "/System/Library/Fonts/Supplemental/Marker Felt.ttc",      # macOS
    "C:/Windows/Fonts/comic.ttf",                              # Windows
]


def font(size):
    for f in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


BLACK, BLUE, RED, GREEN = (30, 30, 35), (25, 70, 170), (190, 35, 35), (20, 120, 60)


def wobble_line(p1, p2, color, width=5):
    (x1, y1), (x2, y2) = p1, p2
    steps = max(4, int(math.dist(p1, p2) / 25))
    pts = []
    for i in range(steps + 1):
        t = i / steps
        pts.append((x1 + (x2 - x1) * t + random.uniform(-2.5, 2.5), y1 + (y2 - y1) * t + random.uniform(-2.5, 2.5)))
    d.line(pts, fill=color, width=width, joint="curve")


def box(cx, cy, w, h, text, color=BLACK, size=40):
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    for a, b in [((x0, y0), (x1 + 6, y0)), ((x1, y0 - 4), (x1, y1)), ((x1 + 4, y1), (x0, y1)), ((x0, y1 + 5), (x0 - 2, y0))]:
        wobble_line(a, b, color)
    write(cx, cy, text, color, size)
    return (x0, y0, x1, y1)


def write(cx, cy, text, color=BLACK, size=40, angle=0):
    f = font(size)
    tw, th = d.textbbox((0, 0), text, font=f)[2:]
    layer = Image.new("RGBA", (tw + 20, th + 20), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((10, 10), text, font=f, fill=color)
    layer = layer.rotate(angle + random.uniform(-3, 3), expand=True, resample=Image.BICUBIC)
    img.paste(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)), layer)


def arrow(p1, p2, color=BLACK, label=None):
    wobble_line(p1, p2, color, 4)
    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    for s in (-1, 1):
        a = ang + math.pi + s * 0.45
        wobble_line(p2, (p2[0] + 26 * math.cos(a), p2[1] + 26 * math.sin(a)), color, 4)
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        write(mx, my - 28, label, color, 28)


write(800, 60, "Order Service v1", BLACK, 54)

users = box(160, 470, 190, 100, "Users", BLUE)
cf = box(520, 230, 250, 100, "CloudFront", BLUE)
s3 = box(900, 230, 230, 100, "S3 (web)", GREEN)
apigw = box(520, 600, 230, 100, "API GW", BLUE)
lam = box(900, 600, 270, 110, "Lambda orders", BLACK, 38)
ddb = box(1360, 600, 250, 100, "DynamoDB", GREEN)
sqs = box(900, 860, 170, 90, "SQS", BLACK)
worker = box(1360, 860, 270, 100, "Lambda worker", BLACK, 36)

arrow((255, 440), (395, 260), BLUE)
arrow((645, 230), (785, 230), BLUE)
arrow((255, 500), (405, 590), BLUE, "HTTPS")
arrow((635, 600), (765, 600))
arrow((1035, 600), (1235, 600), label="put/get")
arrow((900, 655), (900, 815))
arrow((985, 860), (1225, 860))

write(500, 700, "auth??", RED, 40, angle=-6)
write(1330, 400, "TODO: monitoring", RED, 34, angle=4)

img = img.rotate(-1.5, resample=Image.BICUBIC, fillcolor=(235, 234, 228)).filter(ImageFilter.GaussianBlur(0.6))
out = Path(__file__).parent / "whiteboard_sample.jpg"
img.save(out, quality=88)
print(f"wrote {out}")
