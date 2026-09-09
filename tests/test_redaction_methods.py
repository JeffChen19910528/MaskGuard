from PIL import Image

from maskguard.models import BoundingBox
from maskguard.redaction import methods


def _white_image():
    return Image.new("RGB", (100, 100), (255, 255, 255))


def test_solid_mask_paints_black_rectangle():
    image = _white_image()
    box = BoundingBox(x=10, y=10, width=20, height=20)
    methods.solid_mask(image, box, padding=0)
    assert image.getpixel((15, 15)) == (0, 0, 0)
    assert image.getpixel((90, 90)) == (255, 255, 255)


def test_pixelate_creates_uniform_blocks_and_leaves_outside_untouched():
    image = Image.new("RGB", (40, 40))
    for x in range(40):
        for y in range(40):
            image.putpixel((x, y), (x * 5 % 256, y * 5 % 256, 0))
    original = image.copy()
    box = BoundingBox(x=5, y=5, width=20, height=20)
    methods.pixelate(image, box, padding=0, block_size=4)

    assert image.getpixel((0, 0)) == original.getpixel((0, 0))  # outside region untouched

    # Inside the region, a 4x4 block should now be a uniform color (mosaic effect).
    block_pixels = {image.getpixel((5 + dx, 5 + dy)) for dx in range(4) for dy in range(4)}
    assert len(block_pixels) == 1


def test_partial_mask_leaves_edges_untouched():
    image = _white_image()
    box = BoundingBox(x=0, y=0, width=100, height=20)
    methods.partial_mask(image, box, padding=0, keep_ratio=0.2)
    assert image.getpixel((1, 10)) == (255, 255, 255)
    assert image.getpixel((50, 10)) == (0, 0, 0)
    assert image.getpixel((98, 10)) == (255, 255, 255)
