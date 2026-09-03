-- Migration 001: Modernized Memory, Immortus, and Security Schema
-- Used by both C++ DBManager::run_migrations() and Python fallback

-- system_events: immutable audit log of all system interactions
CREATE TABLE IF NOT EXISTS system_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_domain TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    outcome TEXT DEFAULT 'pending',
    sanitization_state TEXT NOT NULL,
    summary TEXT NOT NULL,
    interaction_payload TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_system_events_session ON system_events(session_id);
CREATE INDEX IF NOT EXISTS idx_system_events_domain_type ON system_events(event_domain, event_type);
CREATE INDEX IF NOT EXISTS idx_system_events_created ON system_events(created_at);

-- memory_chain: Immortus speculative memory chain entries
CREATE TABLE IF NOT EXISTS memory_chain (
    chain_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    result TEXT,
    coords_from TEXT,
    coords_to TEXT,
    nbl_outcome TEXT,
    insight TEXT,
    file_path TEXT,
    landmark_id TEXT,
    stale INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_chain_thread ON memory_chain(thread_id);
CREATE INDEX IF NOT EXISTS idx_memory_chain_stale ON memory_chain(stale);
CREATE INDEX IF NOT EXISTS idx_memory_chain_created ON memory_chain(created_at);

-- mycelium_landmarks: crystallized knowledge nodes (activation_count >= 12)
CREATE TABLE IF NOT EXISTS mycelium_landmarks (
    landmark_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    activation_count INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_landmarks_activation ON mycelium_landmarks(activation_count);
