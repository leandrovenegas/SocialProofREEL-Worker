graph TD
    A[Start: process_queue loop] --> B(Connect to Supabase);
    B --> C{Query Supabase: video_queue (status='pending')};
    C -->|Found Lead| D[Update Supabase: video_queue status='processing'];
    D --> E{Get Latest Settings};
    E --> F[Query Supabase: settings table];
    F --> G{Parse config (JSONB) + Fallbacks};
    G --> H[Load Assets: BG_PATH, FONT_PATH];
    G --> H[Load Assets: BG_PATH, FONT_PATH];
    H --> I[Render Video: FFmpeg Process];
    I --> J[Generate Local Temp Video (.mp4)];
    J --> K[Upload to Bunny.net Storage];
    K --> L{Get Bunny URL};
    L --> M[Update Supabase: video_queue (status='completed', bunny_url)];
    M --> N[Delete Local Temp Video];
    N --> O[Continue Loop];
    C -->|No Pending Leads| O;
    O --> A;

    subgraph "core_render.py Components"
        B
        C
        D
        E
        F
        G
        H
        I
        J
        K
        L
        M
        N
        O
    end

    subgraph "External Services / Assets"
        Supabase[(Supabase)]
        BunnyStorage[Bunny.net Storage]
        BunnyPullZone[Bunny.net Pull Zone]
        FFmpeg[FFmpeg Engine]
        LocalAssets[(Local Assets: .ttf, .jpg)]
        TempVideo[(Local Temp Video: .mp4)]
    end

    B -- Creates Client --> Supabase;
    C -- Reads/Writes --> Supabase;
    D -- Writes --> Supabase;
    F -- Reads --> Supabase;
    M -- Writes --> Supabase;
    H -- Uses --> LocalAssets;
    I -- Uses --> FFmpeg;
    I -- Uses --> LocalAssets;
    I -- Generates --> TempVideo;
    K -- Uploads via API --> BunnyStorage;
    L -- Uses URL --> BunnyPullZone;
    N -- Deletes --> TempVideo;

    subgraph "Configuration Flow (get_latest_settings)"
        E --> F;
        F --> G;
        G -- Reads --> Config(config JSONB);
        G -- Fallbacks to --> OldFields(Old Fields/Defaults);
        G -- Uses --> FontGlobal(Global FONT_PATH);
    end