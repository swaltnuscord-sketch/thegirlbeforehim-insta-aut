from datetime import datetime, timezone
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo
import requests

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

matches = glob.glob("staging/**/manifest*.json", recursive=True)
if not matches:
  print("No manifest*.json found in Google Drive 03_Rendered_Posts folder.")
  sys.exit(0)

now_et = datetime.now(ET_TZ).replace(tzinfo=None)
print(f"Current US Eastern Time: {now_et.isoformat()}")

due_posts = []
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
    # Trigger window: within 25 minutes before scheduled slot or already past
    diff_seconds = (slot_dt - now_et).total_seconds()
    if diff_seconds <= 25 * 60:
      due_posts.append((slot_dt.isoformat(), path, data))
  elif EVENT_NAME == "workflow_dispatch":
    due_posts.append((data.get("generated_at", ""), path, data))

if not due_posts:
  print("No @thegirlbeforehim posts are due right now. Exiting cleanly.")
  sys.exit(0)

_, target_manifest, manifest = min(due_posts, key=lambda x: x[0])
post_id = str(manifest.get("post_index") or manifest.get("post_id"))
day_num = manifest.get("day", "00")
slot_num = manifest.get("slot", "0")
fmt = manifest.get("format", "C")

print(f"Preparing post {post_id} (Day {day_num}, Slot {slot_num}, Format {fmt})")

staging_dir = os.path.dirname(target_manifest)
slide_files = manifest.get("slide_filenames") or []
if not slide_files and manifest.get("image_filename"):
  slide_files = [manifest["image_filename"]]

if not slide_files:
  print(f"Error: No slide filenames listed in {target_manifest}.")
  sys.exit(1)

if len(slide_files) > 10:
  print(
      f"Warning: {len(slide_files)} slides found; Meta Content Publishing API"
      " caps automated carousels at 10 slides. Truncating to first 10."
  )
  slide_files = slide_files[:10]

rel_folder = f"day_{int(day_num):02d}_slot_{slot_num}"
target_dir = os.path.join("docs", "images", rel_folder)
os.makedirs(target_dir, exist_ok=True)

owner, repo = REPO_NAME.split("/")
pages_base = f"https://{owner}.github.io/{repo}/images/{rel_folder}"

public_urls = []
for fname in slide_files:
  src = os.path.join(staging_dir, fname)
  if not os.path.exists(src):
    print(f"Error: Expected slide image {src} not found.")
    sys.exit(1)
  shutil.copyfile(src, os.path.join(target_dir, fname))
  public_urls.append(f"{pages_base}/{fname}")

# Commit & push images to GitHub Pages BEFORE calling Buffer
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
subprocess.run(["git", "add", "docs/images/"], check=True)
status_out = subprocess.run(
    ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
)
if status_out.stdout.strip():
  subprocess.run(
      ["git", "commit", "-m", f"Stage GitHub Pages media for post {post_id}"],
      check=True,
  )
  subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
  subprocess.run(["git", "push", "origin", "main"], check=True)

# Wait for GitHub Pages to serve the first image with HTTP 200 (up to 90s)
print(f"Verifying GitHub Pages availability: {public_urls[0]}")
for attempt in range(18):
  try:
    r = requests.head(public_urls[0], timeout=5, allow_redirects=True)
    if r.status_code == 200:
      print("GitHub Pages image is live (HTTP 200).")
      break
  except requests.RequestException:
    pass
  time.sleep(5)
else:
  print("Warning: GitHub Pages did not return HTTP 200 within 90s; proceeding.")

caption = manifest.get("caption", "").strip()
hashtags = manifest.get("hashtags", "").strip()
full_text = f"{caption}\n\n{hashtags}".strip()

assets = [{"image": {"url": url}} for url in public_urls]
ig_type = "carousel" if len(assets) > 1 else "post"

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
print("Buffer Response:\n", json.dumps(res_json, indent=2))

if "errors" in res_json or "message" in res_json.get("data", {}).get(
    "createPost", {}
):
  print("Buffer failed to create post.")
  sys.exit(1)

published_ids.append(post_id)
with open(PUBLISHED_LEDGER, "w", encoding="utf-8") as f:
  json.dump(published_ids, f, indent=2)
  f.write("\n")

print(f"Post {post_id} queued in Buffer and recorded in {PUBLISHED_LEDGER}.")
