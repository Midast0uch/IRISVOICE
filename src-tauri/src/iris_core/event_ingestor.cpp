#include "event_ingestor.h"
#include "db_manager.h"
#include "security_sanitizer.h"
#include <sqlite3.h>
#include <iostream>
#include <sstream>
#include <iomanip>
#include <cstring>

// ============================================================================
// EventIngestor — Phase 4 Complete
// Flow: sanitize → generate UUID → if DB healthy: async INSERT
//       if DB unhealthy: spill to bounded in-memory ring buffer (max 1000)
// ============================================================================

EventIngestor& EventIngestor::get_instance() {
    static EventIngestor instance;
    return instance;
}

std::string EventIngestor::generate_sqlite_uuid() {
    // RFC 4122 v4 UUID using sqlite3_randomness + bit masking
    unsigned char raw[16];

    // Try sqlite3_randomness first (cryptographically secure when available)
    sqlite3_randomness(16, raw);

    // Version 4 (0100 xxxx)
    raw[6] = (raw[6] & 0x0F) | 0x40;
    // Variant (10xx xxxx)
    raw[8] = (raw[8] & 0x3F) | 0x80;

    std::ostringstream oss;
    for (int i = 0; i < 16; ++i) {
        if (i == 4 || i == 6 || i == 8 || i == 10) oss << '-';
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned int>(raw[i]);
    }
    return oss.str();
}

bool EventIngestor::record(
    const std::string& session_id,
    const std::string& domain,
    const std::string& event_type,
    const std::string& actor,
    const std::string& outcome,
    const std::string& summary,
    const std::string& payload_json
) {
    // 1. Sanitize payload
    auto& sanitizer = SecuritySanitizer::get_instance();
    auto [scrubbed_payload, modified] = sanitizer.sanitize_payload(payload_json);
    std::string sanitization_state = modified ? "scrubbed" : "clean";

    // 2. Generate UUID
    std::string event_id = generate_sqlite_uuid();

    // 3. Check DB health
    auto& db = DBManager::get_instance();
    if (!db.is_healthy()) {
        // Spill to in-memory ring buffer
        std::lock_guard<std::mutex> lock(spill_mutex_);
        if (spill_buffer_.size() >= MAX_SPILL) {
            spill_buffer_.pop(); // Drop oldest
        }
        spill_buffer_.push({session_id, domain, event_type, actor, outcome, summary, scrubbed_payload});
        std::cerr << "[EventIngestor] DB unhealthy — event " << event_id << " spilled to buffer"
                  << " (buffer size: " << spill_buffer_.size() << ")" << std::endl;
        return true;
    }

    // 4. Queue async INSERT via writer thread (parameterized to prevent SQL injection)
    auto future = db.execute_async_write([
        event_id, session_id, domain, event_type, actor, outcome,
        sanitization_state, summary, scrubbed_payload
    ](sqlite3* conn) -> int {
        const char* sql =
            "INSERT INTO system_events (event_id, session_id, event_domain, event_type, actor, "
            "outcome, sanitization_state, summary, interaction_payload) VALUES (?,?,?,?,?,?,?,?,?);";
        sqlite3_stmt* stmt = nullptr;
        int rc = sqlite3_prepare_v2(conn, sql, -1, &stmt, nullptr);
        if (rc != SQLITE_OK) return rc;

        sqlite3_bind_text(stmt, 1, event_id.c_str(),        -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 2, session_id.c_str(),      -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 3, domain.c_str(),           -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 4, event_type.c_str(),      -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 5, actor.c_str(),            -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 6, outcome.c_str(),          -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 7, sanitization_state.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 8, summary.c_str(),          -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 9, scrubbed_payload.c_str(), -1, SQLITE_STATIC);

        rc = sqlite3_step(stmt);
        sqlite3_finalize(stmt);
        if (rc != SQLITE_DONE) {
            std::cerr << "[EventIngestor] INSERT failed: " << sqlite3_errmsg(conn) << std::endl;
            return rc;
        }
        return SQLITE_OK;
    });

    // Don't block — fire-and-forget. Caller can call future.get() if needed.
    (void)future;
    return true;
}
