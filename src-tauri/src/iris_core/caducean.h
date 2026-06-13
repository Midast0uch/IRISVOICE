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

    // --- v2 fields (mitochondria-to-mycelium upgrade) ---
    int l = 1;                // winding number (carrier loop multiplicity)
    int m = 1;                // winding number (local loop multiplicity)
    double c_eff = 1.0;       // effective cycle speed = (1/sqrt(2)) * sqrt(l^2 + m^2)
    double xi_prev1 = 0.0;    // phase one step ago (for phase acceleration)
    double xi_prev2 = 0.0;    // phase two steps ago
};

// ============================================================================
// v2: DirectionSignal — bias-free physics signal exposed to callers.
// Returned by get_direction_signal(). Callers (agent kernel, voice kernel,
// TTS, Mycelium) decide what target_u / force_magnitude MEAN in their domain.
// The physics provides the rhythm; the domain provides the interpretation.
// ============================================================================
struct DirectionSignal {
    double target_u;          // +1.0 (expansion attractor) or -1.0 (compression attractor)
    double force_magnitude;   // |F(u)| = |a*u - b*u^3|
    double u_current;         // current attentional velocity
    double phase;             // current xi in [0, 2pi)
    double balance;           // EML-derived urgency in [0.1, 3.0]
};

class Caducean {
public:
    static Caducean& get_instance();

    Caducean(const Caducean&) = delete;
    Caducean& operator=(const Caducean&) = delete;

    // --- v1 API (unchanged signatures) ---
    int recommend(const std::string& session_id);
    double get_xi(const std::string& session_id);
    void update(const std::string& session_id, int action, double balance);

    // --- v2 API (mitochondria-to-mycelium upgrade) ---
    // Initialize a session with specific winding numbers. Recomputes c_eff.
    // If session already exists, l, m are updated and c_eff is recomputed.
    void init_session(const std::string& session_id, int l, int m);

    // Get the bias-free physics signal for a session.
    // Returns a default DirectionSignal (target_u=+1, balance=1.0) if session not found.
    DirectionSignal get_direction_signal(const std::string& session_id, double balance);

    // Dynamically update the double-well potential constants and walk speed.
    // Bounds: a, b clamped to [1.0, 4.0]; s clamped to [0.1, 0.8].
    void set_params(const std::string& session_id, double a, double b, double s);

    // Get full state snapshot for debugging / health check.
    SessionState get_state(const std::string& session_id);

private:
    Caducean() = default;

    std::unordered_map<std::string, SessionState> states_;
    std::mutex mutex_;
};

#endif // CADUCEAN_H
