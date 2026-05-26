#include "db_manager.h"
#include <iostream>
#include <cstring>

// ============================================================================
// DBManager Implementation — Async Single-Writer + Pre-Keyed Read Pool
// ============================================================================

DBManager& DBManager::get_instance() {
    static DBManager instance;
    return instance;
}

DBManager::~DBManager() {
    if (writer_running_.load()) {
        shutdown();
    }
}

// --- Key Helpers ---

int DBManager::hex_to_bytes(const std::string& hex, unsigned char* bytes) {
    if (hex.length() != 64) return -1;
    for (size_t i = 0; i < 32; ++i) {
        char hi = hex[i * 2];
        char lo = hex[i * 2 + 1];
        auto nibble = [](char c) -> int {
            if (c >= '0' && c <= '9') return c - '0';
            if (c >= 'a' && c <= 'f') return c - 'a' + 10;
            if (c >= 'A' && c <= 'F') return c - 'A' + 10;
            return -1;
        };
        int a = nibble(hi);
        int b = nibble(lo);
        if (a < 0 || b < 0) return -2;
        bytes[i] = static_cast<unsigned char>((a << 4) | b);
    }
    return 0;
}

// --- Connection Factory ---

sqlite3* DBManager::open_connection() {
    sqlite3* db = nullptr;
    int rc = sqlite3_open(db_file_path_.c_str(), &db);
    if (rc != SQLITE_OK) {
        std::cerr << "[DB] Failed to open DB: " << sqlite3_errmsg(db) << std::endl;
        if (db) sqlite3_close(db);
        return nullptr;
    }

    #ifdef SQLCIPHER_AVAILABLE
    if (has_key_) {
        rc = sqlite3_key(db, encryption_key_, 32);
        if (rc != SQLITE_OK) {
            std::cerr << "[DB] Key derivation failed: " << sqlite3_errmsg(db) << std::endl;
            sqlite3_close(db);
            return nullptr;
        }
    }
    #endif

    // Performance & safety PRAGMAs
    const char* pragmas =
        "PRAGMA journal_mode = WAL;"
        "PRAGMA synchronous = NORMAL;"
        "PRAGMA temp_store = MEMORY;"
        "PRAGMA foreign_keys = ON;"
        "PRAGMA cache_size = -2000;"   // ~2MB page cache per connection
        "PRAGMA busy_timeout = 5000;";

    char* err_msg = nullptr;
    rc = sqlite3_exec(db, pragmas, nullptr, nullptr, &err_msg);
    if (rc != SQLITE_OK) {
        std::cerr << "[DB] PRAGMA setup failed: " << (err_msg ? err_msg : "unknown") << std::endl;
        sqlite3_free(err_msg);
        sqlite3_close(db);
        return nullptr;
    }

    return db;
}

// --- Lifecycle ---

int DBManager::initialize(const std::string& db_path, const std::string& key_hex) {
    db_file_path_ = db_path;

    if (hex_to_bytes(key_hex, encryption_key_) == 0) {
        has_key_ = true;
    } else {
        std::cerr << "[DB] Invalid hex key format (must be 64 hex chars)" << std::endl;
        return -1;
    }

    // Open writer connection
    writer_db_ = open_connection();
    if (!writer_db_) {
        return -2;
    }

    // Run schema migrations
    if (run_migrations(writer_db_) != 0) {
        sqlite3_close(writer_db_);
        writer_db_ = nullptr;
        return -3;
    }

    // Start writer thread
    writer_running_.store(true);
    writer_thread_ = std::thread(&DBManager::run_writer_loop, this);

    // Pre-open and pre-key read pool connections
    init_read_pool();

    std::cout << "[DB] Initialized. Writer + " << READ_POOL_SIZE << " read connections ready." << std::endl;
    return 0;
}

void DBManager::shutdown() {
    {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        writer_running_.store(false);
    }
    queue_cv_.notify_all();

    if (writer_thread_.joinable()) {
        writer_thread_.join();
    }

    if (writer_db_) {
        sqlite3_close(writer_db_);
        writer_db_ = nullptr;
    }

    drain_read_pool();

    // Clear any remaining queued writes (set broken promise)
    {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        while (!write_queue_.empty()) {
            auto& task = write_queue_.front();
            try {
                task.second.set_exception(
                    std::make_exception_ptr(std::runtime_error("DBManager shutdown"))
                );
            } catch (...) {}
            write_queue_.pop();
        }
    }

    std::cout << "[DB] Shutdown complete." << std::endl;
}

bool DBManager::is_healthy() {
    std::lock_guard<std::mutex> lock(queue_mutex_);
    if (!writer_running_.load() || !writer_db_) return false;

    char* err_msg = nullptr;
    int res = sqlite3_exec(writer_db_, "PRAGMA quick_check(1);", nullptr, nullptr, &err_msg);
    if (err_msg) sqlite3_free(err_msg);
    return res == SQLITE_OK;
}

// --- Writer Thread ---

void DBManager::run_writer_loop() {
    while (true) {
        std::pair<std::function<int(sqlite3*)>, std::promise<int>> task;
        {
            std::unique_lock<std::mutex> lock(queue_mutex_);
            queue_cv_.wait(lock, [this]() {
                return !writer_running_.load() || !write_queue_.empty();
            });

            if (!writer_running_.load() && write_queue_.empty()) break;

            task = std::move(write_queue_.front());
            write_queue_.pop();
        }

        // Execute with exception safety — any throw propagates through the future
        try {
            int res = task.first(writer_db_);
            task.second.set_value(res);
        } catch (...) {
            task.second.set_exception(std::current_exception());
        }
    }
}

std::future<int> DBManager::execute_async_write(std::function<int(sqlite3*)> write_task) {
    std::promise<int> promise;
    std::future<int> future = promise.get_future();

    {
        std::lock_guard<std::mutex> lock(queue_mutex_);
        if (!writer_running_.load()) {
            promise.set_exception(
                std::make_exception_ptr(std::runtime_error("Writer thread not running"))
            );
            return future;
        }
        write_queue_.emplace(std::move(write_task), std::move(promise));
    }
    queue_cv_.notify_one();
    return future;
}

// --- Read Connection Pool ---

void DBManager::init_read_pool() {
    for (size_t i = 0; i < READ_POOL_SIZE; ++i) {
        sqlite3* conn = open_connection();
        if (conn) {
            std::lock_guard<std::mutex> lock(pool_mutex_);
            read_pool_.push_back(conn);
        } else {
            std::cerr << "[DB] Failed to open read pool connection " << i << std::endl;
        }
    }
}

void DBManager::drain_read_pool() {
    std::lock_guard<std::mutex> lock(pool_mutex_);
    for (sqlite3* conn : read_pool_) {
        if (conn) sqlite3_close(conn);
    }
    read_pool_.clear();
}

sqlite3* DBManager::acquire_read_connection() {
    std::unique_lock<std::mutex> lock(pool_mutex_);
    pool_cv_.wait(lock, [this]() {
        return !read_pool_.empty();
    });

    sqlite3* conn = read_pool_.back();
    read_pool_.pop_back();
    return conn;
}

void DBManager::release_read_connection(sqlite3* conn) {
    if (!conn) return;
    std::lock_guard<std::mutex> lock(pool_mutex_);
    read_pool_.push_back(conn);
    pool_cv_.notify_one();
}

// --- ReadGuard RAII ---

DBManager::ReadGuard::ReadGuard(DBManager& mgr) : mgr_(&mgr), conn_(mgr.acquire_read_connection()) {}

DBManager::ReadGuard::~ReadGuard() {
    if (mgr_ && conn_) {
        mgr_->release_read_connection(conn_);
    }
}

DBManager::ReadGuard::ReadGuard(ReadGuard&& other) noexcept
    : mgr_(other.mgr_), conn_(other.conn_) {
    other.mgr_ = nullptr;
    other.conn_ = nullptr;
}

DBManager::ReadGuard& DBManager::ReadGuard::operator=(ReadGuard&& other) noexcept {
    if (this != &other) {
        if (mgr_ && conn_) {
            mgr_->release_read_connection(conn_);
        }
        mgr_ = other.mgr_;
        conn_ = other.conn_;
        other.mgr_ = nullptr;
        other.conn_ = nullptr;
    }
    return *this;
}

// --- Migrations ---

int DBManager::run_migrations(sqlite3* db) {
    const char* migration_sql =
        "CREATE TABLE IF NOT EXISTS system_events ("
        "    event_id TEXT PRIMARY KEY,"
        "    session_id TEXT NOT NULL,"
        "    event_domain TEXT NOT NULL,"
        "    event_type TEXT NOT NULL,"
        "    actor TEXT NOT NULL,"
        "    outcome TEXT DEFAULT 'pending',"
        "    sanitization_state TEXT NOT NULL,"
        "    summary TEXT NOT NULL,"
        "    interaction_payload TEXT,"
        "    created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
        ");"
        "CREATE TABLE IF NOT EXISTS memory_chain ("
        "    chain_id TEXT PRIMARY KEY,"
        "    thread_id TEXT NOT NULL,"
        "    result TEXT,"
        "    coords_from TEXT,"
        "    coords_to TEXT,"
        "    nbl_outcome TEXT,"
        "    insight TEXT,"
        "    file_path TEXT,"
        "    landmark_id TEXT,"
        "    stale INTEGER DEFAULT 0,"
        "    created_at REAL NOT NULL"
        ");"
        "CREATE TABLE IF NOT EXISTS mycelium_landmarks ("
        "    landmark_id TEXT PRIMARY KEY,"
        "    name TEXT NOT NULL,"
        "    description TEXT,"
        "    activation_count INTEGER DEFAULT 0,"
        "    created_at REAL NOT NULL"
        ");";

    char* err_msg = nullptr;
    int rc = sqlite3_exec(db, migration_sql, nullptr, nullptr, &err_msg);
    if (rc != SQLITE_OK) {
        std::cerr << "[DB] Migration failed: " << (err_msg ? err_msg : "unknown") << std::endl;
        sqlite3_free(err_msg);
        return -1;
    }
    return 0;
}
