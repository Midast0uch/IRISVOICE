#include "caducean.h"
#include <cmath>
#include <algorithm>

#ifndef M_PI
    #define M_PI 3.14159265358979323846
#endif

// ============================================================================
// Caducean Attention Governor — Full Vector Dynamics
// Per implementation_plan.md Section 4.1
//
//   State vector per session:  x, y, xi, u, a=2.0, b=2.0, s=0.35
//
//   F(u) = a*u - b*u^3
//
//   recommend():
//     1. Stable orbit: |u|<0.2  &&  |xi|<pi/4  → EXPAND if s>0 else COMPRESS
//     2. Compression valley: F(u) >  0.05        → COMPRESS (1)
//     3. Expansion ridge:  F(u) < -0.05        → EXPAND   (0)
//     4. Neutral valley:   |F(u)| <= 0.05      → CONTINUE (2)
//
//   update(action, balance):
//     action 0 (EXPAND):   x++,  u += s*cos(xi)
//     action 1 (COMPRESS): y++,  u -= s*sin(xi)
//     action 2 (CONTINUE): no x/y/u change
//     xi = fmod(xi + balance*s, 2*pi)
// ============================================================================

Caducean& Caducean::get_instance() {
    static Caducean instance;
    return instance;
}

int Caducean::recommend(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = states_.find(session_id);
    if (it == states_.end()) {
        return 2; // CONTINUE (neutral balanced)
    }

    const auto& state = it->second;

    // 1. Stable equilibrium orbit check
    if (std::abs(state.u) < 0.2 && std::abs(state.xi) < M_PI / 4.0) {
        return (state.s > 0) ? 0 : 1; // EXPAND (0) or COMPRESS (1)
    }

    // 2. Physics-evolved potential landscape force F(u)
    double f = state.a * state.u - state.b * std::pow(state.u, 3.0);
    if (f > 0.05)  return 1;  // Force pulls to COMPRESS
    if (f < -0.05) return 0;  // Force pulls to EXPAND

    return 2; // Neutral state: CONTINUE
}

double Caducean::get_xi(const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = states_.find(session_id);
    return (it != states_.end()) ? it->second.xi : 0.0;
}

void Caducean::update(const std::string& session_id, int action, double balance) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto& state = states_[session_id];

    // 0 = EXPAND, 1 = COMPRESS, 2 = CONTINUE (CONTINUE does not modify x, y, or u)
    if (action == 0) {
        state.x++;
        state.u += state.s * std::cos(state.xi);
    } else if (action == 1) {
        state.y++;
        state.u -= state.s * std::sin(state.xi);
    }

    // Clamp u to the [-1, 1] attention bias range
    state.u = std::clamp(state.u, -1.0, 1.0);

    // Angular attention phase update. balance acts as optional correction factor.
    state.xi = std::fmod(state.xi + balance * state.s, 2.0 * M_PI);
    if (state.xi < 0.0) {
        state.xi += 2.0 * M_PI;
    }
}
