#include "iris_core.h"
#include "db_manager.h"
#include "caducean.h"
#include "event_ingestor.h"
#include <iostream>
#include <cstring>
#include <cmath>
#include <sqlite3.h>

// ============================================================================
// IRIS Hybrid C++ Core Memory Engine — FFI Gateway (Phase 4 Complete)
// All FFI functions wired to actual C++ component implementations.
// ============================================================================

static bool g_initialized = false;

// --- Lifecycle Management ---

extern "C" IRIS_API int init_core_engine(const char* db_path, const char* key_hex) {
    if (!db_path || !key_hex) {
        std::cerr << "[IRIS_CORE] init_core_engine: null argument" << std::endl;
        return -1;
    }
    if (std::strlen(key_hex) != 64) {
        std::cerr << "[IRIS_CORE] init_core_engine: key_hex must be 64 chars" << std::endl;
        return -2;
    }

    int rc = DBManager::get_instance().initialize(db_path, key_hex);
    if (rc != 0) {
        std::cerr << "[IRIS_CORE] DBManager initialization failed: " << rc << std::endl;
        return rc;
    }

    g_initialized = true;
    std::cout << "[IRIS_CORE] Initialized successfully" << std::endl;
    return 0;
}

extern "C" IRIS_API int shutdown_core_engine() {
    DBManager::get_instance().shutdown();
    g_initialized = false;
    std::cout << "[IRIS_CORE] Shutdown complete" << std::endl;
    return 0;
}

extern "C" IRIS_API int core_health_check() {
    if (!g_initialized) return 0;
    return DBManager::get_instance().is_healthy() ? 1 : 0;
}

// --- Event Ingestion ---

extern "C" IRIS_API int ingest_event(
    const char* session_id,
    const char* domain,
    const char* event_type,
    const char* actor,
    const char* outcome,
    const char* summary,
    const char* payload_json
) {
    if (!session_id || !domain || !event_type || !actor || !outcome || !summary) {
        return -1;
    }

    bool ok = EventIngestor::get_instance().record(
        session_id, domain, event_type, actor, outcome, summary,
        payload_json ? payload_json : "{}"
    );
    return ok ? 0 : -1;
}

// --- Caducean Attention Governor ---

extern "C" IRIS_API int caducean_recommend(const char* session_id) {
    if (!session_id) return 2; // MAINTAIN on null
    return Caducean::get_instance().recommend(session_id);
}

extern "C" IRIS_API double caducean_get_xi(const char* session_id) {
    if (!session_id) return 0.0;
    return Caducean::get_instance().get_xi(session_id);
}

extern "C" IRIS_API void caducean_update(const char* session_id, int action, double balance) {
    if (!session_id) return;
    Caducean::get_instance().update(session_id, action, balance);
}

// --- EML Calculation ---

extern "C" IRIS_API double calculate_eml(const char* session_id, double* out_x, double* out_y) {
    if (!session_id || !out_x || !out_y) return 0.0;

    DBManager::ReadGuard guard;
    sqlite3* db = guard.get();
    if (!db) return 0.0;

    int edit_count = 0;
    int test_count = 0;
    int landmark_count = 0;
    int node_count = 0;

    sqlite3_stmt* stmt = nullptr;

    // 1. Count distinct edits in last 3 turns (recency-bound per spec)
    const char* edit_q =
        "SELECT COUNT(DISTINCT interaction_payload) FROM ("
        "SELECT interaction_payload FROM system_events "
        "WHERE session_id = ? AND event_domain = 'CODE' AND event_type = 'file_edit' "
        "ORDER BY created_at DESC LIMIT 3)";

    if (sqlite3_prepare_v2(db, edit_q, -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, session_id, -1, SQLITE_TRANSIENT);
        if (sqlite3_step(stmt) == SQLITE_ROW) edit_count = sqlite3_column_int(stmt, 0);
        sqlite3_finalize(stmt);
        stmt = nullptr;
    }

    // 2. Count successful tests in last 3 turns (recency-bound per spec)
    const char* test_q =
        "SELECT COUNT(*) FROM ("
        "SELECT 1 FROM system_events "
        "WHERE session_id = ? AND event_domain = 'CODE' AND event_type = 'test_run' AND outcome = 'success' "
        "ORDER BY created_at DESC LIMIT 3)";

    if (sqlite3_prepare_v2(db, test_q, -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, session_id, -1, SQLITE_TRANSIENT);
        if (sqlite3_step(stmt) == SQLITE_ROW) test_count = sqlite3_column_int(stmt, 0);
        sqlite3_finalize(stmt);
        stmt = nullptr;
    }

    // 3. Count crystallized landmarks (activation_count >= 12)
    const char* lm_q = "SELECT COUNT(*) FROM mycelium_landmarks WHERE activation_count >= 12;";
    if (sqlite3_prepare_v2(db, lm_q, -1, &stmt, nullptr) == SQLITE_OK) {
        if (sqlite3_step(stmt) == SQLITE_ROW) landmark_count = sqlite3_column_int(stmt, 0);
        sqlite3_finalize(stmt);
        stmt = nullptr;
    }

    // 4. Count total active file nodes (fallback to system_events for this session)
    const char* node_q = "SELECT COUNT(*) FROM system_events WHERE session_id = ?;";
    if (sqlite3_prepare_v2(db, node_q, -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, session_id, -1, SQLITE_TRANSIENT);
        if (sqlite3_step(stmt) == SQLITE_ROW) node_count = sqlite3_column_int(stmt, 0);
        sqlite3_finalize(stmt);
        stmt = nullptr;
    }

    // 5. EML v2 formula per implementation_plan.md Section 4.2
    //    x = Ne/(1+Nt) * (1 - L/V)
    //    y = Nt/(1+Ne) * (L/V) + 1e-5
    //    EML = e^x - ln(y)
    double Ne = static_cast<double>(edit_count);
    double Nt = static_cast<double>(test_count);
    double L  = static_cast<double>(landmark_count);
    double V  = static_cast<double>(node_count > 0 ? node_count : 1);

    double x = (Ne / (1.0 + Nt)) * (1.0 - (L / V));
    double y = (Nt / (1.0 + Ne)) * (L / V) + 1e-5;  // epsilon prevents ln(0)

    *out_x = x;
    *out_y = y;

    return std::exp(x) - std::log(y);
}

// --- Immortus Memory Chain ---

extern "C" IRIS_API int immortus_chain_append(
    const char* thread_id,
    const char* result,
    const char* coords_from,
    const char* coords_to,
    const char* nbl_outcome,
    const char* insight,
    const char* file_path,
    const char* landmark_id
) {
    if (!thread_id || !result) return -1;

    auto& db = DBManager::get_instance();
    std::string chain_id = EventIngestor::get_instance().generate_sqlite_uuid();

    auto future = db.execute_async_write([
        chain_id, thread_id_str = std::string(thread_id), result_str = std::string(result),
        cf = coords_from ? std::string(coords_from) : std::string(),
        ct = coords_to   ? std::string(coords_to)   : std::string(),
        no = nbl_outcome ? std::string(nbl_outcome) : std::string(),
        ins = insight    ? std::string(insight)    : std::string(),
        fp = file_path   ? std::string(file_path)   : std::string(),
        lm = landmark_id ? std::string(landmark_id) : std::string(),
        has_cf = !!coords_from, has_ct = !!coords_to, has_no = !!nbl_outcome,
        has_ins = !!insight, has_fp = !!file_path, has_lm = !!landmark_id
    ](sqlite3* conn) -> int {
        const char* sql =
            "INSERT INTO memory_chain (chain_id, thread_id, result, coords_from, coords_to, "
            "nbl_outcome, insight, file_path, landmark_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?, CAST((julianday('now') - 2440587.5) * 86400000 AS REAL));";
        sqlite3_stmt* stmt = nullptr;
        int rc = sqlite3_prepare_v2(conn, sql, -1, &stmt, nullptr);
        if (rc != SQLITE_OK) return rc;

        sqlite3_bind_text(stmt, 1, chain_id.c_str(),       -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 2, thread_id_str.c_str(),   -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 3, result_str.c_str(),      -1, SQLITE_STATIC);
        if (has_cf) sqlite3_bind_text(stmt, 4, cf.c_str(), -1, SQLITE_STATIC);
        else        sqlite3_bind_null(stmt, 4);
        if (has_ct) sqlite3_bind_text(stmt, 5, ct.c_str(), -1, SQLITE_STATIC);
        else        sqlite3_bind_null(stmt, 5);
        if (has_no) sqlite3_bind_text(stmt, 6, no.c_str(), -1, SQLITE_STATIC);
        else        sqlite3_bind_null(stmt, 6);
        if (has_ins) sqlite3_bind_text(stmt, 7, ins.c_str(), -1, SQLITE_STATIC);
        else         sqlite3_bind_null(stmt, 7);
        if (has_fp) sqlite3_bind_text(stmt, 8, fp.c_str(), -1, SQLITE_STATIC);
        else        sqlite3_bind_null(stmt, 8);
        if (has_lm) sqlite3_bind_text(stmt, 9, lm.c_str(), -1, SQLITE_STATIC);
        else        sqlite3_bind_null(stmt, 9);

        rc = sqlite3_step(stmt);
        sqlite3_finalize(stmt);
        if (rc != SQLITE_DONE) {
            std::cerr << "[IRIS_CORE] immortus_chain_append failed: "
                      << sqlite3_errmsg(conn) << std::endl;
            return rc;
        }
        return SQLITE_OK;
    });

    // Wait for synchronous commit
    int res = future.get();
    return res == SQLITE_OK ? 0 : -1;
}

extern "C" IRIS_API int immortus_chain_keep_latest(const char* thread_id, int keep_count) {
    if (!thread_id || keep_count < 1) return -1;

    auto& db = DBManager::get_instance();

    std::string sql =
        "DELETE FROM memory_chain WHERE thread_id = '" + std::string(thread_id) +
        "' AND chain_id NOT IN ("
        "SELECT chain_id FROM memory_chain WHERE thread_id = '" + std::string(thread_id) +
        "' ORDER BY created_at DESC LIMIT " + std::to_string(keep_count) + ");";

    auto future = db.execute_async_write([sql](sqlite3* conn) -> int {
        char* err_msg = nullptr;
        int rc = sqlite3_exec(conn, sql.c_str(), nullptr, nullptr, &err_msg);
        if (rc != SQLITE_OK) {
            std::cerr << "[IRIS_CORE] immortus_chain_keep_latest failed: "
                      << (err_msg ? err_msg : "unknown") << std::endl;
            sqlite3_free(err_msg);
            return -1;
        }
        return sqlite3_changes(conn);  // number of rows deleted
    });

    // Wait for synchronous commit
    return future.get();
}
