// ============================================================================
// IRIS Core Microbenchmark Harness
// Measures real C++ hot-path latency for README performance table.
// Run: build via CMake as `iris_core_bench` target, then execute.
// ============================================================================

#include <iostream>
#include <chrono>
#include <string>
#include <vector>
#include <cstdlib>
#include <cmath>

#include "caducean.h"
#include "security_sanitizer.h"

// FFI functions for full-pipeline benchmarks
#include "iris_core.h"

// --- Benchmark helpers ------------------------------------------------------

template<typename Func>
static double bench_ns(Func&& f, int iterations) {
    // Warm-up
    for (int i = 0; i < 1000; ++i) { f(); }

    auto t0 = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < iterations; ++i) { f(); }
    auto t1 = std::chrono::high_resolution_clock::now();

    double total_ns = std::chrono::duration<double, std::nano>(t1 - t0).count();
    return total_ns / iterations;
}

template<typename Func>
static double bench_ms(Func&& f, int iterations) {
    double ns = bench_ns(std::forward<Func>(f), iterations);
    return ns / 1'000'000.0;
}

// --- 1. Caducean Recompute --------------------------------------------------

static void bench_caducean() {
    auto& gov = Caducean::get_instance();
    const std::string sid = "bench_session";

    // Seed state so recommend() has something to evaluate
    gov.update(sid, 0, 1.0);   // EXPAND
    gov.update(sid, 1, 0.5);   // COMPRESS
    gov.update(sid, 0, 1.0);   // EXPAND

    double ns = bench_ns([&]() {
        volatile int r = gov.recommend(sid);
        (void)r;
    }, 1'000'000);

    std::cout << "Caducean recommend() | " << std::round(ns) << " ns | "
              << std::round(ns / 1000.0) << " us\n";
}

// --- 2. RE2 Sanitize --------------------------------------------------------

static void bench_re2() {
    auto& san = SecuritySanitizer::get_instance();

    // Small payload (~1 KB) — typical event payload
    std::string small_payload = R"({"tool":"browser_click","params":{"url":"https://example.com/api/v1/users"},"api_key":"sk-live-abc123xyz789","result":"ok"})";

    // Medium payload (~10 KB) — larger interaction log
    std::string medium_payload;
    for (int i = 0; i < 200; ++i) {
        medium_payload += "user_password=secret" + std::to_string(i) + "&";
    }
    medium_payload += "aws_access_key_id=AKIAIOSFODNN7EXAMPLE&ssh_key=-----BEGIN OPENSSH PRIVATE KEY-----";

    // Large payload (~100 KB) — stress test
    std::string large_payload;
    large_payload.reserve(100'000);
    for (int i = 0; i < 2000; ++i) {
        large_payload += "token=ghp_" + std::to_string(i) + "xxxxxxxxxxxxxxxxxxxx&";
    }

    auto run = [&](const std::string& name, const std::string& payload, int iters) {
        double ns = bench_ns([&]() {
            auto [scrubbed, modified] = san.sanitize_payload(payload);
            (void)scrubbed;
            (void)modified;
        }, iters);
        double ms = ns / 1'000'000.0;
        double mb_per_sec = (payload.size() / (1024.0 * 1024.0)) / (ns / 1e9);
        std::cout << "RE2 sanitize (" << name << ", " << payload.size() / 1024 << " KB) | "
                  << std::round(ns) << " ns | " << ms << " ms | "
                  << std::round(mb_per_sec * 10) / 10 << " MB/s\n";
    };

    run("small", small_payload, 100'000);
    run("medium", medium_payload, 50'000);
    run("large", large_payload, 10'000);
}

// --- 3. Event Ingestion (full pipeline) -------------------------------------

static void bench_ingest() {
    const char* db_path = "bench_iris.db";
    const char* key = "0000000000000000000000000000000000000000000000000000000000000000";

    // Remove old bench DB
    std::remove(db_path);

    int rc = init_core_engine(db_path, key);
    if (rc != 0) {
        std::cout << "Event Ingestion | SKIPPED (init failed, rc=" << rc << ")\n";
        std::remove(db_path);
        return;
    }

    const char* sid = "bench";
    const char* domain = "CODE";
    const char* event_type = "file_edit";
    const char* actor = "agent_kernel";
    const char* outcome = "success";
    const char* summary = "Benchmark event";
    const char* payload = "{\"file\":\"test.py\",\"lines\":42}";

    // Warm-up
    for (int i = 0; i < 100; ++i) {
        ingest_event(sid, domain, event_type, actor, outcome, summary, payload);
    }

    double ms = bench_ms([&]() {
        ingest_event(sid, domain, event_type, actor, outcome, summary, payload);
    }, 10'000);

    shutdown_core_engine();
    std::remove(db_path);

    std::cout << "Event ingestion (full pipeline) | " << ms << " ms\n";
}

// --- 4. EML Calculation (full pipeline) -------------------------------------

static void bench_eml() {
    const char* db_path = "bench_iris_eml.db";
    const char* key = "0000000000000000000000000000000000000000000000000000000000000000";

    std::remove(db_path);

    int rc = init_core_engine(db_path, key);
    if (rc != 0) {
        std::cout << "EML calculation | SKIPPED (init failed, rc=" << rc << ")\n";
        std::remove(db_path);
        return;
    }

    // Seed some events so EML has data to query
    const char* sid = "bench";
    for (int i = 0; i < 50; ++i) {
        std::string payload = "{\"iteration\":" + std::to_string(i) + "}";
        ingest_event(sid, "CODE", "test_run", "agent_kernel", "success", "seed", payload.c_str());
    }

    // Wait for async writes to drain
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    double x = 0, y = 0;

    // Warm-up
    for (int i = 0; i < 100; ++i) {
        volatile double eml = calculate_eml(sid, &x, &y);
        (void)eml;
    }

    double ms = bench_ms([&]() {
        volatile double eml = calculate_eml(sid, &x, &y);
        (void)eml;
    }, 10'000);

    shutdown_core_engine();
    std::remove(db_path);

    std::cout << "EML calculation (full pipeline) | " << ms << " ms\n";
}

// --- 5. Memory Overhead (RSS estimate) --------------------------------------

#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#pragma comment(lib, "psapi.lib")

static SIZE_T get_working_set() {
    PROCESS_MEMORY_COUNTERS pmc = {};
    if (GetProcessMemoryInfo(GetCurrentProcess(), &pmc, sizeof(pmc))) {
        return pmc.WorkingSetSize;
    }
    return 0;
}
#else
static size_t get_working_set() { return 0; }
#endif

static void bench_memory() {
    SIZE_T baseline = get_working_set();

    // Force singletons to instantiate
    auto& c = Caducean::get_instance();
    auto& s = SecuritySanitizer::get_instance();
    (void)c;
    (void)s;

    SIZE_T after_singletons = get_working_set();
    double delta_mb = (after_singletons - baseline) / (1024.0 * 1024.0);

    std::cout << "Memory overhead (singletons) | " << std::round(delta_mb * 100) / 100 << " MB RSS\n";
}

// --- Main -------------------------------------------------------------------

int main() {
    std::cout << "========================================\n";
    std::cout << "  IRIS Core Microbenchmark Results\n";
    std::cout << "========================================\n\n";

    bench_caducean();
    bench_re2();
    bench_ingest();
    bench_eml();
    bench_memory();

    std::cout << "\n========================================\n";
    return 0;
}
