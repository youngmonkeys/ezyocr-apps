import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "packaging" / "icons"
ICON_NAME = "ezyocr"
ICON_BASE = ICON_DIR / ICON_NAME
ICONSET_SIZES = (16, 32, 128, 256, 512)
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 4
SIMPLE_MAX_SIZE = 32

GRADIENT_START = (67, 56, 202)
GRADIENT_MID = (37, 99, 235)
GRADIENT_END = (6, 182, 212)
WHITE = (255, 255, 255)
BEAM = (94, 242, 214)


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def gradient(size):
    small = 256
    image = Image.new("RGB", (small, small))
    pixels = image.load()
    for y in range(small):
        for x in range(small):
            t = (x + y) / (2 * (small - 1))
            if t < 0.5:
                color = lerp(GRADIENT_START, GRADIENT_MID, t * 2)
            else:
                color = lerp(GRADIENT_MID, GRADIENT_END, (t - 0.5) * 2)
            pixels[x, y] = color
    return image.resize((size, size), Image.BICUBIC)


def rounded_mask(size, box, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    return mask


def draw_brackets(draw, s, box, length, width):
    left, top, right, bottom = (v * s for v in box)
    length *= s
    width *= s
    half = width / 2
    corners = (
        ((left, top), (1, 1)),
        ((right, top), (-1, 1)),
        ((left, bottom), (1, -1)),
        ((right, bottom), (-1, -1)),
    )
    for (cx, cy), (dx, dy) in corners:
        draw.line((cx, cy, cx + dx * length, cy), fill=WHITE, width=round(width))
        draw.line((cx, cy, cx, cy + dy * length), fill=WHITE, width=round(width))
        for px, py in ((cx, cy), (cx + dx * length, cy), (cx, cy + dy * length)):
            draw.ellipse((px - half, py - half, px + half, py + half), fill=WHITE)


def draw_icon_master(size, simple):
    s = size / 1024
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    if simple:
        body = (40 * s, 40 * s, size - 40 * s, size - 40 * s)
        radius = 220 * s
    else:
        body = (100 * s, 100 * s, size - 100 * s, size - 100 * s)
        radius = 185 * s
        shadow = Image.new("RGBA", (size, size), (10, 20, 60, 0))
        shadow_box = (body[0], body[1] + 18 * s, body[2], body[3] + 18 * s)
        ImageDraw.Draw(shadow).rounded_rectangle(shadow_box, radius=radius, fill=(10, 20, 60, 110))
        shadow = shadow.filter(ImageFilter.GaussianBlur(28 * s))
        canvas.alpha_composite(shadow)

    body_mask = rounded_mask(size, body, radius)
    background = gradient(size).convert("RGBA")
    if not simple:
        highlight = Image.new("L", (size, size), 0)
        ImageDraw.Draw(highlight).ellipse((-300 * s, -620 * s, 1100 * s, 420 * s), fill=46)
        highlight = highlight.filter(ImageFilter.GaussianBlur(60 * s))
        white_layer = Image.new("RGBA", (size, size), WHITE + (0,))
        white_layer.putalpha(highlight)
        background.alpha_composite(white_layer)
    background.putalpha(body_mask)
    canvas.alpha_composite(background)

    content = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(content)

    if simple:
        draw_brackets(draw, s, (210, 210, 814, 814), 210, 110)
        beam_y = 512 * s
        beam_h = 100 * s
        draw.rounded_rectangle(
            (190 * s, beam_y - beam_h / 2, 834 * s, beam_y + beam_h / 2), radius=beam_h / 2, fill=BEAM + (255,)
        )
        canvas.alpha_composite(content)
        return canvas

    draw_brackets(draw, s, (262, 262, 762, 762), 150, 50)

    beam_y = 540
    lines = ((372, 652, 392), (372, 600, 466), (372, 680, 614), (372, 560, 688))
    line_h = 38
    for x1, x2, y in lines:
        scanned = y < beam_y
        alpha = 255 if scanned else 110
        draw.rounded_rectangle(
            (x1 * s, (y - line_h / 2) * s, x2 * s, (y + line_h / 2) * s), radius=line_h / 2 * s, fill=WHITE + (alpha,)
        )
    canvas.alpha_composite(content)

    glow = Image.new("RGBA", (size, size), BEAM + (0,))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.rectangle((300 * s, (beam_y - 70) * s, 724 * s, beam_y * s), fill=BEAM + (70,))
    glow = glow.filter(ImageFilter.GaussianBlur(26 * s))
    glow_alpha = ImageChops.multiply(glow.getchannel("A"), body_mask)
    glow.putalpha(glow_alpha)
    canvas.alpha_composite(glow)

    beam = Image.new("RGBA", (size, size), BEAM + (0,))
    beam_draw = ImageDraw.Draw(beam)
    beam_h = 22
    beam_draw.rounded_rectangle(
        (300 * s, (beam_y - beam_h / 2) * s, 724 * s, (beam_y + beam_h / 2) * s),
        radius=beam_h / 2 * s,
        fill=BEAM + (255,),
    )
    beam_glow = beam.filter(ImageFilter.GaussianBlur(14 * s))
    canvas.alpha_composite(beam_glow)
    canvas.alpha_composite(beam)
    return canvas


def draw_icon(size):
    simple = size <= SIMPLE_MAX_SIZE
    master = draw_icon_master(size * SUPERSAMPLE, simple)
    return master.resize((size, size), Image.LANCZOS)


def main():
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    images = {size: draw_icon(size) for size in sorted(set(PNG_SIZES) | set(ICO_SIZES))}

    images[1024].save(ICON_BASE.with_suffix(".png"))
    for size in PNG_SIZES:
        images[size].save(ICON_DIR / f"{ICON_NAME}-{size}.png")

    ico_images = [images[size] for size in ICO_SIZES]
    ico_images[-1].save(
        ICON_BASE.with_suffix(".ico"),
        format="ICO",
        sizes=[(size, size) for size in ICO_SIZES],
        append_images=ico_images[:-1],
    )
    print(f"Icons written to {ICON_DIR}")

    if sys.platform != "darwin":
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / f"{ICON_NAME}.iconset"
        iconset.mkdir()
        for size in ICONSET_SIZES:
            images[size].save(iconset / f"icon_{size}x{size}.png")
            images[size * 2].save(iconset / f"icon_{size}x{size}@2x.png")
        output = ICON_BASE.with_suffix(".icns")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(output)], check=True)
    print(f"Icon written to {ICON_BASE.with_suffix('.icns')}")


if __name__ == "__main__":
    if not shutil.which("iconutil") and sys.platform == "darwin":
        sys.exit("iconutil not found")
    main()
