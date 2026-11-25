import os
import textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1350
TEXT_COLOR = (74, 63, 92)       # #4A3F5C
ACCENT_COLOR = (242, 201, 211)  # #F2C9D3

FONT_PATH = os.path.join(os.path.dirname(__file__), "..", "fonts", "PlaywriteBEVLG.ttf")
SANS_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]


def find_font(candidates, size):
  for p in candidates:
    if os.path.exists(p):
      return ImageFont.truetype(p, size)
  return ImageFont.load_default()


def get_playwrite(size):
  if os.path.exists(FONT_PATH):
    return ImageFont.truetype(FONT_PATH, size)
  return find_font(SANS_CANDIDATES, size)


def hex_to_rgb(h):
  h = h.lstrip("#")
  return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def make_paper_bg(bg_rgb, seed=42):
  rng = np.random.default_rng(seed)
  base = np.array(bg_rgb, dtype=np.float32)

  y_idx, x_idx = np.ogrid[:H, :W]
  cx, cy = W * 0.5, H * 0.45
  dist = np.sqrt(((x_idx - cx) / (W * 0.65)) ** 2 + ((y_idx - cy) / (H * 0.65)) ** 2)
  vignette = np.clip(1.0 - 0.085 * (dist ** 1.6), 0.88, 1.02)
  v_grad = np.linspace(1.015, 0.975, H, dtype=np.float32)[:, None]

  fine_grain = rng.normal(0.0, 7.5, (H, W, 1)).astype(np.float32)
  coarse_small = rng.normal(0.0, 5.0, (H // 3, W // 3, 1)).astype(np.float32)
  coarse_img = Image.fromarray(
      np.clip(coarse_small[:, :, 0] + 128, 0, 255).astype(np.uint8), mode="L"
  ).resize((W, H), Image.Resampling.BILINEAR)
  coarse_img = coarse_img.filter(ImageFilter.GaussianBlur(radius=1.2))
  coarse_grain = (np.asarray(coarse_img, dtype=np.float32) - 128.0)[:, :, None]

  arr = base[None, None, :] * vignette[:, :, None] * v_grad[:, :, None]
  arr = arr + fine_grain + coarse_grain * 0.85

  num_specks = 3500
  sx = rng.integers(0, W, size=num_specks)
  sy = rng.integers(0, H, size=num_specks)
  s_delta = rng.choice([-14.0, 12.0], size=num_specks)
  for c in range(3):
    arr[sy, sx, c] += s_delta

  arr = np.clip(arr, 0, 255).astype(np.uint8)
  return Image.fromarray(arr, mode="RGB")


def render_slide(text, bg_hex, out_path, is_hook=True, slide_num=1, total_slides=1, seed=1):
  bg_rgb = hex_to_rgb(bg_hex)
  img = make_paper_bg(bg_rgb, seed=seed)
  draw = ImageDraw.Draw(img)
  font_footer = find_font(SANS_CANDIDATES, 28)

  base_size = 64 if is_hook else 56
  max_text_w = 860
  max_text_h = 920
  paragraphs = [p.strip() for p in text.split(" / ") if p.strip()]

  font_size = base_size
  while font_size >= 40:
    font = get_playwrite(font_size)
    wrap_chars = 22 if font_size >= 58 else 26
    wrapped_lines = []
    for p_idx, p in enumerate(paragraphs):
      lines = textwrap.wrap(p, width=wrap_chars)
      wrapped_lines.extend(lines)
      if p_idx < len(paragraphs) - 1:
        wrapped_lines.append("")

    line_heights = []
    max_line_w = 0
    for line in wrapped_lines:
      if line == "":
        line_heights.append(int(font_size * 0.55))
      else:
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        lh = bbox[3] - bbox[1]
        max_line_w = max(max_line_w, lw)
        line_heights.append(lh + int(font_size * 0.55))

    total_h = sum(line_heights)
    if max_line_w <= max_text_w and total_h <= max_text_h:
      break
    font_size -= 4

  y = (H - total_h) // 2 - 24
  draw.ellipse((W // 2 - 6, y - 52, W // 2 + 6, y - 40), fill=ACCENT_COLOR)

  for line, lh in zip(wrapped_lines, line_heights):
    if line != "":
      bbox = draw.textbbox((0, 0), line, font=font)
      tw = bbox[2] - bbox[0]
      x = (W - tw) // 2 - bbox[0]
      draw.text((x, y), line, font=font, fill=TEXT_COLOR)
    y += lh

  footer_text = "@thegirlbeforehim" if total_slides == 1 else f"@thegirlbeforehim   ·   {slide_num}/{total_slides}"
  fb = draw.textbbox((0, 0), footer_text, font=font_footer)
  fw = fb[2] - fb[0]
  draw.text(((W - fw) // 2, H - 92), footer_text, font=font_footer, fill=TEXT_COLOR)

  img.save(out_path, "PNG", optimize=True)
