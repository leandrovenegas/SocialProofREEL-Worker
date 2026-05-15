"""
core_render.py — SocialProofREEL Worker
========================================
DUMB RENDERER: Reads metadata.json from /app/temp/leads/{id}/ and
produces a single 9:16 MP4 (3 review slides concatenated, ~18s).
Does NOT call the Scraper. Communicates only via the local bridge files.

PIPELINE:
  For each review in metadata.json:
    render_review_slide() → slide_0.mp4, slide_1.mp4, slide_2.mp4
  Then:
    concatenate_slides()  → final_{business_id}.mp4
  Then (queue mode only):
    upload_to_bunny()     → CDN URL
    Update Supabase video_queue status

TEST (standalone — no Supabase needed):
  docker run --rm -v "$(pwd):/app" --env-file .env socialproof-worker \\
    python core_render.py /app/temp/leads/{business_id}
"""

import os
import sys
import json
import time
import glob
import subprocess
import textwrap
import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
FONT_PATH     = os.path.join(BASE_DIR, "Montserrat-Bold.ttf")
BASE_TEMP_DIR = os.path.join(BASE_DIR, "temp", "leads")

SUPABASE_URL  = os.getenv("SUPABASE_URL")
SUPABASE_KEY  = os.getenv("SUPABASE_KEY")

BUNNY_ACCESS_KEY = os.getenv("BUNNY_ACCESS_KEY")
STORAGE_ZONE     = os.getenv("STORAGE_ZONE")
PULL_ZONE_URL    = "https://socialproofreels.b-cdn.net/"

SLIDE_DURATION = 6   # seconds per review card
FPS            = 30
RESOLUTION     = "1080x1920"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wrap_text(text: str, width: int = 26) -> str:
    """Wraps text and returns a \\n-joined string safe for FFmpeg drawtext."""
    lines = textwrap.wrap(text or "", width=width, break_long_words=True)
    # FFmpeg drawtext uses literal \n — keep as Python newline; subprocess handles it
    return "\n".join(lines[:10])


def esc(text: str) -> str:
    """Escapes a string for use inside an FFmpeg drawtext filter value."""
    text = str(text)
    text = text.replace("\\", "\\\\")
    text = text.replace("'",  "\\'")
    text = text.replace(":",  "\\:")
    text = text.replace("%",  "\\%")
    # Replace actual newlines with FFmpeg's \n escape
    text = text.replace("\n", "\\n")
    return text


def stars(n: int) -> str:
    n = max(0, min(5, int(n)))
    return "*" * n + "-" * (5 - n)   # ASCII-safe, works with any Latin font


# ---------------------------------------------------------------------------
# STEP 1 — Render one review slide
# ---------------------------------------------------------------------------

def render_review_slide(
    business_name: str,
    overall_rating: float,
    review: dict,
    slide_path: str,
    font: str = FONT_PATH,
    duration: int = SLIDE_DURATION,
) -> bool:
    """
    Renders a single 9:16 review card as an MP4 slide.

    Visual layout (dark theme, 1080×1920):
      ┌─────────────────────────────┐
      │  [avatar 180×180, centered] │
      │  Business Name              │
      │  Overall rating  ****-      │
      │ ─────────────────────────── │
      │  Review rating  *****       │
      │  "Review text wrapped..."   │
      │  — Reviewer Name            │
      │ ─────────────────────────── │
      │  leandrovenegas.cl          │
      └─────────────────────────────┘
    """
    avatar_path = review.get("avatar_local_path")
    has_avatar  = bool(avatar_path and os.path.exists(str(avatar_path)))

    b_name       = esc(business_name[:40])
    o_stars      = esc(f"[{stars(round(overall_rating))}]  {overall_rating}")
    r_stars      = esc(f"[{stars(review.get('rating', 5))}]")
    review_text  = esc(wrap_text(review.get("review_text", ""), width=26))
    reviewer     = esc("- " + review.get("reviewer_name", "Anonymous")[:30])
    font_esc     = font.replace(":", "\\:")

    cmd = ["ffmpeg", "-y"]

    # Input 0: solid dark background
    cmd += ["-f", "lavfi", "-i",
            f"color=c=0x0F0F1A:size=1080x1920:rate={FPS}:duration={duration}"]

    # Input 1: avatar (optional)
    if has_avatar:
        cmd += ["-loop", "1", "-t", str(duration), "-i", str(avatar_path)]

    # ---- filter_complex ----
    chains = []

    if has_avatar:
        chains.append("[1:v]scale=180:180[av]")
        chains.append("[0:v][av]overlay=x=450:y=160[bg]")
        prev = "[bg]"
    else:
        prev = "[0:v]"

    # Top label
    chains.append(
        f"{prev}drawtext=fontfile='{font_esc}'"
        f":text='resenas de Google'"
        f":fontsize=28:fontcolor=0xAAAAAA:x=(w-text_w)/2:y=90[f0]"
    )
    # Business name
    chains.append(
        f"[f0]drawtext=fontfile='{font_esc}'"
        f":text='{b_name}'"
        f":fontsize=56:fontcolor=white:x=(w-text_w)/2:y=380"
        f":shadowx=2:shadowy=2:shadowcolor=black[f1]"
    )
    # Overall rating
    chains.append(
        f"[f1]drawtext=fontfile='{font_esc}'"
        f":text='{o_stars}'"
        f":fontsize=36:fontcolor=0xFFD700:x=(w-text_w)/2:y=455[f2]"
    )
    # Divider 1
    chains.append(
        "[f2]drawbox=x=90:y=520:w=900:h=2:color=0xFFFFFF@0.12:t=fill[f3]"
    )
    # Review rating
    chains.append(
        f"[f3]drawtext=fontfile='{font_esc}'"
        f":text='{r_stars}'"
        f":fontsize=50:fontcolor=0xFFD700:x=(w-text_w)/2:y=555[f4]"
    )
    # Review text
    chains.append(
        f"[f4]drawtext=fontfile='{font_esc}'"
        f":text='{review_text}'"
        f":fontsize=40:fontcolor=white:x=(w-text_w)/2:y=650"
        f":line_spacing=12:fix_bounds=true[f5]"
    )
    # Reviewer name
    chains.append(
        f"[f5]drawtext=fontfile='{font_esc}'"
        f":text='{reviewer}'"
        f":fontsize=32:fontcolor=0xAAAACC:x=(w-text_w)/2:y=1380[f6]"
    )
    # Divider 2
    chains.append(
        "[f6]drawbox=x=90:y=1440:w=900:h=2:color=0xFFFFFF@0.12:t=fill[f7]"
    )
    # Watermark
    chains.append(
        f"[f7]drawtext=fontfile='{font_esc}'"
        f":text='leandrovenegas.cl'"
        f":fontsize=26:fontcolor=0xFFFFFF@0.35:x=(w-text_w)/2:y=1830[out]"
    )

    cmd += ["-filter_complex", ";".join(chains)]
    cmd += ["-map", "[out]",
            "-vcodec", "libx264", "-crf", "24", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-t", str(duration),
            slide_path]

    print(f"[FFmpeg] Rendering: {os.path.basename(slide_path)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[FFmpeg] ERROR rendering slide:\n{result.stderr[-3000:]}")
        return False
    print(f"[FFmpeg] ✓ {slide_path}")
    return True


# ---------------------------------------------------------------------------
# STEP 2 — Concatenate slides
# ---------------------------------------------------------------------------

def concatenate_slides(slide_paths: list, output_path: str) -> bool:
    """Concatenates multiple slide MP4s into a single final video."""
    if not slide_paths:
        print("[CONCAT] No slides to concatenate.")
        return False

    if len(slide_paths) == 1:
        import shutil
        shutil.copy(slide_paths[0], output_path)
        print(f"[CONCAT] Single slide copied → {output_path}")
        return True

    cmd = ["ffmpeg", "-y"]
    for sp in slide_paths:
        cmd += ["-i", sp]

    n = len(slide_paths)
    fc = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1[out]"

    cmd += ["-filter_complex", fc,
            "-map", "[out]",
            "-vcodec", "libx264", "-crf", "22", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            output_path]

    print(f"[CONCAT] Joining {n} slides → {os.path.basename(output_path)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[CONCAT] ERROR:\n{result.stderr[-3000:]}")
        return False
    print(f"[CONCAT] ✓ Final video: {output_path}")
    return True


# ---------------------------------------------------------------------------
# STEP 3 — Upload to Bunny.net
# ---------------------------------------------------------------------------

def upload_to_bunny(file_path: str, business_id: str) -> str | None:
    """Uploads the final MP4 to Bunny.net Storage. Returns the CDN URL or None."""
    if not BUNNY_ACCESS_KEY or not STORAGE_ZONE:
        print("[BUNNY] Credentials not set — skipping upload.")
        return None

    filename = f"socialproof_{business_id}.mp4"
    url      = f"https://storage.bunnycdn.com/{STORAGE_ZONE}/{filename}"
    headers  = {"AccessKey": BUNNY_ACCESS_KEY, "Content-Type": "application/octet-stream"}

    print(f"[BUNNY] Uploading {filename}...")
    with open(file_path, "rb") as f:
        resp = requests.put(url, data=f, headers=headers, timeout=120)

    if resp.status_code == 201:
        cdn_url = f"{PULL_ZONE_URL}{filename}"
        print(f"[BUNNY] ✓ {cdn_url}")
        return cdn_url
    else:
        print(f"[BUNNY] Upload failed ({resp.status_code}): {resp.text}")
        return None


# ---------------------------------------------------------------------------
# PUBLIC ENTRYPOINT — render_lead_from_metadata
# ---------------------------------------------------------------------------

def render_lead_from_metadata(lead_dir: str) -> str | None:
    """
    Full render pipeline for one lead folder.

    Args:
        lead_dir: Path to /app/temp/leads/{business_id}/

    Returns:
        Path to the final MP4, or None on failure.
    """
    metadata_path = os.path.join(lead_dir, "metadata.json")
    if not os.path.exists(metadata_path):
        print(f"[RENDER] metadata.json not found in {lead_dir}")
        return None

    with open(metadata_path, encoding="utf-8") as f:
        meta = json.load(f)

    business_id   = meta["business_id"]
    business_name = meta.get("business_name", "Negocio")
    overall_rating = meta.get("overall_rating", 5.0)
    reviews        = meta.get("reviews", [])

    if not reviews:
        print(f"[RENDER] No reviews in metadata — nothing to render.")
        return None

    print(f"\n[RENDER] === {business_name} ({overall_rating}★) — {len(reviews)} reviews ===")

    # Render individual slides
    slide_paths = []
    for i, review in enumerate(reviews[:3]):
        slide_path = os.path.join(lead_dir, f"slide_{i}.mp4")
        ok = render_review_slide(
            business_name=business_name,
            overall_rating=overall_rating,
            review=review,
            slide_path=slide_path,
        )
        if ok:
            slide_paths.append(slide_path)
        else:
            print(f"[RENDER] Slide {i} failed — skipping.")

    if not slide_paths:
        print("[RENDER] All slides failed.")
        return None

    # Concatenate
    final_path = os.path.join(lead_dir, f"final_{business_id}.mp4")
    if not concatenate_slides(slide_paths, final_path):
        return None

    # Cleanup intermediate slides
    for sp in slide_paths:
        try:
            os.remove(sp)
        except OSError:
            pass

    print(f"[RENDER] ✓ Done → {final_path}")
    return final_path


# ---------------------------------------------------------------------------
# QUEUE MODE — process_queue (Supabase listener)
# ---------------------------------------------------------------------------

def process_queue():
    """
    Polls Supabase video_queue for pending leads and processes them.
    Each queue row must have a 'lead_dir' field pointing to the local
    temp folder produced by scraper_engine.py.
    """
    from supabase import create_client
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("[QUEUE] Worker started. Polling video_queue...")

    while True:
        try:
            rows = (
                supabase.table("video_queue")
                .select("*")
                .eq("status", "pending")
                .execute()
                .data
            )

            if not rows:
                time.sleep(10)
                continue

            for row in rows:
                lead_id  = row["id"]
                lead_dir = row.get("lead_dir", os.path.join(BASE_TEMP_DIR, row.get("business_id", lead_id)))
                print(f"\n[QUEUE] Processing lead: {lead_id}")

                supabase.table("video_queue").update({"status": "processing"}).eq("id", lead_id).execute()

                final_path = render_lead_from_metadata(lead_dir)

                if final_path:
                    bunny_url = upload_to_bunny(final_path, lead_id)
                    if bunny_url:
                        supabase.table("video_queue").update({
                            "status": "completed",
                            "bunny_url": bunny_url,
                        }).eq("id", lead_id).execute()
                        try:
                            os.remove(final_path)
                        except OSError:
                            pass
                        print(f"[QUEUE] ✓ Lead {lead_id} completed: {bunny_url}")
                    else:
                        supabase.table("video_queue").update({"status": "upload_failed"}).eq("id", lead_id).execute()
                else:
                    supabase.table("video_queue").update({"status": "render_failed"}).eq("id", lead_id).execute()

        except Exception as e:
            print(f"[QUEUE] Error: {e}")
            time.sleep(10)


# ---------------------------------------------------------------------------
# CLI — standalone render test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Auto-detect the most recent lead folder
        folders = sorted(glob.glob(os.path.join(BASE_TEMP_DIR, "*")), key=os.path.getmtime, reverse=True)
        if not folders:
            print("Usage: python core_render.py <lead_dir>")
            print("No lead folders found in", BASE_TEMP_DIR)
            sys.exit(1)
        lead_dir = folders[0]
        print(f"[CLI] Auto-selected most recent lead: {lead_dir}")
    else:
        lead_dir = sys.argv[1]

    result = render_lead_from_metadata(lead_dir)
    if not result:
        print("[CLI] Render failed.")
        sys.exit(1)
    print(f"\n[CLI] Video ready: {result}")
