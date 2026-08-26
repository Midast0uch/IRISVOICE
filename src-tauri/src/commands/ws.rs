// commands/ws.rs — Tauri commands for the Rust-side WebSocket client.
//
// These commands let the frontend start, send to, disconnect, and query
// the WebSocket client running in the Rust process (ws_client.rs).
//
// Usage (frontend):
//   invoke('start_ws_client', { url: 'ws://localhost:8000/ws' })
//   invoke('ws_send', { message: JSON.stringify({ type, payload }) })
//   invoke('ws_disconnect')
//   const state = invoke('get_ws_connection_state')
//
// The frontend listens for Tauri events:
//   listen('ws:connected', handler)
//   listen('ws:disconnected', handler)
//   listen('ws:message', handler)

use std::sync::Arc;
use tauri::State;
use tokio::sync::Mutex;

use crate::ws_client::WsClient;

/// Start the Rust-side WebSocket client.
///
/// Spawns a Tokio task that maintains the connection to `url`.
/// The task runs until `ws_disconnect` is called or the app exits.
#[tauri::command]
pub async fn start_ws_client(
    app_handle: tauri::AppHandle,
    ws_state: State<'_, Arc<Mutex<WsClient>>>,
    url: String,
) -> Result<(), String> {
    crate::ws_client::start(url, app_handle, ws_state.inner().clone()).await;
    Ok(())
}

/// Send a message through the Rust-side WebSocket connection.
///
/// Returns true if the message was queued for delivery, false if the
/// WebSocket is disconnected.  Never blocks — the actual send happens
/// asynchronously in the background Tokio task.
#[tauri::command]
pub async fn ws_send(
    ws_state: State<'_, Arc<Mutex<WsClient>>>,
    message: String,
) -> Result<bool, String> {
    let state = ws_state.lock().await;
    match &state.sender {
        Some(sender) => sender
            .send(message)
            .map(|_| true)
            .map_err(|e| format!("Failed to queue message: {}", e)),
        None => Ok(false),
    }
}

/// Cleanly close the WebSocket connection and drop the Tokio task.
#[tauri::command]
pub async fn ws_disconnect(
    ws_state: State<'_, Arc<Mutex<WsClient>>>,
) -> Result<(), String> {
    let mut state = ws_state.lock().await;
    state.stop = true;      // tell the running loop to exit, not reconnect
    state.sender = None;    // Dropping the sender causes the pump loop to exit
    Ok(())
}

/// Get the current connection state.
///
/// Returns "connected" if the WebSocket is open, "disconnected" otherwise.
#[tauri::command]
pub async fn get_ws_connection_state(
    ws_state: State<'_, Arc<Mutex<WsClient>>>,
) -> Result<String, String> {
    let state = ws_state.lock().await;
    Ok(if state.sender.is_some() {
        "connected".into()
    } else {
        "disconnected".into()
    })
}
