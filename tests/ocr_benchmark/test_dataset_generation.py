"""Benchmark framework tests: dataset generation + ground truth round-trip.
No OCR needed — these test the benchmark tooling itself."""
from __future__ import annotations

from benchmarks.ocr.dataset import (
    _MAJOR_SENSITIVE_LINES,
    condition_rotated,
    generate_dataset,
    load_ground_truth,
    render_line,
)


def test_generate_dataset_produces_images_and_ground_truth(tmp_path):
    items = generate_dataset(tmp_path)
    assert len(items) >= 45  # 9 major types x 5 conditions + language-variety + combined

    for item in items:
        image_path = tmp_path / item.image
        assert image_path.exists(), f"missing generated image for {item.image}"

    ground_truth_path = tmp_path / "ground_truth.json"
    assert ground_truth_path.exists()


def test_ground_truth_round_trips_through_load_ground_truth(tmp_path):
    generated = generate_dataset(tmp_path)
    loaded = load_ground_truth(tmp_path)

    assert len(loaded) == len(generated)
    by_image = {item.image: item for item in loaded}
    for original in generated:
        reloaded = by_image[original.image]
        assert reloaded.category == original.category
        assert reloaded.condition == original.condition
        assert reloaded.text == original.text
        assert [(s.type, tuple(s.bbox)) for s in reloaded.sensitive] == [
            (s.type, tuple(s.bbox)) for s in original.sensitive
        ]


def test_every_major_sensitive_type_has_all_five_conditions(tmp_path):
    items = generate_dataset(tmp_path)
    conditions_by_category: dict[str, set[str]] = {}
    for item in items:
        if item.category in _MAJOR_SENSITIVE_LINES:
            conditions_by_category.setdefault(item.category, set()).add(item.condition)

    expected_conditions = {"clean", "low_res", "blurred", "rotated", "font_large"}
    for category, conditions in conditions_by_category.items():
        assert conditions == expected_conditions, f"{category} missing conditions: {expected_conditions - conditions}"


def test_ground_truth_bbox_is_within_image_bounds(tmp_path):
    from PIL import Image

    items = generate_dataset(tmp_path)
    for item in items:
        image = Image.open(tmp_path / item.image)
        for region in item.sensitive:
            x, y, w, h = region.bbox
            assert x >= 0 and y >= 0
            assert x + w <= image.width
            assert y + h <= image.height


def test_rotation_bbox_transform_matches_actual_pixel_position():
    """Regression pin for the rotation ground-truth transform: rotate a
    single-pixel marker and confirm the formula in `condition_rotated`
    predicts its new position (verified empirically before implementation;
    this keeps that verification from silently drifting)."""
    from PIL import Image

    marker_image = Image.new("RGB", (200, 100), (255, 255, 255))
    marker_image.putpixel((150, 80), (0, 0, 0))
    bbox = (150, 80, 1, 1)

    rotated_image, new_bbox = condition_rotated(marker_image, bbox, angle=15)

    black_pixels = [
        (x, y)
        for x in range(rotated_image.width)
        for y in range(rotated_image.height)
        if rotated_image.getpixel((x, y)) == (0, 0, 0)
    ]
    assert black_pixels, "marker pixel vanished after rotation"
    px, py = black_pixels[0]

    nx, ny, nw, nh = new_bbox
    assert nx - 2 <= px <= nx + nw + 2
    assert ny - 2 <= py <= ny + nh + 2


def test_render_line_bbox_bounds_the_actual_drawn_text():
    image, bbox = render_line("A123456789", font_size=30)
    x, y, w, h = bbox
    # Every non-white pixel must fall within the reported bbox (with a small
    # antialiasing margin) — this is what makes the generator's own ground
    # truth trustworthy for IoU scoring.
    margin = 2
    for px in range(image.width):
        for py in range(image.height):
            if image.getpixel((px, py)) != (255, 255, 255):
                assert x - margin <= px <= x + w + margin
                assert y - margin <= py <= y + h + margin
