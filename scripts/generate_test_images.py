"""Generates synthetic test images for E2E OCR/redaction testing.

Every value used here is fabricated for testing only:
- The credit card number is the universally-used Luhn-valid *test* number
  (4111 1111 1111 1111) that every payment processor's own test docs use.
- The Taiwan ID, phone number, email, and API key are made-up placeholders
  that only match the expected *format*, not any real person's data.

Every generated image also carries a visible "TEST DATA (SYNTHETIC)" banner
so nobody mistakes a fixture for a real document.

Usage:
    python scripts/generate_test_images.py [--output-dir tests/fixtures]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BANNER = "TEST DATA (SYNTHETIC) - DO NOT USE AS REAL PII"

# Windows ships Microsoft JhengHei (Traditional Chinese + Latin) at this path;
# fall back to the default PIL bitmap font (Latin-only) if it's unavailable
# so the script still runs on non-Windows machines.
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


def render_lines(lines: list[str], font_size: int = 30, padding: int = 24) -> Image.Image:
    font = _load_font(font_size)
    all_lines = [BANNER, ""] + lines

    dummy = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(dummy)
    line_sizes = [draw.textbbox((0, 0), line or " ", font=font) for line in all_lines]
    line_height = max(box[3] - box[1] for box in line_sizes) + 14
    width = max(box[2] - box[0] for box in line_sizes) + padding * 2
    height = line_height * len(all_lines) + padding * 2

    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    y = padding
    for i, line in enumerate(all_lines):
        color = (180, 0, 0) if i == 0 else (0, 0, 0)
        draw.text((padding, y), line, font=font, fill=color)
        y += line_height
    return image


# Each fixture: filename -> (text lines, expected sensitive types for E2E assertions)
FIXTURES: dict[str, dict] = {
    "email.png": {
        "lines": ["Email：demo.test.user@example.com"],
        "expected_types": ["Email"],
    },
    "phone.png": {
        "lines": ["電話：0912345678"],
        "expected_types": ["PhoneTW"],
    },
    "taiwan_id.png": {
        "lines": ["身分證：A123456789"],
        "expected_types": ["TaiwanID"],
    },
    "credit_card.png": {
        "lines": ["信用卡：4111 1111 1111 1111"],
        "expected_types": ["CreditCard"],
    },
    "api_key.png": {
        "lines": ["API_KEY=demo_test_key_123456789"],
        "expected_types": ["SecretKeyValue"],
    },
    "passport.png": {
        "lines": ["護照：PA1234567"],
        "expected_types": ["Passport"],
    },
    "bank_account.png": {
        "lines": ["銀行帳號：1234567890123"],
        "expected_types": ["BankAccount"],
    },
    "mixed_language.png": {
        "lines": [
            "姓名：Chris Wang 王小明",
            "Note 備註：this is a bilingual 中英文混合 test line",
        ],
        "expected_types": ["PersonalName"],
    },
    "mixed_sensitive.png": {
        "lines": [
            "姓名：王小明",
            "電話：0912345678",
            "Email：demo@example.com",
            "身分證：A123456789",
            "信用卡：4111 1111 1111 1111",
            "API_KEY=demo_test_key_123456789",
        ],
        "expected_types": [
            "PersonalName", "PhoneTW", "Email", "TaiwanID", "CreditCard", "SecretKeyValue",
        ],
    },
}


def generate(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for filename, spec in FIXTURES.items():
        image = render_lines(spec["lines"])
        path = output_dir / filename
        image.save(path)
        manifest[filename] = {
            "expected_types": spec["expected_types"],
            "lines": spec["lines"],
        }
        print(f"wrote {path} ({image.width}x{image.height})")

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {manifest_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="tests/fixtures", help="Where to write the generated PNGs")
    args = parser.parse_args()
    generate(Path(args.output_dir))


if __name__ == "__main__":
    main()
