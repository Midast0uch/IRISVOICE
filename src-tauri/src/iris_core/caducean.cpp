#include "caducean.h"
#include <algorithm>
#include <cmath>
#include <mutex>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

// Adaptive safety net thresholds (v2 — mitochondria-to-mycelium upgrade).
// Phase-acceleration threshold: stable limit cycles have d^2 xi/dt^2 ≈ 0.
// Values above this indicate genuine topological drift, not stable orbit.
static constexpr double PHASE_ACCEL_THRESHOLD = 0.05;
// Topological charge threshold: |Q| = |x-y|/(x+y+1) above this is a "lone kink"
static constexpr double TOPO_CHARGE_THRESHOLD = 0.8;

static double clamp(double v, double lo, double hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

static double compute_c_eff(int l, int m) {
    return (1.0 / std::sqrt(2.0)) * std::sqrt(double(l) * l + double(m) * m);
}

Caducean& Caducean::get_instance() {
    static Caducean instance;
    return instance;
}

int Caducean::recommend(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = states_.find(session_id);
    if (it == states_.end()) {
        return 2; // CONTINUE
    }
    const auto& state = it->second;

    // --- v2: Adaptive safety net (FIRST check — short-circuits on violation) ---
    // Detects genuine topological drift vs stable limit cycles via phase
    // acceleration. d^2 xi/dt^2 ≈ 0 on a stable orbit; nonzero on drift.
    const double total = double(state.x) + double(state.y) + 1.0;
    const double Q = std::abs(double(state.x) - double(state.y)) / total;
    if (Q > TOPO_CHARGE_THRESHOLD) {
        const double diff1 = std::remainder(state.xi - state.xi_prev1, 2.0 * M_PI);
        const double diff2 = std::remainder(state.xi_prev1 - state.xi_prev2, 2.0 * M_PI);
        const double phase_accel = std::abs(diff1 - diff2);
        if (phase_accel > PHASE_ACCEL_THRESHOLD) {
            return 3; // TOPO_VIOLATION — stop-the-line event
        }
    }

    // Stable-orbit: near xi=0 with low |u| -> recommend based on sign of s
    if (std::abs(state.u) < 0.2 && state.xi < M_PI / 4.0) {
        return state.s >= 0.0 ? 0 : 1; // EXPAND or COMPRESS
    }
    double F = state.a * state.u - state.b * std::pow(state.u, 3);
    if (F > 0.05) return 1;  // COMPRESS
    if (F < -0.05) return 0; // EXPAND
    return 2;                 // CONTINUE
}

double Caducean::get_xi(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = states_.find(session_id);
    if (it == states_.end()) {
        return 0.0;
    }
    return it->second.xi;
}

void Caducean::update(const std::string& session_id, int action, double balance) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto& state = states_[session_id];
    // Clamp balance to safe range [0.1, 3.0]
    balance = clamp(balance, 0.1, 3.0);
    // --- v2: Shift phase history BEFORE updating current phase ---
    state.xi_prev2 = state.xi_prev1;
    state.xi_prev1 = state.xi;
    // Advance accumulators
    if (action == 0) { // EXPAND
        state.x += 1;
        state.u += state.s * std::cos(state.xi);
    } else { // COMPRESS (or any non-zero action)
        state.y += 1;
        state.u -= state.s * std::sin(state.xi);
    }
    // Clamp u to Lyapunov bound [-1, 1]
    state.u = clamp(state.u, -1.0, 1.0);
    // --- v2: Advance phase using c_eff (effective cycle speed from winding) ---
    state.xi = std::fmod(state.xi + balance * state.s * state.c_eff, 2.0 * M_PI);
    if (state.xi < 0.0) state.xi += 2.0 * M_PI;
}

// --- v2 API: mitochondria-to-mycelium upgrade ---

void Caducean::init_session(const std::string& session_id, int l, int m) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto& state = states_[session_id];
    state.l = l;
    state.m = m;
    state.c_eff = compute_c_eff(l, m);
}

DirectionSignal Caducean::get_direction_signal(const std::string& session_id, double balance) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = states_.find(session_id);
    // Default: optimistic (target_u=+1, balance=1.0) for unknown sessions
    if (it == states_.end()) {
        DirectionSignal sig{};
        sig.target_u = 1.0;
        sig.force_magnitude = 0.0;
        sig.u_current = 0.0;
        sig.phase = 0.0;
        sig.balance = clamp(balance, 0.1, 3.0);
        return sig;
    }
    const auto& state = it->second;
    // F(u) = a*u - b*u^3
    const double F = state.a * state.u - state.b * std::pow(state.u, 3);
    DirectionSignal sig{};
    sig.target_u = (state.u >= 0.0) ? 1.0 : -1.0;
    sig.force_magnitude = std::abs(F);
    sig.u_current = state.u;
    sig.phase = state.xi;
    sig.balance = clamp(balance, 0.1, 3.0);
    return sig;
}

void Caducean::set_params(const std::string& session_id, double a, double b, double s) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto& state = states_[session_id];
    // Bounds chosen for Duffing stability: a, b in [1, 4]; s in [0.1, 0.8]
    state.a = clamp(a, 1.0, 4.0);
    state.b = clamp(b, 1.0, 4.0);
    state.s = clamp(s, 0.1, 0.8);
}

SessionState Caducean::get_state(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = states_.find(session_id);
    if (it == states_.end()) {
        return SessionState{}; // default-initialized state
    }
    return it->second;
}
