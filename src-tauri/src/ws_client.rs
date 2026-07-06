// ws_client.rs — WebSocket client running in the Tauri Rust process.
//
// Maintains a persistent WebSocket connection to the Python backend,
// independent of the WebView lifecycle.  Handles reconnection with
// exponential backoff.  Messages are forwarded between the frontend
// (via Tauri events/commands) and the backend (via WebSocket).
//
// Architecture:
//   frontend  ←→  Tauri IPC  ←→  ws_client::WsClient  ←→  Python backend
//               (invoke/emit)       (tokio-tungstenite)     (ws://localhost:8000/ws)
//
// This module does NOT own the Tauri state.  State is managed in
// commands/ws.rs via Arc<tokio::sync::Mutex<WsClient>>.

use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tauri::Emitter;
use tokio::sync::Mutex;
use tokio_tungstenite::connect_async;

// ── Constants ──────────────────────────────────────────────────────────────

const INITIAL_BACKOFF_SECS: u64 = 1;
const MAX_BACKOFF_SECS: u64 = 15;
const STABILITY_RESET_SECS: u64 = 30;

// ── State ──────────────────────────────────────────────────────────────────

pub struct WsClient {
    /// Sender half of the outgoing message channel.
    /// None = disconnected.  Set to Some(tx) on connect, None on disconnect.
    pub sender: Option<tokio::sync::mpsc::UnboundedSender<String>>,
}

impl WsClient {
    pub fn new() -> Self {
        Self { sender: None }
    }
}

// ── Public API ─────────────────────────────────────────────────────────────

/// Start the WebSocket client in a background Tokio task.
///
/// Call this once from the frontend (via `invoke('start_ws_client', { url })`).
/// The task runs until `ws_disconnect` is called or the app exits.
pub fn start(
    url: String,
    app_handle: tauri::AppHandle,
    state: Arc<Mutex<WsClient>>,
) {
    tokio::spawn(async move {
        run_ws_loop(url, app_handle, state).await;
    });
}

// ── Internal ───────────────────────────────────────────────────────────────

async fn run_ws_loop(
    url: String,
    app_handle: tauri::AppHandle,
    state: Arc<Mutex<WsClient>>,
) {
    let mut backoff = INITIAL_BACKOFF_SECS;
    let mut stable_since: Option<std::time::Instant> = None;

    loop {
        match connect_async(&url).await {
            Ok((ws_stream, _)) => {
                let (mut write, mut read) = ws_stream.split();
                let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<String>();

                // Publish sender so ws_send commands can push messages
                {
                    let mut state_lock = state.lock().await;
                    state_lock.sender = Some(tx);
                }

                // Notify frontend
                let _ = app_handle.emit("ws:connected", ());
                eprintln!("[WS Client] Connected to {}", url);

                // Reset backoff on successful connection
                backoff = INITIAL_BACKOFF_SECS;
                stable_since = Some(std::time::Instant::now());

                // Message pump loop
                let result: Result<(), &str> = loop {
                    tokio::select! {
                        // Outgoing: frontend → backend
                        msg = rx.recv() => {
                            match msg {
                                Some(text) => {
                                    if write
                                        .send(tungstenite::Message::Text(text.into()))
                                        .await
                                        .is_err()
                                    {
                                        break Err("write failed");
                                    }
                                }
                                None => break Err("channel closed"),
                            }
                        }
                        // Incoming: backend → frontend
                        msg = read.next() => {
                            match msg {
                                Some(Ok(tungstenite::Message::Text(text))) => {
                                    let _ = app_handle.emit("ws:message", text.to_string());
                                }
                                Some(Ok(tungstenite::Message::Close(_))) => {
                                    break Err("server closed connection");
                                }
                                Some(Ok(tungstenite::Message::Ping(data))) => {
                                    // Auto-pong handled by tungstenite — but
                                    // send a pong explicitly to be safe
                                    let _ = write
                                        .send(tungstenite::Message::Pong(data))
                                        .await;
                                }
                                Some(Ok(_)) => {
                                    // Binary, Pong — ignore
                                }
                                Some(Err(e)) => {
                                    break Err("ws error");
                                }
                                None => break Err("stream ended"),
                            }
                        }
                    }

                    // Reset backoff to 1s after 30s of stable connection
                    if let Some(start) = stable_since {
                        if start.elapsed().as_secs() >= STABILITY_RESET_SECS {
                            backoff = INITIAL_BACKOFF_SECS;
                            stable_since = None; // don't keep checking
                        }
                    }
                };

                // Clean up state on disconnect
                {
                    let mut state_lock = state.lock().await;
                    state_lock.sender = None;
                }

                let _ = app_handle.emit("ws:disconnected", ());
                eprintln!(
                    "[WS Client] Disconnected from {} ({:?})",
                    url, result
                );
            }
            Err(e) => {
                eprintln!("[WS Client] Connection failed: {} — retrying in {}s", e, backoff);
            }
        }

        // Exponential backoff with cap
        tokio::time::sleep(tokio::time::Duration::from_secs(backoff)).await;
        backoff = std::cmp::min(backoff * 2, MAX_BACKOFF_SECS);
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_ws_client_initial_state() {
        let client = WsClient::new();
        assert!(client.sender.is_none());
    }

    #[tokio::test]
    async fn test_backoff_increases_then_caps() {
        let mut backoff = INITIAL_BACKOFF_SECS;
        let expected: Vec<u64> = vec![1, 2, 4, 8, 15, 15, 15];
        for &exp in &expected {
            assert_eq!(backoff, exp);
            backoff = std::cmp::min(backoff * 2, MAX_BACKOFF_SECS);
        }
    }

    #[test]
    fn test_constants_are_sane() {
        assert!(INITIAL_BACKOFF_SECS >= 1);
        assert!(MAX_BACKOFF_SECS >= INITIAL_BACKOFF_SECS);
        assert!(STABILITY_RESET_SECS >= INITIAL_BACKOFF_SECS);
    }
}
