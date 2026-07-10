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

/**
 * Pre-existing utility: generate N synthetic Caducean trajectories and
 * write them to the database. Used by Domain 18 benchmark tests.
 * @return Number of trajectories written (>= 0), or -1 on error.
 */
IRIS_API int simulate_trajectories_to_db(int n, int steps, double a, double b, double s);

/**
 * Pre-existing utility: prune an Immortus chain to keep the latest N
 * entries. Used by backend/api/chat.py on thread delete.
 * @return Number of entries kept (>= 0), or -1 on error.
 */
IRIS_API int immortus_chain_keep_latest(const char* thread_id, int keep_count);

// --- v2: Caducean Mitochondria-to-Mycelium Upgrade ---
// Bias-free physics signal exposed to callers. The agent kernel, voice kernel,
// TTS, and Mycelium all consume DirectionSignal — the physics is the program,
// the labels are the user interface.

/**
 * DirectionSignal C-compatible struct for FFI.
 * MUST stay binary-compatible with backend/gateway/iris_ffi.py::IrisDirectionSignal.
 * Field order is FROZEN — see Caducean v2 contract test test_caducean_ffi_contract.py.
 */
typedef struct {
    double target_u;          // +1.0 (expansion attractor) or -1.0 (compression attractor)
    double force_magnitude;   // |F(u)| = |a*u - b*u^3|
    double u_current;         // current attentional velocity
    double phase;             // current xi in [0, 2pi)
    double balance;           // EML-derived urgency in [0.1, 3.0]
} IrisDirectionSignal;

/**
 * Initialize a Caducean session with specific winding numbers (l, m).
 * Recomputes the effective cycle speed c_eff = (1/sqrt(2)) * sqrt(l^2 + m^2).
 * Idempotent: re-initializing updates l, m and recomputes c_eff.
 * @return 0 on success, 1 on error.
 */
IRIS_API int caducean_init_session(const char* session_id, int l, int m);

/**
 * Get the bias-free DirectionSignal for a session.
 * Returns a default signal (target_u=+1, balance=1.0) if session not found.
 * @return 0 on success, 1 on error (e.g. NULL out pointer).
 */
IRIS_API int caducean_get_direction_signal(const char* session_id, double balance, IrisDirectionSignal* out);

/**
 * Dynamically update the double-well potential constants and walk speed.
 * Bounds: a, b clamped to [1.0, 4.0]; s clamped to [0.1, 0.8].
 * @return 0 on success.
 */
IRIS_API int caducean_set_params(const char* session_id, double a, double b, double s);

/**
 * Get a full SessionState snapshot for a session (debug / health check).
 * Returned as 9 doubles: x, y, xi, u, a, b, s, c_eff, _padding.
 * (Padding aligns to 8 doubles for FFI stability.)
 */
IRIS_API int caducean_get_state(const char* session_id, double* out_x, double* out_y,
                                 double* out_xi, double* out_u,
                                 double* out_a, double* out_b, double* out_s,
                                 double* out_c_eff);

/**
 * v2: O(1) EML calculation directly from SessionState (x, y) accumulators.
 * This is the v2 path that bypasses SQL — pure field-theory formula:
 *   Ne = x, Nt = y, L = min(x,y), V = x + y + 1
 *   x_eml = (Ne/(1+Nt)) * (1 - L/V)
 *   y_eml = (Nt/(1+Ne)) * (L/V) + 1e-5
 *   EML = exp(x_eml) - log(y_eml)
 * @return EML score (double), or 0.0 if session not found.
 */
IRIS_API double caducean_calculate_eml(const char* session_id, double* out_x, double* out_y);

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

/**
 * Query the Immortus memory chain by coordinate proximity (W7/O1).
 * Mirrors backend/gateway/iris_ffi.py::_PythonFallbackEngine.immortus_chain_query_by_coordinate.
 * Returns a malloc'd JSON array string; caller frees it via free_cstring().
 * @param coords        Target coordinate "x,y,xi,u" (4 comma-separated floats).
 * @param threshold     Max Euclidean 4D distance to include.
 * @param limit         Max number of results (<=0 means no limit).
 * @param thread_id     Optional thread filter (nullable).
 * @param nbl_outcome   Optional nbl_outcome filter (nullable).
 * @return malloc'd JSON string (free with free_cstring()); "[]" on no match/error.
 */
IRIS_API char* immortus_chain_query_by_coordinate(
    const char* coords,
    double threshold,
    int limit,
    const char* thread_id,
    const char* nbl_outcome
);

/**
 * Free a string returned by immortus_chain_query_by_coordinate.
 */
IRIS_API void free_cstring(char* s);

#ifdef __cplusplus
}
#endif

#endif // IRIS_CORE_H
