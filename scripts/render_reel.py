import os
import subprocess
import tempfile
from render_slides import render_slide


def render_reel_mp4(slides_text, bg_hex, out_mp4, post_id=1):
  """Render a 7-12 second 1080x1920 faceless Reel MP4 from slides_text."""
  if not slides_text:
    raise ValueError("slides_text cannot be empty for Reel generation.")

  num_slides = len(slides_text)
  # Target ~10 seconds total (clamp per-slide duration between 1.8s and 3.0s)
  fade_dur = 0.35
  per_slide = max(1.8, min(3.0, (10.0 + (num_slides - 1) * fade_dur) / num_slides))
  total_dur = num_slides * per_slide - (num_slides - 1) * fade_dur

  with tempfile.TemporaryDirectory() as tmpdir:
    frame_paths = []
    for idx, text in enumerate(slides_text, 1):
      fpath = os.path.join(tmpdir, f"reel_frame_{idx:02d}.png")
      render_slide(
          text,
          bg_hex,
          fpath,
          is_hook=(idx == 1),
          slide_num=idx,
          total_slides=num_slides,
          seed=int(post_id) * 100 + idx,
          width=1080,
          height=1920,
      )
      frame_paths.append(fpath)

    cmd = ["ffmpeg", "-y"]
    for fpath in frame_paths:
      cmd.extend(["-loop", "1", "-t", f"{per_slide:.2f}", "-i", fpath])

    # Soft, warm, non-copyright ambient brown-noise audio bed
    cmd.extend([
        "-f", "lavfi", "-t", f"{total_dur:.2f}",
        "-i", "anoisesrc=color=brown:amplitude=0.015:sample_rate=44100",
    ])

    filter_parts = []
    for i in range(num_slides):
      # Subtle gentle zoom-in motion on each frame
      frames_cnt = int(per_slide * 30)
      filter_parts.append(
          f"[{i}:v]scale=1140:2026,zoompan=z='min(zoom+0.0008,1.05)':d={frames_cnt}:s=1080x1920:fps=30,format=yuv420p,setsar=1[v{i}]"
      )

    if num_slides == 1:
      v_out = "[v0]"
    else:
      prev = "[v0]"
      offset = per_slide - fade_dur
      for i in range(1, num_slides):
        nxt = f"[xf{i}]" if i < num_slides - 1 else "[vout]"
        filter_parts.append(
            f"{prev}[v{i}]xfade=transition=fade:duration={fade_dur}:offset={offset:.2f}{nxt}"
        )
        prev = nxt
        offset += per_slide - fade_dur
      v_out = "[vout]"

    audio_idx = num_slides
    filter_parts.append(
        f"[{audio_idx}:a]lowpass=f=320,afade=t=in:st=0:d=0.6,afade=t=out:st={max(0, total_dur - 0.8):.2f}:d=0.8[aout]"
    )

    filter_complex = ";".join(filter_parts)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", v_out,
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        out_mp4,
    ])

    subprocess.run(cmd, check=True)
    print(f"Rendered {total_dur:.1f}s Reel MP4 -> {out_mp4}")
