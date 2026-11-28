from datetime import datetime, timezone
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from zoneinfo import ZoneInfo
import requests
from render_reel import render_reel_mp4
from render_slides import render_slide

GDRIVE_RENDERED_FOLDER_ID = "1ocIfVmkQgdw4txcpMVx_HVjZEB1-4nmQ"
GDRIVE_FOLDER_URL = (
    f"https://drive.google.com/drive/folders/{GDRIVE_RENDERED_FOLDER_ID}"
)
BUFFER_API_URL = "https://api.buffer.com"
PUBLISHED_LEDGER = "published.json"
ET_TZ = ZoneInfo("America/New_York")

BUFFER_TOKEN = os.environ.get("BUFFER_API_KEY")
CHANNEL_ID = os.environ.get("BUFFER_INSTAGRAM_CHANNEL_ID")
REPO_NAME = os.environ.get(
    "GITHUB_REPOSITORY", "swaltnuscord-sketch/thegirlbeforehim-insta-aut"
)
EVENT_NAME = os.environ.get("GITHUB_EVENT_NAME", "schedule")

if not BUFFER_TOKEN or not CHANNEL_ID:
  print(
      "Error: Missing BUFFER_API_KEY or BUFFER_INSTAGRAM_CHANNEL_ID in secrets."
  )
  sys.exit(1)

published_ids = []
if os.path.exists(PUBLISHED_LEDGER):
  with open(PUBLISHED_LEDGER, "r", encoding="utf-8") as f:
    published_ids = json.load(f)

os.makedirs("staging", exist_ok=True)
subprocess.run(
    [
        sys.executable,
        "-m",
        "gdown",
        "--folder",
        GDRIVE_FOLDER_URL,
        "-O",
        "staging/",
    ],
    check=True,
)

for zpath in sorted(glob.glob("staging/**/*.zip", recursive=True)):
  with zipfile.ZipFile(zpath, "r") as zf:
    zf.extractall("staging")

matches = sorted(glob.glob("staging/**/manifest*.json", recursive=True))
if not matches:
  print("No manifest*.json found in Google Drive 03_Rendered_Posts folder.")
  sys.exit(0)

now_et = datetime.now(ET_TZ).replace(tzinfo=None)
print(f"Current US Eastern Time: {now_et.isoformat()}")

due_by_pid = {}
for path in matches:
  with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

  pid = str(data.get("post_index") or data.get("post_id") or "")
  if not pid or pid in published_ids:
    continue

  if data.get("manual_ig_app") is True:
    print(f"Skipping post {pid}: flagged for manual Instagram app upload.")
    continue

  slot_str = data.get("scheduled_at_est") or data.get("scheduled_at_et")
  if slot_str:
    slot_dt = datetime.fromisoformat(slot_str)
    diff_seconds = (slot_dt - now_et).total_seconds()
    if diff_seconds <= 25 * 60:
      if pid not in due_by_pid or data.get("slides_text"):
        due_by_pid[pid] = (slot_dt.isoformat(), path, data)
  elif EVENT_NAME == "workflow_dispatch":
    if pid not in due_by_pid or data.get("slides_text"):
      due_by_pid[pid] = (data.get("generated_at", ""), path, data)

due_posts = sorted(due_by_pid.values(), key=lambda x: x[0])
if not due_posts:
  print("No @thegirlbeforehim posts are due right now. Exiting cleanly.")
  sys.exit(0)

print(f"Found {len(due_posts)} due post(s) to process.")

subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
subprocess.run(
    [
        "git",
        "config",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    ],
    check=True,
)

owner, repo = REPO_NAME.split("/")
staged_posts = []

for _, target_manifest, manifest in due_posts:
  post_id = str(manifest.get("post_index") or manifest.get("post_id"))
  day_num = int(manifest.get("day", 0))
  slot_num = int(manifest.get("slot", 0))
  fmt = manifest.get("format", "C")
  bg_hex = manifest.get("bg_hex", "#FBF8F3")
  slides_text = manifest.get("slides_text") or []

  is_reel = (
      fmt == "REEL"
      or manifest.get("as_reel") is True
      or (fmt == "A" and slot_num == 5 and day_num % 3 == 0 and manifest.get("as_reel") is not False and len(slides_text) > 0)
  )

  rel_folder = f"day_{day_num:02d}_slot_{slot_num}"

  if is_reel:
    print(f"Generating faceless 10s Reel for post {post_id} (Day {day_num}, Slot {slot_num})")
    video_dir = os.path.join("docs", "videos", rel_folder)
    os.makedirs(video_dir, exist_ok=True)
    reel_path = os.path.join(video_dir, "reel.mp4")
    render_reel_mp4(slides_text, bg_hex, reel_path, post_id=post_id)
    reel_url = f"https://{owner}.github.io/{repo}/videos/{rel_folder}/reel.mp4"
    staged_posts.append((post_id, manifest, [reel_url], True))
    continue

  print(f"Staging image media for post {post_id} (Day {day_num}, Slot {slot_num}, Format {fmt})")
  staging_dir = os.path.dirname(target_manifest)
  slide_files = manifest.get("slide_filenames") or []
  if not slide_files and manifest.get("image_filename"):
    slide_files = [manifest["image_filename"]]

  if not slide_files and slides_text:
    slide_files = [f"slide_{i:02d}.png" for i in range(1, len(slides_text) + 1)]

  if not slide_files:
    print(f"Error: No slide filenames listed in {target_manifest}.")
    sys.exit(1)

  if len(slide_files) > 10:
    print(
        f"Warning: {len(slide_files)} slides found; Meta Content Publishing API"
        " caps automated carousels at 10 slides. Truncating to first 10."
    )
    slide_files = slide_files[:10]

  target_dir = os.path.join("docs", "images", rel_folder)
  os.makedirs(target_dir, exist_ok=True)
  pages_base = f"https://{owner}.github.io/{repo}/images/{rel_folder}"

  public_urls = []
  for idx, fname in enumerate(slide_files, 1):
    src = os.path.join(staging_dir, fname)
    if not os.path.exists(src):
      if idx - 1 < len(slides_text):
        print(f"Rendering {fname} in GitHub Actions for post {post_id}...")
        render_slide(
            slides_text[idx - 1],
            bg_hex,
            src,
            is_hook=(idx == 1),
            slide_num=idx,
            total_slides=len(slide_files),
            seed=int(post_id) * 100 + idx,
        )
      else:
        print(f"Error: Expected slide image {src} not found.")
        sys.exit(1)
    shutil.copyfile(src, os.path.join(target_dir, fname))
    public_urls.append(f"{pages_base}/{fname}")

  staged_posts.append((post_id, manifest, public_urls, False))

subprocess.run(["git", "add", "docs/"], check=True)
diff_check = subprocess.run(["git", "diff", "--cached", "--quiet"])
if diff_check.returncode != 0:
  subprocess.run(
      ["git", "commit", "-m", "Stage GitHub Pages media for due posts"],
      check=True,
  )
  subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
  subprocess.run(["git", "push", "origin", "main"], check=True)

mutation = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post { id text status }
    }
    ... on MutationError { message }
  }
}
"""

for idx, (post_id, manifest, public_urls, is_reel) in enumerate(staged_posts):
  print(f"Verifying GitHub Pages availability for post {post_id}: {public_urls[0]}")
  for _ in range(18):
    try:
      r = requests.head(public_urls[0], timeout=5, allow_redirects=True)
      if r.status_code == 200:
        print("GitHub Pages media is live (HTTP 200).")
        break
    except requests.RequestException:
      pass
    time.sleep(5)
  else:
    print("Warning: GitHub Pages did not return HTTP 200 within 90s; proceeding.")

  caption = manifest.get("caption", "").strip()
  hashtags = manifest.get("hashtags", "").strip()
  full_text = f"{caption}\n\n{hashtags}".strip()

  if is_reel:
    assets = [{"video": {"url": public_urls[0], "metadata": {"thumbnailOffset": 1000}}}]
    ig_type = "reel"
  else:
    assets = [{"image": {"url": url}} for url in public_urls]
    ig_type = "post"

  slot_str = manifest.get("scheduled_at_est") or manifest.get("scheduled_at_et")
  mode = "shareNow"
  due_at_iso = None
  if slot_str:
    slot_dt_et = datetime.fromisoformat(slot_str).replace(tzinfo=ET_TZ)
    slot_dt_utc = slot_dt_et.astimezone(timezone.utc)
    if slot_dt_utc > datetime.now(timezone.utc):
      mode = "customScheduled"
      due_at_iso = slot_dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

  post_input = {
      "channelId": CHANNEL_ID,
      "text": full_text,
      "schedulingType": "automatic",
      "mode": mode,
      "assets": assets,
      "metadata": {"instagram": {"type": ig_type, "shouldShareToFeed": True}},
  }
  if due_at_iso:
    post_input["dueAt"] = due_at_iso

  response = requests.post(
      BUFFER_API_URL,
      json={"query": mutation, "variables": {"input": post_input}},
      headers={
          "Authorization": f"Bearer {BUFFER_TOKEN}",
          "Content-Type": "application/json",
      },
      timeout=30,
  )

  res_json = response.json()
  print(f"Buffer Response for post {post_id}:\n", json.dumps(res_json, indent=2))

  if "errors" in res_json or "message" in res_json.get("data", {}).get(
      "createPost", {}
  ):
    print(f"Buffer failed to create post {post_id}.")
    sys.exit(1)

  published_ids.append(post_id)
  with open(PUBLISHED_LEDGER, "w", encoding="utf-8") as f:
    json.dump(published_ids, f, indent=2)
    f.write("\n")

  print(f"Post {post_id} queued in Buffer and recorded in {PUBLISHED_LEDGER}.")
  if idx < len(staged_posts) - 1:
    time.sleep(10)
