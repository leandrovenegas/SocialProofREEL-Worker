"""
inspect_db.py - Muestra estructura y datos de las tablas Supabase.
Correr en el servidor: docker run --rm -v $(pwd):/app --env-file .env socialproof-worker python inspect_db.py
"""

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

TABLES = ["video_queue", "lead_rejections", "raw_leads", "settings"]

for table in TABLES:
    print(f"\n{'='*60}")
    print(f"TABLE: {table}")
    print('='*60)
    try:
        res = supabase.table(table).select("*").limit(3).execute()
        rows = res.data
        if not rows:
            print("  (empty)")
        else:
            # Print column names
            print(f"  COLUMNS: {list(rows[0].keys())}")
            print(f"  ROWS ({len(rows)} shown):")
            for row in rows:
                print(f"  {row}")
    except Exception as e:
        print(f"  ERROR: {e}")

print("\n[DONE]")
