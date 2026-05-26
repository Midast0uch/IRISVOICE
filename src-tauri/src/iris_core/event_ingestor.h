#ifndef EVENT_INGESTOR_H
#define EVENT_INGESTOR_H

#include <string>
#include <vector>
#include <mutex>
#include <queue>
#include <condition_variable>

// Forward declaration
class DBManager;

// ============================================================================
// EventIngestor — Phase 4 Implementation
// Generates UUIDs, sanitizes payloads, queues for async DB write.
// Falls back to in-memory ring buffer if DB is unhealthy.
// ============================================================================

struct SpilledEvent {
    std::string session_id;
    std::string domain;
    std::string event_type;
    std::string actor;
    std::string outcome;
    std::string summary;
    std::string payload_json;
};

class EventIngestor {
public:
    static EventIngestor& get_instance();

    EventIngestor(const EventIngestor&) = delete;
    EventIngestor& operator=(const EventIngestor&) = delete;

    /**
     * Record an event. Sanitizes, generates UUID, queues for async write.
     * If DB is unhealthy, spills to in-memory ring buffer.
     * @return true on success (queued or spilled).
     */
    bool record(
        const std::string& session_id,
        const std::string& domain,
        const std::string& event_type,
        const std::string& actor,
        const std::string& outcome,
        const std::string& summary,
        const std::string& payload_json
    );

    std::string generate_sqlite_uuid();

private:
    EventIngestor() = default;

    std::mutex spill_mutex_;
    std::queue<SpilledEvent> spill_buffer_;
    static constexpr size_t MAX_SPILL = 1000;
};

#endif // EVENT_INGESTOR_H
