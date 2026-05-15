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
BASE_TEMP_DIR = os.path.join(BASE_DIR, "videos_locales")

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
    bg_path: str = None,
    font: str = FONT_PATH,
    duration: int = SLIDE_DURATION,
) -> bool:
    """
    Renders a single 9:16 review card as an MP4 slide.
    Uses Material Design aesthetics (Google Maps style).
    """
    avatar_path = review.get("avatar_local_path")
    has_avatar  = bool(avatar_path and os.path.exists(str(avatar_path)))

    b_name       = esc(business_name[:40])
    o_stars      = esc(f"[{stars(round(overall_rating))}]  {overall_rating}")
    r_stars      = esc(f"[{stars(review.get('rating', 5))}]")
    review_text  = esc(wrap_text(review.get("review_text", ""), width=20))
    reviewer     = esc(review.get("reviewer_name", "Anonymous")[:30])
    font_esc     = font.replace(":", "\\:")

    cmd = ["ffmpeg", "-y"]

    # Input 0: Background
    if bg_path and os.path.exists(bg_path):
        cmd += ["-loop", "1", "-t", str(duration), "-i", bg_path]
        has_bg_img = True
    else:
        cmd += ["-f", "lavfi", "-i", f"color=c=0x0F0F1A:size=1080x1920:rate={FPS}:duration={duration}"]
        has_bg_img = False

    # Input 1: Avatar (optional)
    if has_avatar:
        cmd += ["-loop", "1", "-t", str(duration), "-i", str(avatar_path)]

    # ---- filter_complex ----
    chains = []

    if has_bg_img:
        # Scale and crop background, then darken
        chains.append("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=15:5[bg_scaled]")
        chains.append("[bg_scaled]colorchannelmixer=rr=0.3:gg=0.3:bb=0.3[bg_dark]")
        prev = "[bg_dark]"
    else:
        prev = "[0:v]"

    if has_avatar:
        chains.append("[1:v]scale=432:432[av]")
        chains.append(f"{prev}[av]overlay=x=(W-432)/2:y=200[bg_av]")
        prev = "[bg_av]"

    # Top label
    chains.append(
        f"{prev}drawtext=fontfile='{font_esc}'"
        f":text='Reseñas de Google'"
        f":fontsize=40:fontcolor=0xAAAAAA:x=(w-text_w)/2:y=100[f0]"
    )
    # Reviewer Name (Now under avatar)
    chains.append(
        f"[f0]drawtext=fontfile='{font_esc}'"
        f":text='{reviewer}'"
        f":fontsize=56:fontcolor=white:x=(w-text_w)/2:y=660"
        f":shadowx=3:shadowy=3:shadowcolor=black[f1]"
    )
    # Review rating
    chains.append(
        f"[f1]drawtext=fontfile='{font_esc}'"
        f":text='{r_stars}'"
        f":fontsize=52:fontcolor=0xFBBC04:x=(w-text_w)/2:y=740[f2]"
    )
    # Divider 1
    chains.append(
        "[f2]drawbox=x=90:y=830:w=900:h=3:color=0xFFFFFF@0.15:t=fill[f3]"
    )
    # Review text
    chains.append(
        f"[f3]drawtext=fontfile='{font_esc}'"
        f":text='{review_text}'"
        f":fontsize=48:fontcolor=white:x=(w-text_w)/2:y=950"
        f":line_spacing=18:fix_bounds=true[f4]"
    )
    # Divider 2
    chains.append(
        "[f4]drawbox=x=90:y=1500:w=900:h=3:color=0xFFFFFF@0.15:t=fill[f5]"
    )
    # Business name (Now at the bottom)
    chains.append(
        f"[f5]drawtext=fontfile='{font_esc}'"
        f":text='{b_name}'"
        f":fontsize=50:fontcolor=white:x=(w-text_w)/2:y=1570"
        f":shadowx=2:shadowy=2:shadowcolor=black[f6]"
    )
    # Overall rating
    chains.append(
        f"[f6]drawtext=fontfile='{font_esc}'"
        f":text='{o_stars}'"
        f":fontsize=38:fontcolor=0xFBBC04:x=(w-text_w)/2:y=1640[f7]"
    )
    # Watermark
    chains.append(
        f"[f7]drawtext=fontfile='{font_esc}'"
        f":text='leandrovenegas.cl'"
        f":fontsize=32:fontcolor=0xFFFFFF@0.35:x=(w-text_w)/2:y=1820[out]"
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

def concatenate_slides(slide_paths: list, output_path: str, audio_path: str = None) -> bool:
    """Concatenates multiple slide MP4s into a single final video, with optional audio."""
    if not slide_paths:
        print("[CONCAT] No slides to concatenate.")
        return False

    cmd = ["ffmpeg", "-y"]
    for sp in slide_paths:
        cmd += ["-i", sp]

    n = len(slide_paths)
    fc = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1[out]"

    if audio_path and os.path.exists(audio_path):
        cmd += ["-i", audio_path]
        audio_idx = n
        cmd += ["-filter_complex", fc,
                "-map", "[out]",
                "-map", f"{audio_idx}:a",
                "-c:a", "aac", "-shortest",
                "-vcodec", "libx264", "-crf", "22", "-preset", "fast",
                "-pix_fmt", "yuv420p", "-r", str(FPS),
                output_path]
    else:
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
# PUBLIC ENTRYPOINT — render_lead_from_metadata
# ---------------------------------------------------------------------------

def render_lead_from_metadata(lead_dir: str) -> str | None:
    """
    Full render pipeline for one lead folder.
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

    bg_path = meta.get("background_local_path")
    audio_path = os.path.join(lead_dir, "audio.mp3")
    if not os.path.exists(audio_path):
        audio_path = None

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
            bg_path=bg_path
        )
        if ok:
            slide_paths.append(slide_path)
        else:
            print(f"[RENDER] Slide {i} failed — skipping.")

    if not slide_paths:
        print("[RENDER] All slides failed.")
        return None

    # Concatenate with versioning
    version = 1
    while True:
        final_path = os.path.join(lead_dir, f"video_v{version}.mp4")
        if not os.path.exists(final_path):
            break
        version += 1

    if not concatenate_slides(slide_paths, final_path, audio_path):
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
# CLI — standalone render test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python core_render.py <business_name_or_folder_path>")
        sys.exit(1)

    arg = sys.argv[1]
    if os.path.isdir(arg) and os.path.exists(os.path.join(arg, "metadata.json")):
        lead_dir = arg
    else:
        import hashlib
        business_id = hashlib.md5(arg.encode("utf-8")).hexdigest()
        lead_dir = os.path.join(BASE_TEMP_DIR, business_id)

    if not os.path.exists(lead_dir):
        print(f"[CLI] Error: Directory not found: {lead_dir}")
        sys.exit(1)

    result = render_lead_from_metadata(lead_dir)
    if not result:
        print("[CLI] Render failed.")
        sys.exit(1)
    print(f"\n[CLI] Video ready: {result}")
