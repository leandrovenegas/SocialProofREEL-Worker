Plan Arquitectónico v4.0: Sistema de Orquestación y Renderizado Local
Tus comentarios son muy acertados y apuntan a hacer el sistema no solo más robusto, sino comercialmente más atractivo ("estética Google Maps"). Estás en lo correcto respecto al rol del sync_agent: él es el cerebro y a él le pediremos las cosas de ahora en adelante.

Aquí está el plan final refinado.

Soluciones a tus nuevas observaciones
1. El Agente es el Cerebro (CLI Local)
Estás 100% en lo cierto. Ya no llamarás a core_render o places_api manualmente. El sync_agent.py tendrá dos modos:

Modo Automático (Servidor): Corre infinito escuchando a Supabase.
Modo Manual (CLI): Puedes ejecutar python sync_agent.py --test "Nombre del Local" y el agente se encargará de llamar al módulo de la API, esperar los datos, y luego llamar al Render. Todo con un solo comando.
2. Prioridad de 5 Estrellas (Fallback inteligente)
Excelente punto para no romper el video. La lógica en places_api.py será:

Obtener las reseñas.
Ordenarlas de mayor a menor calificación (5, luego 4, luego 3...).
Tomar las 3 mejores disponibles. Si un local tiene puro 1 estrella, el video se hará con reseñas de 1 estrella, mostrando la realidad del negocio tal como pides.
3. Fotos de Fondo Dinámicas
Nota Técnica: La API oficial de Google Places no permite extraer la foto específica que un usuario adjuntó a su reseña. Sin embargo, sí nos permite descargar las fotos oficiales del Local/Negocio. La solución: El places_api.py descargará la mejor foto disponible del negocio. El core_render.py tomará esa foto, la pondrá de fondo (quizás con un leve desenfoque o filtro oscuro para que las letras se lean bien) y pondrá la gráfica encima. Si el local no tiene fotos, usará tu color de fondo por defecto.

4. Estética "Google Maps" Realista
Rediseñaremos la composición en core_render.py para que parezca una captura real de Google:

Textos y tipografía significativamente más grandes.
Todo centrado para formato TikTok/Reels.
Avatar al 40% del ancho de pantalla (súper alta resolución).
Usaremos los colores típicos de Google (estrellas amarillas #fbbc04, textos legibles, nombre del usuario en gris, etc.).
Plan de Ejecución (Fases de Refactorización)
Fase 1: Crear places_api.py (Reemplazo del Scraper)
Limpiar dependencias viejas (Playwright no es necesario si solo usamos API).
Implementar la lógica de ordenamiento de reseñas (Priorizar 5 estrellas).
Añadir la descarga de 1 foto del negocio para usarla de fondo (Background).
Guardar todo estructuradamente en /videos_locales/hash_del_local/.
Fase 2: Rediseñar core_render.py
Adaptar el código de FFmpeg para soportar un fondo dinámico (imagen JPG).
Aplicar las nuevas coordenadas: Avatar gigante (432px), textos centrados, tipografías más grandes y colores de Google Maps.
Añadir capacidad de inyectar música de fondo.
Fase 3: Crear sync_agent.py (El Orquestador Maestro)
Programar el modo CLI (--test "Nombre") para que puedas usarlo de inmediato.
Programar el modo Supabase (Polling, Logs de tiempo, Control de versiones v1, Estado de errores failed).
⚠️ User Review Required
Con este plan, tenemos un producto automatizado, estéticamente fiel a Google y arquitectónicamente sólido.

Si estás de acuerdo con estos detalles finales (especialmente la técnica de usar las fotos del negocio como fondo), dime "Adelante" e iniciaré la escritura del código inmediatamente.