#ifndef IRIS_CORE_H
#define IRIS_CORE_H

#ifdef __cplusplus
extern "C" {
#endif

// ============================================================================
// IRIS Hybrid C++ Core Memory Engine — FFI C-Interface
// Exports to Python via ctypes. All strings are UTF-8, null-terminated.
// ============================================================================

#ifdef _WIN32
    #define IRIS_API __declspec(dllexport)
#else
    #define IRIS_API __attribute__((visibility("default")))
#endif

// --- Lifecycle Management ---

/**
 * Initialize the C++ core engine.
 * @param db_path   Path to the SQLCipher database file (UTF-8).
 * @param key_hex   64-character hex string encryption key (PBKDF2-derived).
 * @return 0 on success, non-zero error code on failure.
 */
IRIS_API int init_core_engine(const char* db_path, const char* key_hex);

/**
 * Gracefully shut down the C++ core engine.
 * Closes writer thread, drains read pool, frees resources.
 * @return 0 on success.
 */
IRIS_API int shutdown_core_engine();

/**
 * Health check — returns 1 if writer thread and DB connection are healthy.
 * @return 1 if healthy, 0 if unhealthy.
 */
IRIS_API int core_health_check();

// --- Event Ingestion ---

/**
 * Ingest a system event. Sanitizes payload, generates UUID, queues for async write.
 * @param session_id    Session identifier (UTF-8).
 * @param domain        Event domain, e.g. "CODE", "USER", "SYSTEM" (UTF-8).
 * @param event_type    Event type, e.g. "file_edit", "test_run" (UTF-8).
 * @param actor         Actor identifier, e.g. "agent_kernel" (UTF-8).
 * @param outcome       Outcome string, e.g. "success", "failure" (UTF-8).
 * @param summary       Short human-readable summary (UTF-8).
 * @param payload_json  JSON string of interaction payload (UTF-8).
 * @return 0 on success, non-zero on failure.
 */
IRIS_API int ingest_event(
    const char* session_id,
    const char* domain,
    const char* event_type,
    const char* actor,
    const char* outcome,
    const char* summary,
    const char* payload_json
);

// --- Caducean Attention Governor ---

/**
 * Get the Caducean recommendation for a session.
 * @param session_id    Session identifier.
 * @return Recommendation code: 0=EXPAND, 1=CONTRACT, 2=MAINTAIN.
 */
IRIS_API int caducean_recommend(const char* session_id);

/**
 * Get the Caducean instability metric xi for a session.
 * @param session_id    Session identifier.
 * @return Xi value (double), or 0.0 if session not found.
 */
IRIS_API double caducean_get_xi(const char* session_id);

/**
 * Update the Caducean state for a session with an action and balance correction.
 * @param session_id    Session identifier.
 * @param action        0=EXPAND, 1=COMPRESS, 2=CONTINUE.
 * @param balance       Optional EML correction factor for phase update.
 */
IRIS_API void caducean_update(const char* session_id, int action, double balance);

// --- EML Calculation ---

/**
 * Calculate the Epistemic Metabolic Learning (EML) score for a session.
 * @param session_id    Session identifier.
 * @param out_x         Output pointer for x-axis drift.
 * @param out_y         Output pointer for y-axis drift.
 * @return EML score (double), or 0.0 on error.
 */
IRIS_API double calculate_eml(const char* session_id, double* out_x, double* out_y);

// --- Immortus Memory Chain ---

/**
 * Append a new chain entry to the Immortus memory chain.
 * @param thread_id     Thread identifier.
 * @param result        Result text.
 * @param coords_from   Source coordinates.
 * @param coords_to     Target coordinates.
 * @param nbl_outcome   NBL outcome string.
 * @param insight       Insight text.
 * @param file_path     Associated file path (nullable).
 * @param landmark_id   Landmark ID (nullable).
 * @return 0 on success.
 */
IRIS_API int immortus_chain_append(
    const char* thread_id,
    const char* result,
    const char* coords_from,
    const char* coords_to,
    const char* nbl_outcome,
    const char* insight,
    const char* file_path,
    const char* landmark_id
);

/**
 * Keep only the latest N entries in the Immortus chain for a thread.
 * @param thread_id     Thread identifier.
 * @param keep_count    Number of latest entries to retain.
 * @return Number of rows deleted, or -1 on error.
 */
IRIS_API int immortus_chain_keep_latest(const char* thread_id, int keep_count);

#ifdef __cplusplus
}
#endif

#endif // IRIS_CORE_H
