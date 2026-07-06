// commands/mod.rs — Tauri command modules
//
// v2 (Phase 5): Caducean commands proxy to Python FastAPI endpoints.
// See caducean.rs for the thin HTTP layer.
//
// WS: Rust-side WebSocket client commands.
// See ws.rs for the WS client control commands.

pub mod caducean;
pub mod ws;
