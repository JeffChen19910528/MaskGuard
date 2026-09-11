"""Synthetic OCR benchmark dataset generator.

Every value here is fabricated for testing (same policy as
scripts/generate_test_images.py): the credit card number is the universal
Luhn-valid *test* number every payment processor's own docs use; Taiwan
ID/passport/bank account/API key/password values only match the expected
*format*, not any real person's data. Ground truth (expected text, expected
sensitive type, expected bounding region) is written to `ground_truth.json`
next to the images — this is benchmark-only data, never touched by or
written to the production audit log.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msjh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


@dataclass
class SensitiveRegion:
    type: str
    bbox: tuple[int, int, int, int]  # x, y, width, height, in THIS image's own coordinates


@dataclass
class DatasetItem:
    image: str  # filename, relative to the dataset directory
    category: str  # e.g. "TaiwanID", "mixed_chinese_english", "normal_text"
    condition: str  # "clean" | "low_res" | "blurred" | "rotated" | "font_large"
    text: str  # full expected line text, for OCR accuracy/CER
    sensitive: list[SensitiveRegion] = field(default_factory=list)

    def to_json(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Rendering: draw one line of text on a white background, returning the
# exact bounding box of the drawn text (its own ground truth).
# ---------------------------------------------------------------------------


def render_line(text: str, font_size: int = 30, padding: int = 24) -> tuple[Image.Image, tuple[int, int, int, int]]:
    font = _load_font(font_size)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font)
    text_w, text_h = right - left, bottom - top

    width, height = text_w + padding * 2, text_h + padding * 2
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw_x, draw_y = padding - left, padding - top
    draw.text((draw_x, draw_y), text, font=font, fill=(0, 0, 0))

    return image, (padding, padding, text_w, text_h)


# ---------------------------------------------------------------------------
# Image conditions (Skill.md §35 test-image-condition list, scoped to the
# subset this benchmark tracks ground truth through).
# ---------------------------------------------------------------------------


def condition_low_res(image: Image.Image, bbox, scale: float = 0.5):
    w, h = image.size
    small = image.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.BILINEAR)
    restored = small.resize((w, h), Image.BILINEAR)
    return restored, bbox  # canvas size unchanged -> bbox coordinates unchanged


def condition_blurred(image: Image.Image, bbox, radius: float = 1.3):
    return image.filter(ImageFilter.GaussianBlur(radius)), bbox


def condition_rotated(image: Image.Image, bbox, angle: float = 6.0):
    """Rotate `angle` degrees (PIL's `Image.rotate`, expand=True) and carry
    the bounding box through the same transform, verified empirically
    against PIL's actual pixel output (see benchmarks/README.md methodology
    section): for a point (x, y) relative to the original center,
        x' =  dx*cos(theta) + dy*sin(theta)
        y' = -dx*sin(theta) + dy*cos(theta)
    then re-centered into the expanded canvas. Applied to all 4 corners of
    the box and axis-aligned-bounded, since MaskGuard's own bounding boxes
    (and Tesseract's) are always axis-aligned.
    """
    rotated = image.rotate(angle, expand=True, fillcolor=(255, 255, 255))
    ow, oh = image.size
    nw, nh = rotated.size
    cx, cy = ow / 2, oh / 2
    ncx, ncy = nw / 2, nh / 2
    theta = math.radians(angle)

    x, y, w, h = bbox
    corners = [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]
    transformed = []
    for px, py in corners:
        dx, dy = px - cx, py - cy
        xp = dx * math.cos(theta) + dy * math.sin(theta) + ncx
        yp = -dx * math.sin(theta) + dy * math.cos(theta) + ncy
        transformed.append((xp, yp))

    left = min(p[0] for p in transformed)
    top = min(p[1] for p in transformed)
    right = max(p[0] for p in transformed)
    bottom = max(p[1] for p in transformed)
    return rotated, (int(left), int(top), int(right - left), int(bottom - top))


# ---------------------------------------------------------------------------
# Dataset definition
# ---------------------------------------------------------------------------

# Major sensitive types (Skill.md §35), each rendered under every condition
# in _CONDITIONS below. (text, sensitive_type, value_substring_for_bbox)
_MAJOR_SENSITIVE_LINES: dict[str, tuple[str, str, str]] = {
    "TaiwanID": ("身分證：A123456789", "TaiwanID", "A123456789"),
    "Passport": ("護照：PA1234567", "Passport", "PA1234567"),
    "BankAccount": ("銀行帳號：1234567890123", "BankAccount", "1234567890123"),
    "CreditCard": ("信用卡：4111 1111 1111 1111", "CreditCard", "4111 1111 1111 1111"),
    "Email": ("Email：demo.test.user@example.com", "Email", "demo.test.user@example.com"),
    # Category key/filename stay "PhoneTW" (still Taiwan-mobile-specific test
    # data), but the ground-truth sensitive TYPE is the Phase 6.3 canonical
    # "Phone" — RegexDetector's raw "PhoneTW" output is rewritten to "Phone"
    # by canonicalize_types() before match_detections() ever compares types
    # (see runner.py), so ground truth must say "Phone" too or every phone
    # detection would count as both a false negative and a false positive.
    "PhoneTW": ("電話：0912345678", "Phone", "0912345678"),
    "APIKey": ("API_KEY=demo_test_key_123456789", "SecretKeyValue", "demo_test_key_123456789"),
    "Password": ("password: demo_test_pw_123456", "SecretKeyValue", "demo_test_pw_123456"),
    "Address": ("地址：台北市中正區忠孝東路100號", "Address", "台北市中正區忠孝東路100號"),
}

_CONDITIONS = ["clean", "low_res", "blurred", "rotated", "font_large"]

# Language/context variety categories (Skill.md §35 image-condition list,
# clean condition only — these test OCR text recovery, not a specific
# sensitive-data mask, except where noted).
_LANGUAGE_VARIETY_LINES: dict[str, tuple[str, str, list[tuple[str, str]]]] = {
    "english_text": ("This is a normal English sentence used for OCR testing.", "clean", []),
    "traditional_chinese_text": ("這是一段用於測試的繁體中文句子，不包含任何敏感資料。", "clean", []),
    "mixed_chinese_english": ("Meeting at 3pm 下午三點開會 with 王經理 in Room 5B.", "clean", []),
    "chinese_labeled_field": ("姓名：王小明", "clean", [("PersonalName", "王小明")]),
    "normal_non_sensitive_text": ("本文件僅供內部教學使用，不含個人資料。", "clean", []),
}

_MULTIPLE_SENSITIVE_LINES = [
    "姓名：王小明",
    "電話：0912345678",
    "Email：demo@example.com",
    "身分證：A123456789",
    "信用卡：4111 1111 1111 1111",
    "API_KEY=demo_test_key_123456789",
]
_MULTIPLE_SENSITIVE_EXPECTED = [
    ("PersonalName", "王小明"),
    ("Phone", "0912345678"),  # canonical type (Phase 6.3) — see _MAJOR_SENSITIVE_LINES note above
    ("Email", "demo@example.com"),
    ("TaiwanID", "A123456789"),
    ("CreditCard", "4111 1111 1111 1111"),
    ("SecretKeyValue", "demo_test_key_123456789"),
]


def _find_value_bbox(full_text: str, value: str, image: Image.Image, font_size: int) -> tuple[int, int, int, int]:
    """Re-derive a substring's own bbox within a rendered line by measuring
    the prefix width up to where the value starts (single-line, single-font
    text, so this is an exact measurement, not an approximation)."""
    font = _load_font(font_size)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    prefix_start = full_text.index(value)
    prefix = full_text[:prefix_start]

    full_box = probe.textbbox((0, 0), full_text, font=font)
    prefix_box = probe.textbbox((0, 0), prefix, font=font) if prefix else (0, 0, 0, 0)
    value_box = probe.textbbox((0, 0), value, font=font)

    padding = 24  # must match render_line's padding
    x = padding + (prefix_box[2] - full_box[0])
    y = padding
    width = value_box[2] - value_box[0]
    height = full_box[3] - full_box[1]
    return (x, y, width, height)


def _build_items() -> list[tuple[DatasetItem, Image.Image]]:
    items: list[tuple[DatasetItem, Image.Image]] = []

    for type_key, (text, sensitive_type, value) in _MAJOR_SENSITIVE_LINES.items():
        for condition in _CONDITIONS:
            font_size = 42 if condition == "font_large" else 30
            image, _ = render_line(text, font_size=font_size)
            bbox = _find_value_bbox(text, value, image, font_size)

            if condition == "low_res":
                image, bbox = condition_low_res(image, bbox)
            elif condition == "blurred":
                image, bbox = condition_blurred(image, bbox)
            elif condition == "rotated":
                image, bbox = condition_rotated(image, bbox)

            filename = f"{type_key}_{condition}.png"
            item = DatasetItem(
                image=filename,
                category=type_key,
                condition=condition,
                text=text,
                sensitive=[SensitiveRegion(type=sensitive_type, bbox=bbox)],
            )
            items.append((item, image))

    for category, (text, condition, expected) in _LANGUAGE_VARIETY_LINES.items():
        image, _ = render_line(text, font_size=30)
        sensitive = [
            SensitiveRegion(type=t, bbox=_find_value_bbox(text, v, image, 30)) for t, v in expected
        ]
        item = DatasetItem(image=f"{category}.png", category=category, condition=condition, text=text, sensitive=sensitive)
        items.append((item, image))

    # Multiple sensitive values in one image: stack the lines vertically,
    # each with its own known y-offset, so ground truth is still exact.
    font_size = 30
    font = _load_font(font_size)
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    line_boxes = [probe.textbbox((0, 0), line, font=font) for line in _MULTIPLE_SENSITIVE_LINES]
    padding = 24
    line_height = max(b[3] - b[1] for b in line_boxes) + 14
    width = max(b[2] - b[0] for b in line_boxes) + padding * 2
    height = line_height * len(_MULTIPLE_SENSITIVE_LINES) + padding * 2

    combined = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(combined)
    sensitive_regions = []
    y = padding
    for text_line, (sensitive_type, value) in zip(_MULTIPLE_SENSITIVE_LINES, _MULTIPLE_SENSITIVE_EXPECTED):
        box = probe.textbbox((0, 0), text_line, font=font)
        draw.text((padding - box[0], y - box[1]), text_line, font=font, fill=(0, 0, 0))
        prefix_start = text_line.index(value)
        prefix_box = probe.textbbox((0, 0), text_line[:prefix_start], font=font) if prefix_start else (0, 0, 0, 0)
        value_box = probe.textbbox((0, 0), value, font=font)
        x = padding + (prefix_box[2] - box[0])
        sensitive_regions.append(SensitiveRegion(type=sensitive_type, bbox=(x, y, value_box[2] - value_box[0], box[3] - box[1])))
        y += line_height

    items.append(
        (
            DatasetItem(
                image="multiple_sensitive_values.png",
                category="multiple_sensitive_values",
                condition="clean",
                text=" ".join(_MULTIPLE_SENSITIVE_LINES),
                sensitive=sensitive_regions,
            ),
            combined,
        )
    )

    return items


def generate_dataset(output_dir: str | Path) -> list[DatasetItem]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    items_with_images = _build_items()
    ground_truth = []
    for item, image in items_with_images:
        image.save(output_path / item.image)
        ground_truth.append(item.to_json())

    (output_path / "ground_truth.json").write_text(
        json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return [item for item, _ in items_with_images]


def load_ground_truth(dataset_dir: str | Path) -> list[DatasetItem]:
    path = Path(dataset_dir) / "ground_truth.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        DatasetItem(
            image=entry["image"],
            category=entry["category"],
            condition=entry["condition"],
            text=entry["text"],
            sensitive=[SensitiveRegion(type=s["type"], bbox=tuple(s["bbox"])) for s in entry["sensitive"]],
        )
        for entry in raw
    ]
