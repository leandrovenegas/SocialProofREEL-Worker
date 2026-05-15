# MISSION: SocialProofREEL
**Status:** MVP Development Phase.
**Core Concept:** Automated GMB review videos (15-30s) as "Bait" for high-ticket funnels.

## THE TRIAD ROLES (Permanent Context)
1. **Russell:** Marketing & Conversion. Every asset must lead to leandrovenegas.cl.
2. **Architect:** Local rendering (Home PC) + Bunny.net CDN + Vercel Dashboard.
3. **Producer:** Vertical 9:16, premium aesthetics, clean typography.

## TECHNICAL STACK
- Backend: Python + FFmpeg (Local processing).
- Hosting: Bunny.net (Bunny Stream API).
- Frontend: Next.js (https://github.com/hexclave/multi-tenant-starter-template.git).
- Database: 6,000 leads.

## ARCHITECTURAL TRUTH
- Do NOT rewrite existing logic.
- Prioritize low-token consumption.
- The Vercel Dashboard is a "Canvas" for aesthetic control, not for rendering.
## DATA & SYNC (The Bridge)
- Intermediary: Supabase (PostgreSQL + Realtime).
- Communication: Dashboard writes to 'video_queue' and 'settings' tables. Local PC reads and processes.
- Preview Logic: Dashboard uses a CSS/Canvas mock-up for real-time preview (Low cost).

## OPTIMIZATION (FFmpeg)
- Format: H.264 (.mp4).
- Target Size: < 5MB per 15s video.
- Bitrate: 2M - 4M max.
- Audio: AAC 128k (IA Voiceover).
