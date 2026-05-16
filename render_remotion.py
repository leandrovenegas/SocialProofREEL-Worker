"""
render_remotion.py — SocialProofREEL Worker
=============================================
BRIDGE SCRIPT: Replaces core_render.py for the new Remotion workflow.
Reads metadata.json from /app/temp/leads/{id}/, optionally fetches the global
settings config from Supabase (or reads it from the dashboard JSON), and 
executes the Remotion Node.js rendering process.
"""

import os
import sys
import json
import hashlib
import subprocess
import shutil
from dotenv import load_dotenv

load_dotenv()

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
BASE_TEMP_DIR = os.path.join(BASE_DIR, "videos_locales")
REMOTION_DIR  = os.path.join(BASE_DIR, "remotion_engine")

def render_lead_with_remotion(lead_dir: str) -> str | None:
    """
    Calls Remotion to render the video.
    """
    metadata_path = os.path.join(lead_dir, "metadata.json")
    if not os.path.exists(metadata_path):
        print(f"[REMOTION_BRIDGE] metadata.json not found in {lead_dir}")
        return None

    with open(metadata_path, encoding="utf-8") as f:
        meta = json.load(f)

    business_name = meta.get("business_name", "Negocio")
    
    print(f"\n[REMOTION_BRIDGE] === Starting Remotion for {business_name} ===")

    # Determine final video path version
    version = 1
    while True:
        final_path = os.path.join(lead_dir, f"video_v{version}.mp4")
        if not os.path.exists(final_path):
            break
        version += 1

    # To bypass Remotion's file:// security and Google's 429 rate limit, 
    # we copy the images to the public folder so they are served statically.
    business_id = os.path.basename(os.path.normpath(lead_dir))
    public_leads_dir = os.path.join(REMOTION_DIR, "public", "leads", business_id)
    os.makedirs(public_leads_dir, exist_ok=True)
    
    # Copy background and avatars
    if os.path.exists(os.path.join(lead_dir, "background.jpg")):
        shutil.copy(os.path.join(lead_dir, "background.jpg"), public_leads_dir)
    for i in range(5):
        if os.path.exists(os.path.join(lead_dir, f"avatar_{i}.jpg")):
            shutil.copy(os.path.join(lead_dir, f"avatar_{i}.jpg"), public_leads_dir)
    
    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",        # Entry point for remotion
        "SocialProofReel",     # Composition ID (we will create this in React)
        final_path,            # Output MP4
        "--props", metadata_path
    ]

    print(f"[REMOTION_BRIDGE] Command: {' '.join(cmd)}")
    
    try:
        # Run Remotion inside the remotion_engine folder
        result = subprocess.run(
            cmd,
            cwd=REMOTION_DIR,
            capture_output=True,
            text=True,
            check=True
        )
        print(f"[REMOTION_BRIDGE] ✓ Done → {final_path}")
        return final_path
    except subprocess.CalledProcessError as e:
        print(f"[REMOTION_BRIDGE] ERROR rendering video:")
        print(e.stdout)
        print(e.stderr)
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python render_remotion.py <business_name_or_folder_path>")
        sys.exit(1)

    arg = sys.argv[1]
    if os.path.isdir(arg) and os.path.exists(os.path.join(arg, "metadata.json")):
        lead_dir = arg
    else:
        business_id = hashlib.md5(arg.encode("utf-8")).hexdigest()
        lead_dir = os.path.join(BASE_TEMP_DIR, business_id)

    if not os.path.exists(lead_dir):
        print(f"[CLI] Error: Directory not found: {lead_dir}")
        sys.exit(1)

    result = render_lead_with_remotion(lead_dir)
    if not result:
        print("[CLI] Render failed.")
        sys.exit(1)
    print(f"\n[CLI] Video ready: {result}")
