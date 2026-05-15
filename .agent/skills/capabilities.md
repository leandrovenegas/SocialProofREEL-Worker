## CAPABILITIES (Local Worker)
- **Scraping:** Extracting GMB reviews (text, rating, avatar)[cite: 1].
- **Video Engine:** Advanced FFmpeg composition (image, blur, text overlays)[cite: 1].
- **Sync:** Real-time polling or listening to Supabase PostgreSQL changes[cite: 1].
- **Storage:** Direct integration with Bunny Stream API for video hosting[cite: 1].
## FILOSOFÍA DE DESARROLLO (MODULARIZACIÓN CRÍTICA)
1. **Aislamiento Total:** Cada script (`scraper_engine.py`, `core_render.py`, `uploader.py`) debe ser "tonto" respecto al resto. 
2. **Comunicación vía Assets:** Un módulo no llama al otro. El Scraper deja archivos en `/app/temp/` y el Renderizador los toma de ahí cuando detecta que están listos.
3. **Resiliencia:** Si el Scraper falla, el Renderizador debe poder seguir trabajando con los leads ya materializados. Si Bunny.net falla, el Renderizador no se detiene.
4. **Validación Manual:** El flujo debe permitir ejecutar el Scraper para una sola URL, generar la carpeta local y permitirme revisar el `metadata.json` antes de lanzar el Render.
