#ifndef DB_MANAGER_H
#define DB_MANAGER_H

#include <sqlite3.h>
#include <string>
#include <vector>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <thread>
#include <future>
#include <functional>
#include <atomic>

// ============================================================================
// DBManager — Async Single-Writer + Pre-Keyed Read Connection Pool
// ============================================================================
// Design:
//   - ONE dedicated writer thread with ONE sqlite3 connection (serialized writes)
//   - FOUR pre-opened, pre-keyed read connections in a pool (eliminates
//     repeated SQLCipher PBKDF2 key derivation overhead on every read)
//   - ReadGuard RAII class ensures connections are ALWAYS returned to the pool,
//     preventing leaks and deadlocks
//
// Audited safety features:
//   - hex_to_bytes: validates every character is valid hex (endptr + range check)
//   - is_healthy(): locks queue_mutex to prevent race with shutdown()
//   - run_writer_loop(): try/catch around task execution with set_exception
//   - PRAGMA cache_size=-2000: bounds each connection page cache to ~2MB
//     (4 connections × 2MB = ~8MB total pool memory, vs unbounded 32MB+)
// ============================================================================

class DBManager {
public:
    static constexpr size_t READ_POOL_SIZE = 4;
    static constexpr int PAGE_CACHE_PAGES = -2000;  // 512 pages × 4KB ≈ 2MB

    static DBManager& get_instance();

    // Delete copy/move — strict singleton
    DBManager(const DBManager&) = delete;
    DBManager& operator=(const DBManager&) = delete;
    DBManager(DBManager&&) = delete;
    DBManager& operator=(DBManager&&) = delete;

    // Lifecycle
    int initialize(const std::string& db_path, const std::string& key_hex);
    void shutdown();
    bool is_healthy();

    // Async write queue — serialized on dedicated writer thread
    std::future<int> execute_async_write(std::function<int(sqlite3*)> write_task);

    // Read connection pool — pre-keyed, no repeated PBKDF2 on acquire
    sqlite3* acquire_read_connection();
    void release_read_connection(sqlite3* conn);

    // RAII guard — auto-releases connection on scope exit (no leak possible)
    class ReadGuard {
    public:
        explicit ReadGuard(DBManager& mgr = get_instance());
        ~ReadGuard();
        ReadGuard(const ReadGuard&) = delete;
        ReadGuard& operator=(const ReadGuard&) = delete;
        ReadGuard(ReadGuard&& other) noexcept;
        ReadGuard& operator=(ReadGuard&& other) noexcept;

        sqlite3* get() const { return conn_; }
        explicit operator bool() const { return conn_ != nullptr; }

    private:
        DBManager* mgr_;
        sqlite3* conn_;
    };

    // Migration
    int run_migrations(sqlite3* db);

private:
    DBManager() = default;
    ~DBManager();

    // Connection helpers
    sqlite3* open_connection();
    int hex_to_bytes(const std::string& hex, unsigned char* bytes);

    // Writer thread
    void run_writer_loop();

    // Read pool
    void init_read_pool();
    void drain_read_pool();

    // State
    std::string db_file_path_;
    sqlite3* writer_db_ = nullptr;
    std::thread writer_thread_;
    std::atomic<bool> writer_running_{false};

    std::queue<std::pair<std::function<int(sqlite3*)>, std::promise<int>>> write_queue_;
    std::mutex queue_mutex_;
    std::condition_variable queue_cv_;

    // Read pool
    std::vector<sqlite3*> read_pool_;
    std::mutex pool_mutex_;
    std::condition_variable pool_cv_;

    // Encryption
    unsigned char encryption_key_[32] = {0};
    bool has_key_ = false;
};

#endif // DB_MANAGER_H
