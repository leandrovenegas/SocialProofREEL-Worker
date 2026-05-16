"""
sync_agent.py — SocialProofREEL Orchestrator
============================================
The Brain of the operation. Orchestrates the Places API and Core Render.
Can be run in CLI test mode or continuous Supabase daemon mode.

Modes:
  1. CLI: python sync_agent.py --test "Nombre del Local"
  2. Daemon: python sync_agent.py
"""

import os
import sys
import time
import subprocess
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

def update_supabase_status(supabase, lead_id: str, status: str, error_message: str = None, execution_time: float = None, video_path: str = None):
    """Updates the status of a job in Supabase."""
    if not supabase or not lead_id:
        return
    
    payload = {"status": status}
    if error_message:
        payload["error_message"] = error_message
    if execution_time is not None:
        payload["execution_time_seconds"] = execution_time
    if video_path:
        payload["local_video_path"] = video_path

    try:
        supabase.table("video_queue").update(payload).eq("id", lead_id).execute()
        print(f"[SUPABASE] Updated {lead_id} -> {status}")
    except Exception as e:
        print(f"[SUPABASE] X Failed to update status for {lead_id}: {e}")

def handle_lead_rejection(supabase, lead_id, business_name, reason, error_msg):
    """
    DLQ Pattern: Archives a lead that cannot be processed into 'lead_rejections' 
    and removes it from 'video_queue' to keep the queue clean.
    """
    if not supabase or not lead_id:
        return
    print(f"[ORCHESTRATOR] [REJECTION] Rejecting lead: {reason}")
    
    try:
        # 1. Archive to lead_rejections
        supabase.table("lead_rejections").insert({
            "original_lead_id": lead_id,
            "business_name": business_name,
            "reason_code": reason,
            "error_message": error_msg
        }).execute()
        
        # 2. Delete from video_queue
        supabase.table("video_queue").delete().eq("id", lead_id).execute()
        print(f"[ARCHIVE] Lead {lead_id} ({business_name}) moved to 'lead_rejections'.")
    except Exception as e:
        print(f"[SUPABASE] X Failed to archive/delete lead {lead_id}: {e}")

def run_pipeline(query: str, lead_id: str = None, supabase=None, business_name: str = None):
    """
    Executes the full pipeline: Places API -> Core Render.
    query: Maps URL or business name used for scraping.
    business_name: Human-readable name for logs/DB (defaults to query).
    """
    business_name = business_name or query
    print(f"\n{'='*50}")
    print(f"STARTING Pipeline for: '{business_name}'")
    print(f"{'='*50}")

    start_time = time.time()
    update_supabase_status(supabase, lead_id, "fetching_data")

    # Step 1: Places API
    try:
        print(f"\n[ORCHESTRATOR] Running places_api.py...")
        result = subprocess.run(
            ["python", "places_api.py", query],
            capture_output=True, text=True, check=True
        )
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        err_msg = f"Places API failed:\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
        print(f"[ORCHESTRATOR] X {err_msg}")
        
        # Detect specific rejection reasons
        if "[ERROR] No reviews returned" in e.stdout:
            handle_lead_rejection(supabase, lead_id, business_name, "no_reviews", err_msg)
        elif "ZERO_RESULTS" in e.stdout:
            handle_lead_rejection(supabase, lead_id, business_name, "not_found", err_msg)
        else:
            # Generic technical failure
            update_supabase_status(supabase, lead_id, "failed", error_message=err_msg)
            
        return False

    update_supabase_status(supabase, lead_id, "rendering")

    # Step 2: Core Render
    try:
        print(f"\n[ORCHESTRATOR] Running render_remotion.py...")
        result = subprocess.run(
            ["python", "render_remotion.py", business_name],
            capture_output=True, text=True, check=True
        )
        print(result.stdout)
        
        # Extract the video path from stdout
        video_path = None
        for line in result.stdout.split('\n'):
            if "[CLI] Video ready:" in line:
                video_path = line.split("[CLI] Video ready:")[1].strip()
                break

    except subprocess.CalledProcessError as e:
        err_msg = f"Core Render failed:\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
        print(f"[ORCHESTRATOR] X {err_msg}")
        update_supabase_status(supabase, lead_id, "failed", error_message=err_msg)
        return False

    # Success
    end_time = time.time()
    exec_time = round(end_time - start_time, 2)
    print(f"\n[ORCHESTRATOR] Pipeline completed in {exec_time}s")
    
    update_supabase_status(
        supabase, 
        lead_id, 
        "completed", 
        execution_time=exec_time,
        video_path=video_path
    )
    return True

def daemon_mode():
    """Continuous polling mode for Supabase."""
    from supabase import create_client
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[DAEMON] Error: SUPABASE_URL or SUPABASE_KEY not found in .env")
        sys.exit(1)

    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[DAEMON] Error connecting to Supabase: {e}")
        sys.exit(1)

    print("[DAEMON] Sync Agent started. Polling video_queue for 'pending' jobs...")

    while True:
        try:
            # Batch process: Get all pending jobs (limit 10 for now)
            response = supabase.table("video_queue").select("*").eq("status", "pending").limit(10).execute()
            rows = response.data

            if not rows:
                time.sleep(10)
                continue

            print(f"\n[DAEMON] Found {len(rows)} pending jobs in batch.")
            
            for row in rows:
                lead_id = row["id"]
                business_name = row.get("business_name") or "Unknown"
                # Use maps_url (has Place ID) for reliable lookup; fallback to name
                query = row.get("maps_url") or business_name
                
                run_pipeline(query, lead_id, supabase, business_name=business_name)

        except Exception as e:
            print(f"[DAEMON] Polling error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        if len(sys.argv) < 3:
            print("Usage: python sync_agent.py --test \"Nombre del Local\"")
            sys.exit(1)
        business_name = sys.argv[2]
        run_pipeline(business_name, business_name=business_name)
    else:
        daemon_mode()
