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
use tokio_tungstenite::tungstenite::Message as WsMessage;

// ── Constants ──────────────────────────────────────────────────────────────

const INITIAL_BACKOFF_SECS: u64 = 1;
const MAX_BACKOFF_SECS: u64 = 15;
const STABILITY_RESET_SECS: u64 = 30;

// ── State ──────────────────────────────────────────────────────────────────

pub struct WsClient {
    /// Sender half of the outgoing message channel.
    /// None = disconnected.  Set to Some(tx) on connect, None on disconnect.
    pub sender: Option<tokio::sync::mpsc::UnboundedSender<String>>,
    /// True while the run_ws_loop task is alive.  Guards against duplicate
    /// start_ws_client invokes: the frontend mounts several useIRISWebSocket
    /// instances, each calling start_ws_client on mount.  Without this guard
    /// they each spawn their own loop and all fight for the single backend
    /// `client="iris"` slot, evicting each other in a reconnect storm that
    /// cancelled every in-flight chat thread.
    pub running: bool,
    /// Set by ws_disconnect so the running loop exits instead of reconnecting.
    pub stop: bool,
}

impl WsClient {
    pub fn new() -> Self {
        Self { sender: None, running: false, stop: false }
    }
}

// ── Public API ─────────────────────────────────────────────────────────────

/// Start the WebSocket client in a background Tokio task.
///
/// Call this from the frontend (via `invoke('start_ws_client', { url })`).
/// The task runs until `ws_disconnect` is called or the app exits.
///
/// Idempotent: only one run_ws_loop may exist at a time.  The frontend
/// instantiates useIRISWebSocket in several components, each calling
/// start_ws_client on mount, so without this guard multiple loops would
/// spawn and evict each other on the backend's single `client="iris"` slot.
pub async fn start(
    url: String,
    app_handle: tauri::AppHandle,
    state: Arc<Mutex<WsClient>>,
) {
    {
        let mut state_lock = state.lock().await;
        if state_lock.running {
            eprintln!("[WS Client] start_ws_client ignored — loop already running");
            return;
        }
        state_lock.running = true;
        state_lock.stop = false;
    }
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
        // Exit if a stop was requested (ws_disconnect) so a later
        // start_ws_client can spawn a fresh loop (e.g. after an HMR remount).
        {
            let state_lock = state.lock().await;
            if state_lock.stop {
                break;
            }
        }
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

                // Message pump loop — breaks on any error/disconnect
                loop {
                    tokio::select! {
                        // Outgoing: frontend → backend
                        msg = rx.recv() => {
                            let text = match msg {
                                Some(t) => t,
                                None => break,
                            };
                            if write
                                .send(WsMessage::Text(text.into()))
                                .await
                                .is_err()
                            {
                                break;
                            }
                        }
                        // Incoming: backend → frontend
                        msg = read.next() => {
                            match msg {
                                Some(Ok(WsMessage::Text(text))) => {
                                    let _ = app_handle.emit("ws:message", text.to_string());
                                }
                                Some(Ok(WsMessage::Close(_))) => break,
                                Some(Ok(WsMessage::Ping(data))) => {
                                    let _ = write
                                        .send(WsMessage::Pong(data))
                                        .await;
                                }
                                Some(Ok(_)) => {
                                    // Binary, Pong — ignore
                                }
                                Some(Err(_)) => break,
                                None => break,
                            }
                        }
                    }

                    // Reset backoff to 1s after 30s of stable connection
                    if let Some(start) = stable_since {
                        if start.elapsed().as_secs() >= STABILITY_RESET_SECS {
                            backoff = INITIAL_BACKOFF_SECS;
                            stable_since = None;
                        }
                    }
                }

                // Clean up state on disconnect
                {
                    let mut state_lock = state.lock().await;
                    state_lock.sender = None;
                }

                let _ = app_handle.emit("ws:disconnected", ());
                eprintln!("[WS Client] Disconnected from {}", url);
            }
            Err(e) => {
                eprintln!("[WS Client] Connection failed: {} — retrying in {}s", e, backoff);
            }
        }

        // Stop requested? Exit instead of sleeping/reconnecting.
        {
            let state_lock = state.lock().await;
            if state_lock.stop {
                break;
            }
        }

        // Exponential backoff with cap
        tokio::time::sleep(tokio::time::Duration::from_secs(backoff)).await;
        backoff = std::cmp::min(backoff * 2, MAX_BACKOFF_SECS);
    }

    // Loop exited (stop requested): clear flags so start_ws_client may spawn
    // again.  Done under the lock so a concurrent start() sees running=false.
    {
        let mut state_lock = state.lock().await;
        state_lock.running = false;
        state_lock.stop = false;
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

    #[test]
    fn test_backoff_resets_after_stable_connection() {
        let mut backoff = 8u64;
        let mut stable_seconds: u64 = 15;
        assert!(stable_seconds < STABILITY_RESET_SECS);
        stable_seconds = 30;
        if stable_seconds >= STABILITY_RESET_SECS {
            backoff = INITIAL_BACKOFF_SECS;
        }
        assert_eq!(backoff, 1);
    }

    #[tokio::test]
    async fn test_mpsc_channel_buffers_messages() {
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<String>();
        tx.send("hello".to_string()).unwrap();
        tx.send("world".to_string()).unwrap();
        assert_eq!(rx.recv().await.unwrap(), "hello");
        assert_eq!(rx.recv().await.unwrap(), "world");
        assert!(rx.try_recv().is_err());
    }

    #[tokio::test]
    async fn test_mpsc_channel_dropped_sender_closes() {
        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<String>();
        tx.send("test".to_string()).unwrap();
        drop(tx);
        assert_eq!(rx.recv().await.unwrap(), "test");
        assert!(rx.recv().await.is_none());
    }
}
