#ifndef CADUCEAN_H
#define CADUCEAN_H

#include <string>
#include <unordered_map>
#include <mutex>

// ============================================================================
// Caducean Attention Governor — Phase 3 Implementation
// Full vector dynamics per implementation_plan.md Section 4.1
//   State:  x, y, xi, u, a=2.0, b=2.0, s=0.35
//   F(u)   = a*u - b*u^3
//   update = vector rotation driven by action + balance phase correction
// ============================================================================

struct SessionState {
    int x = 0;                // cumulative EXPAND count
    int y = 0;                // cumulative COMPRESS count
    double xi = 0.0;          // angular attention phase [0, 2pi)
    double u = 0.0;           // velocity offset [-1, 1]
    double a = 2.0;           // landscape potential constant a
    double b = 2.0;           // landscape potential constant b
    double s = 0.35;          // walk speed coefficient
};

class Caducean {
public:
    static Caducean& get_instance();

    Caducean(const Caducean&) = delete;
    Caducean& operator=(const Caducean&) = delete;

    int recommend(const std::string& session_id);
    double get_xi(const std::string& session_id);
    void update(const std::string& session_id, int action, double balance);

private:
    Caducean() = default;

    std::unordered_map<std::string, SessionState> states_;
    std::mutex mutex_;
};

#endif // CADUCEAN_H
