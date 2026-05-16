"""
enqueue_leads.py — SocialProofREEL
===================================
Reads raw_leads (processed=false) and creates video_queue entries.

Pre-screening logic:
  - reviews = 0  → skip to lead_rejections (saves API quota)
  - reviews >= 1 → insert into video_queue with maps_url

Run on server:
  docker run --rm -v $(pwd):/app --env-file .env socialproof-worker python enqueue_leads.py
"""

import os
import sys
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

MIN_REVIEWS = int(os.getenv("MIN_REVIEWS", "1"))
BATCH_SIZE  = 50


def enqueue():
    print("[ENQUEUE] Fetching unprocessed leads from raw_leads...")

    offset = 0
    total_queued    = 0
    total_rejected  = 0
    total_skipped   = 0

    while True:
        res = supabase.table("raw_leads") \
            .select("*") \
            .eq("processed", False) \
            .limit(BATCH_SIZE) \
            .offset(offset) \
            .execute()

        rows = res.data
        if not rows:
            break

        queue_batch     = []
        rejection_batch = []

        for row in rows:
            data          = row.get("raw_data", {})
            business_name = data.get("name", "")
            maps_url      = data.get("url", "")
            reviews       = data.get("reviews", 0)
            rating        = data.get("rating", 0)

            if not business_name:
                total_skipped += 1
                continue

            if reviews < MIN_REVIEWS:
                # Pre-screen: no reviews in source data, skip API call
                rejection_batch.append({
                    "business_name":    business_name,
                    "reason_code":      "no_reviews_prescreen",
                    "error_message":    f"Source data shows {reviews} reviews (min: {MIN_REVIEWS})",
                    "original_lead_id": row["id"],
                })
            else:
                queue_batch.append({
                    "business_name": business_name,
                    "maps_url":      maps_url,
                    "status":        "pending",
                })

        # Insert qualified leads into video_queue
        if queue_batch:
            supabase.table("video_queue").insert(queue_batch).execute()
            total_queued += len(queue_batch)

        # Archive rejected leads
        if rejection_batch:
            supabase.table("lead_rejections").insert(rejection_batch).execute()
            total_rejected += len(rejection_batch)

        # Mark all as processed
        ids = [r["id"] for r in rows]
        supabase.table("raw_leads").update({"processed": True}).in_("id", ids).execute()

        print(f"[ENQUEUE] Batch {offset//BATCH_SIZE + 1}: "
              f"+{len(queue_batch)} queued, +{len(rejection_batch)} rejected")

        offset += BATCH_SIZE

    print(f"\n[DONE] Queued: {total_queued} | Rejected: {total_rejected} | Skipped: {total_skipped}")


if __name__ == "__main__":
    enqueue()
