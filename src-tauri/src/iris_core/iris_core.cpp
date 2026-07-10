#include "iris_core.h"
#include "db_manager.h"
#include "caducean.h"
#include "event_ingestor.h"
#include <iostream>
#include <cstring>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <algorithm>
#include <string>
#include <vector>
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

// --- Pre-existing utilities (restored — were missing from C++ side) ---

extern "C" IRIS_API int simulate_trajectories_to_db(int n, int steps, double a, double b, double s) {
    if (n <= 0 || steps <= 0) return -1;
    // Generate n synthetic sessions, each running `steps` updates with
    // the given (a, b, s) parameters. Used by Domain 18 benchmark
    // (test_iris_core_simulate.py) to generate test data without
    // touching the live DB.
    // Returns the total number of trajectory rows written (= n * steps).
    int written = 0;
    for (int i = 0; i < n; ++i) {
        std::string sid = "sim_" + std::to_string(i);
        Caducean::get_instance().init_session(sid, 1, 1);
        Caducean::get_instance().set_params(sid, a, b, s);
        for (int j = 0; j < steps; ++j) {
            // Alternate actions; balance=1.0 is a neutral update
            Caducean::get_instance().update(sid, j % 2, 1.0);
            written += 1;
        }
    }
    return written;
}

// --- v2: Caducean Mitochondria-to-Mycelium Upgrade FFI Wrappers ---

extern "C" IRIS_API int caducean_init_session(const char* session_id, int l, int m) {
    if (!session_id) return 1;
    Caducean::get_instance().init_session(session_id, l, m);
    return 0;
}

extern "C" IRIS_API int caducean_get_direction_signal(const char* session_id, double balance, IrisDirectionSignal* out) {
    if (!session_id || !out) return 1;
    DirectionSignal sig = Caducean::get_instance().get_direction_signal(session_id, balance);
    out->target_u = sig.target_u;
    out->force_magnitude = sig.force_magnitude;
    out->u_current = sig.u_current;
    out->phase = sig.phase;
    out->balance = sig.balance;
    return 0;
}

extern "C" IRIS_API int caducean_set_params(const char* session_id, double a, double b, double s) {
    if (!session_id) return 1;
    Caducean::get_instance().set_params(session_id, a, b, s);
    return 0;
}

extern "C" IRIS_API int caducean_get_state(const char* session_id,
                                             double* out_x, double* out_y,
                                             double* out_xi, double* out_u,
                                             double* out_a, double* out_b, double* out_s,
                                             double* out_c_eff) {
    if (!session_id) return 1;
    SessionState s = Caducean::get_instance().get_state(session_id);
    if (out_x)     *out_x     = static_cast<double>(s.x);
    if (out_y)     *out_y     = static_cast<double>(s.y);
    if (out_xi)    *out_xi    = s.xi;
    if (out_u)     *out_u     = s.u;
    if (out_a)     *out_a     = s.a;
    if (out_b)     *out_b     = s.b;
    if (out_s)     *out_s     = s.s;
    if (out_c_eff) *out_c_eff = s.c_eff;
    return 0;
}

extern "C" IRIS_API double caducean_calculate_eml(const char* session_id, double* out_x, double* out_y) {
    if (!session_id) return 0.0;
    SessionState s = Caducean::get_instance().get_state(session_id);
    // O(1) field-theory formula from SessionState (x, y) accumulators.
    // This is the v2 path that bypasses SQL — pure field-theory arithmetic.
    const double Ne = static_cast<double>(s.x);
    const double Nt = static_cast<double>(s.y);
    const double L  = std::min(Ne, Nt);
    const double V  = Ne + Nt + 1.0;
    const double x_eml = (Ne / (1.0 + Nt)) * (1.0 - L / V);
    const double y_eml = (Nt / (1.0 + Ne)) * (L / V) + 1e-5;
    const double eml  = std::exp(x_eml) - std::log(y_eml);
    if (out_x) *out_x = Ne;
    if (out_y) *out_y = Nt;
    return eml;
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

// --- Immortus trajectory-conditioned query (W7/O1) ---
// Mirror of backend/gateway/iris_ffi.py::_PythonFallbackEngine.
// immortus_chain_query_by_coordinate. Returns a malloc'd JSON array string;
// the caller frees it via free_cstring().

// Parse exactly 4 comma-separated floats into out[4]. Returns false otherwise.
static bool iris_parse_coord4(const char* text, double out[4]) {
    if (!text) return false;
    double vals[4] = {0, 0, 0, 0};
    int idx = 0;
    const char* p = text;
    const char* start = text;
    while (true) {
        if (*p == ',' || *p == '\0') {
            if (idx >= 4) return false;
            std::string tok(start, p);
            try {
                size_t pos = 0;
                vals[idx] = std::stod(tok, &pos);
                if (pos != tok.size()) return false;
            } catch (...) {
                return false;
            }
            idx++;
            if (*p == '\0') break;
            start = p + 1;
        }
        p++;
    }
    if (idx != 4) return false;
    for (int i = 0; i < 4; ++i) out[i] = vals[i];
    return true;
}

static std::string iris_json_escape(const std::string& in) {
    std::string out;
    out.reserve(in.size() + 8);
    for (char c : in) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x",
                                  static_cast<unsigned int>(
                                      static_cast<unsigned char>(c)));
                    out += buf;
                } else {
                    out += c;
                }
        }
    }
    return out;
}

static std::string iris_col_text(sqlite3_stmt* stmt, int col) {
    const unsigned char* t = sqlite3_column_text(stmt, col);
    return t ? std::string(reinterpret_cast<const char*>(t)) : std::string();
}

// Returns "null" for SQL NULL, otherwise a JSON-escaped quoted string.
static std::string iris_json_value(sqlite3_stmt* stmt, int col) {
    if (sqlite3_column_type(stmt, col) == SQLITE_NULL) return "null";
    return "\"" + iris_json_escape(iris_col_text(stmt, col)) + "\"";
}

extern "C" IRIS_API char* immortus_chain_query_by_coordinate(
    const char* coords,
    double threshold,
    int limit,
    const char* thread_id,
    const char* nbl_outcome
) {
    auto emit_empty = []() -> char* {
        char* s = static_cast<char*>(std::malloc(3));
        std::strcpy(s, "[]");
        return s;
    };

    double target[4] = {0, 0, 0, 0};
    if (!iris_parse_coord4(coords, target)) return emit_empty();

    DBManager::ReadGuard guard;
    if (!guard) return emit_empty();
    sqlite3* conn = guard.get();

    std::string sql =
        "SELECT chain_id, thread_id, result, coords_from, coords_to, "
        "nbl_outcome, insight, file_path, landmark_id FROM memory_chain WHERE 1=1";
    std::vector<std::string> binds;
    if (thread_id && *thread_id) {
        sql += " AND thread_id = ?";
        binds.push_back(thread_id);
    }
    if (nbl_outcome && *nbl_outcome) {
        sql += " AND nbl_outcome = ?";
        binds.push_back(nbl_outcome);
    }
    sql += ";";

    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(conn, sql.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) return emit_empty();

    for (size_t i = 0; i < binds.size(); ++i) {
        sqlite3_bind_text(stmt, static_cast<int>(i + 1),
                          binds[i].c_str(), -1, SQLITE_STATIC);
    }

    struct Row { double dist; std::string json; };
    std::vector<Row> rows;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        double cf[4] = {0, 0, 0, 0};
        if (!iris_parse_coord4(iris_col_text(stmt, 3).c_str(), cf)) continue;
        double d = 0.0;
        for (int k = 0; k < 4; ++k) {
            double diff = cf[k] - target[k];
            d += diff * diff;
        }
        d = std::sqrt(d);
        if (d > threshold) continue;

        std::string obj = "{";
        obj += "\"chain_id\":" + iris_json_value(stmt, 0) + ",";
        obj += "\"thread_id\":" + iris_json_value(stmt, 1) + ",";
        obj += "\"result\":" + iris_json_value(stmt, 2) + ",";
        obj += "\"coords_from\":" + iris_json_value(stmt, 3) + ",";
        obj += "\"coords_to\":" + iris_json_value(stmt, 4) + ",";
        obj += "\"nbl_outcome\":" + iris_json_value(stmt, 5) + ",";
        obj += "\"insight\":" + iris_json_value(stmt, 6) + ",";
        obj += "\"file_path\":" + iris_json_value(stmt, 7) + ",";
        obj += "\"landmark_id\":" + iris_json_value(stmt, 8) + ",";
        obj += "\"distance\":" + std::to_string(d);
        obj += "}";
        rows.push_back({d, obj});
    }
    sqlite3_finalize(stmt);

    std::sort(rows.begin(), rows.end(),
              [](const Row& a, const Row& b) { return a.dist < b.dist; });
    if (limit > 0 && rows.size() > static_cast<size_t>(limit)) {
        rows.resize(static_cast<size_t>(limit));
    }

    std::string out = "[";
    for (size_t i = 0; i < rows.size(); ++i) {
        if (i) out += ",";
        out += rows[i].json;
    }
    out += "]";

    char* result = static_cast<char*>(std::malloc(out.size() + 1));
    std::memcpy(result, out.c_str(), out.size() + 1);
    return result;
}

extern "C" IRIS_API void free_cstring(char* s) {
    if (s) std::free(s);
}
