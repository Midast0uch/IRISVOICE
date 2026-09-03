// caducean.rs — Tauri commands for Caducean v2 (Phase 5)
//
// These commands are thin HTTP proxies to the Python FastAPI endpoints
// at /api/caducean/*. They are registered in main.rs via generate_handler!.
//
// Architecture: Python owns the C++ DLL, Tauri is a thin shell. The
// frontend calls invoke("caducean_get_state", { sessionId }) which
// triggers this Rust function, which makes an HTTP GET to the local
// Python backend, which calls into the FFI, which calls into C++.
//
// Why this layer exists:
//   - Tauri commands are the only IPC the frontend can use (no direct
//     HTTP from WebView to localhost in production builds — CORS / CSP).
//   - The Rust layer is intentionally dumb — no state, no caching,
//     just pure proxying. All state lives in Python (and C++).
//
// Frozen contract: see backend/tests/contracts/caducean_api_v2.json.

use serde::{Deserialize, Serialize};

const PYTHON_BACKEND_URL: &str = "http://localhost:8000";

// ── Response shapes (match the FastAPI endpoints exactly) ──────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaduceanStateResponse {
    pub session_id: String,
    pub engine_live: bool,
    pub x: i64,
    pub y: i64,
    pub xi: f64,
    pub u: f64,
    pub a: f64,
    pub b: f64,
    pub s: f64,
    pub c_eff: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DirectionSignalResponse {
    pub session_id: String,
    pub target_u: f64,
    pub force_magnitude: f64,
    pub u_current: f64,
    pub phase: f64,
    pub balance: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SetParamsRequest {
    pub session_id: String,
    pub a: f64,
    pub b: f64,
    pub s: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SetParamsResponse {
    pub ok: bool,
    pub session_id: String,
    pub applied: Option<SetParamsApplied>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SetParamsApplied {
    pub a: f64,
    pub b: f64,
    pub s: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaduceanHealthResponse {
    pub engine_live: bool,
    pub engine_initialized_at: Option<String>,
}

// ── Tauri commands (called from frontend via invoke()) ─────────────

/// Returns full Caducean state for a session.
#[tauri::command]
pub async fn caducean_get_state(session_id: String) -> Result<CaduceanStateResponse, String> {
    let url = format!("{}/api/caducean/state?session_id={}", PYTHON_BACKEND_URL, session_id);
    let resp = reqwest::get(&url).await.map_err(|e| format!("HTTP error: {}", e))?;
    let body: CaduceanStateResponse = resp
        .json()
        .await
        .map_err(|e| format!("JSON parse error: {}", e))?;
    Ok(body)
}

/// Returns the bias-free DirectionSignal for a session.
#[tauri::command]
pub async fn caducean_get_direction_signal(
    session_id: String,
    balance: Option<f64>,
) -> Result<DirectionSignalResponse, String> {
    let bal = balance.unwrap_or(1.0).clamp(0.1, 3.0);
    let url = format!(
        "{}/api/caducean/direction?session_id={}&balance={}",
        PYTHON_BACKEND_URL, session_id, bal
    );
    let resp = reqwest::get(&url).await.map_err(|e| format!("HTTP error: {}", e))?;
    let body: DirectionSignalResponse = resp
        .json()
        .await
        .map_err(|e| format!("JSON parse error: {}", e))?;
    Ok(body)
}

/// Update Duffing potential constants and walk speed.
#[tauri::command]
pub async fn caducean_set_params(
    session_id: String,
    a: f64,
    b: f64,
    s: f64,
) -> Result<SetParamsResponse, String> {
    let url = format!("{}/api/caducean/params", PYTHON_BACKEND_URL);
    let client = reqwest::Client::new();
    let body = SetParamsRequest { session_id, a, b, s };
    let resp = client
        .post(&url)
        .json(&body)
        .send()
        .await
        .map_err(|e| format!("HTTP error: {}", e))?;
    let result: SetParamsResponse = resp
        .json()
        .await
        .map_err(|e| format!("JSON parse error: {}", e))?;
    Ok(result)
}

/// Health check — returns engine_live bool.
#[tauri::command]
pub async fn caducean_health() -> Result<CaduceanHealthResponse, String> {
    let url = format!("{}/api/caducean/health", PYTHON_BACKEND_URL);
    let resp = reqwest::get(&url).await.map_err(|e| format!("HTTP error: {}", e))?;
    let body: CaduceanHealthResponse = resp
        .json()
        .await
        .map_err(|e| format!("JSON parse error: {}", e))?;
    Ok(body)
}
