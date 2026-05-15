# PROJECT MANIFEST: SOCIALPROOFREEL
**Status:** MVP Development Phase[cite: 1].
**Vision:** Automated GMB review videos (15-30s) used as a high-conversion lead magnet for leandrovenegas.cl[cite: 1].

## CORE ROLES (The Triad)
- **Russell:** Focus on the conversion funnel. The video is the bait to trigger a sales call[cite: 1].
- **Architect:** Focus on local batch processing and Supabase synchronization[cite: 1].
- **Producer:** Focus on vertical 9:16 aesthetics and clean, readable typography[cite: 1].

## PRIMARY WORKFLOW
1. Listen to Supabase 'video_queue' table[cite: 1].
2. Download asset configuration from 'settings' table[cite: 1].
3. Execute FFmpeg rendering locally[cite: 1].
4. Upload to Bunny.net and update Supabase status[cite: 1].

## EXECUTION ENVIRONMENT (DOCKER)
- **Host OS:** Ubuntu 26.04 (Development only).
- **Runtime:** Docker Container `socialproof-worker`.
- **Image Base:** `playwright/python:v1.45.0-jammy` (Ubuntu 24.04).
- **Volume Mapping:** Local project folder mapped to `/app` inside the container.
- **CLI Task:** The agent must only write code and provide the Docker command for execution. Do NOT attempt to run scripts or install packages on the host.

## FILOSOFÍA DE DESARROLLO (MODULARIZACIÓN CRÍTICA)
1. **Aislamiento Total:** Cada script (`scraper_engine.py`, `core_render.py`, `uploader.py`) debe ser "tonto" respecto al resto. 
2. **Comunicación vía Assets:** Un módulo no llama al otro. El Scraper deja archivos en `/app/temp/` y el Renderizador los toma de ahí cuando detecta que están listos.
3. **Resiliencia:** Si el Scraper falla, el Renderizador debe poder seguir trabajando con los leads ya materializados. Si Bunny.net falla, el Renderizador no se detiene.
4. **Validación Manual:** El flujo debe permitir ejecutar el Scraper para una sola URL, generar la carpeta local y permitirme revisar el `metadata.json` antes de lanzar el Render.