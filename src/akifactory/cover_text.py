"""Deterministic Turkish-safe cover typography."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def compose(background: Path, output: Path, title: str) -> None:
    image = Image.open(background).convert("RGB")
    width, height = image.size
    margin = round(width * 0.075)
    available = width - 2 * margin
    font_path = Path("C:/Windows/Fonts/arialbd.ttf")
    draw = ImageDraw.Draw(image)
    for size in range(round(width * 0.095), 17, -1):
        font = ImageFont.truetype(str(font_path), size)
        lines: list[str] = []
        for word in title.split():
            candidate = f"{lines[-1]} {word}" if lines else word
            if lines and draw.textlength(candidate, font=font) <= available:
                lines[-1] = candidate
            else:
                lines.append(word)
        if all(draw.textlength(line, font=font) <= available for line in lines) and len(lines) * size * 1.22 <= height * 0.32:
            break
    line_height = round(size * 1.22)
    top = height - round(height * 0.12) - len(lines) * line_height
    overlay = Image.new("RGBA", image.size)
    shade = ImageDraw.Draw(overlay)
    start = max(0, top - round(height * 0.15))
    for y in range(start, height):
        alpha = min(235, round(235 * (y - start) / max(1, height - start) * 1.8))
        shade.line((0, y, width, y), fill=(5, 9, 18, alpha))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        x = (width - draw.textlength(line, font=font)) / 2
        draw.text((x, top + index * line_height), line, font=font,
                  fill="#FFD95A" if index == len(lines) - 1 else "white",
                  stroke_width=max(2, size // 25), stroke_fill="#10131C")
    image.convert("RGB").save(output, quality=96, subsampling=0)
