# @thegirlbeforehim Instagram Automation Relay

Automated Google Drive -> GitHub Pages -> Buffer GraphQL publishing relay for **@thegirlbeforehim** (*"letters to the girl i was"*).

## Architecture
1. **Google Drive Staging** ([Root Folder](https://drive.google.com/drive/folders/1SHjA70U9Ld9ANE3-mVJmbXIqGwpwhMD0)):
   - `01_Strategy_and_Prompts` (`1jd9LM-8gMnZ5-xtj6PiL-14xrri3xztQ`)
   - `02_Content_CSVs` (`1XNlwa2LYCq6fdwRUvowWZhqvJ-NQXFIB`)
   - `03_Rendered_Posts` (`1ocIfVmkQgdw4txcpMVx_HVjZEB1-4nmQ`)
   - `04_Published_Logs` (`1WkkJNYAnYFaaIlY_JH3aVvUb4oWZ2lZ-`)
2. **GitHub Actions Cron Relay** (`.github/workflows/publish_buffer.yml`):
   - Runs **20 minutes before** each of the 7 daily EST slots (`12:10`, `16:40`, `20:10`, `23:10`, `01:40`, `03:10`, `05:10` UTC).
   - Pulls staged slide PNGs + `manifest.json` from `03_Rendered_Posts` via `gdown`.
   - Publishes static images to `docs/images/` (served via GitHub Pages).
   - Pushes single-image posts (Format C) and carousels (Format A / up to 10-slide Format B) to Buffer's GraphQL API (`https://api.buffer.com`).
   - Tracks published post indices in `published.json` to prevent duplicates.

## Required Repository Setup
1. **GitHub Secrets** (`Settings -> Secrets and variables -> Actions`):
   - `BUFFER_API_KEY`: Your Buffer API bearer token
   - `BUFFER_INSTAGRAM_CHANNEL_ID`: The Buffer channel ID for `@thegirlbeforehim`
2. **GitHub Pages** (`Settings -> Pages`):
   - Set **Source** to `Deploy from a branch`, branch `main`, folder `/docs`.
   - Ensure the repository is **Public** (required for GitHub Pages on GitHub Free) so Buffer and Meta's Graph API can fetch the hosted PNG URLs.
3. **Actions Permissions** (`Settings -> Actions -> General`):
   - Enable **Read and write permissions** under Workflow permissions so the relay can commit to `docs/images/` and `published.json`.
