import os
import time
import textwrap
import requests
from supabase import create_client, Client
from dotenv import load_dotenv
import ffmpeg

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_PATH = os.path.join(BASE_DIR, "Montserrat-Bold.ttf")
BG_PATH = os.path.join(BASE_DIR, "background_business.jpg")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

BUNNY_ACCESS_KEY = os.getenv("BUNNY_ACCESS_KEY")
STORAGE_ZONE = os.getenv("STORAGE_ZONE")
PULL_ZONE_URL = 'https://socialproofreels.b-cdn.net/'

def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def wrap_text(text, width=35):
    lines = textwrap.wrap(text, width=width)
    return "\n".join(lines)

def get_latest_settings(supabase_client):
    settings_data = supabase_client.table("settings").select("*").order("id", desc=True).limit(1).execute().data
    if not settings_data:
        # Fallback to default values if no settings are found
        return {
            "blur_level": 15,
            "primary_color": "#FFFFFF",
            "font_path": FONT_PATH # Use global FONT_PATH as default
        }

    latest_settings = settings_data[0]
    config = latest_settings.get("config")

    # Initialize processed settings with existing fields and defaults
    processed_settings = {
        "blur_level": latest_settings.get("blur_level", 15),
        "primary_color": latest_settings.get("primary_color", "#FFFFFF"),
        "font_path": FONT_PATH # Default to global FONT_PATH
    }

    if config and isinstance(config, dict):
        processed_settings["blur_level"] = config.get("blur_level", processed_settings["blur_level"])
        processed_settings["primary_color"] = config.get("primary_color", processed_settings["primary_color"])
        processed_settings["font_path"] = config.get("font_path", processed_settings["font_path"])

    return processed_settings

def upload_to_bunny(file_path, lead_id):
    filename = os.path.basename(file_path)
    url = f"https://storage.bunnycdn.com/{STORAGE_ZONE}/{filename}"
    
    headers = {
        "AccessKey": BUNNY_ACCESS_KEY,
        "Content-Type": "application/octet-stream"
    }
    
    with open(file_path, 'rb') as f:
        response = requests.put(url, data=f, headers=headers)
        
    if response.status_code == 201:
        return f"{PULL_ZONE_URL}{filename}"
    else:
        print(f"Upload failed: {response.text}")
        return None

def render_lead_video(lead_data, settings):
    output_file = os.path.join(BASE_DIR, f"output_{lead_data['id']}.mp4")
    review_text = wrap_text(lead_data.get('review_text', ''))
    
    blur_level = settings["blur_level"]
    primary_color = settings["primary_color"]
    box_color = primary_color.replace("#", "0x") + "@0.8"

    try:
        stream = ffmpeg.input(BG_PATH, loop=1, t=15)
        stream = ffmpeg.filter(stream, 'boxblur', lr=blur_level)
        stream = ffmpeg.drawtext(
            stream,
            text=f"{review_text}\n\n- {lead_data.get('reviewer_name', 'Anonymous')}",
            fontfile=settings["font_path"],
            fontsize=40,
            fontcolor='black' if primary_color.upper() == '#FFFFFF' else 'white',
            box=1,
            boxcolor=box_color,
            boxborderw=40,
            x='(w-text_w)/2',
            y='(h-text_h)/2',
            fix_bounds=True
        )
        stream = ffmpeg.output(
            stream, output_file, vcodec='libx264', crf=24, preset='fast',
            pix_fmt='yuv420p', r=30, s='1080x1920', video_bitrate='3M'
        ).overwrite_output()
        
        ffmpeg.run(stream, capture_stdout=True, capture_stderr=True)
        return output_file
    except ffmpeg.Error as e:
        print(f"FFmpeg Error: {e.stderr.decode('utf8')}")
        return None

def process_queue():
    supabase = get_supabase()
    print("Worker started. Listening to 'video_queue'...")
    
    while True:
        try:
            response = supabase.table("video_queue").select("*").eq("status", "pending").execute()
            
            if not response.data:
                time.sleep(10)
                continue
            
            for lead in response.data:
                lead_id = lead['id']
                print(f"Processing lead: {lead_id}")
                
                supabase.table("video_queue").update({"status": "processing"}).eq("id", lead_id).execute()
                settings = get_latest_settings(supabase)
                
                video_path = render_lead_video(lead, settings)
                
                if video_path:
                    bunny_url = upload_to_bunny(video_path, lead_id)
                    if bunny_url:
                        supabase.table("video_queue").update({
                            "status": "completed",
                            "bunny_url": bunny_url
                        }).eq("id", lead_id).execute()
                        
                        if os.path.exists(video_path):
                            os.remove(video_path)
                        print(f"Lead {lead_id} completed: {bunny_url}")
                    else:
                        supabase.table("video_queue").update({"status": "failed"}).eq("id", lead_id).execute()
                else:
                    supabase.table("video_queue").update({"status": "failed"}).eq("id", lead_id).execute()

        except Exception as e:
            print(f"Error in queue loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    process_queue()
