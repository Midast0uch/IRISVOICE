#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;
pub mod ws_client;

use std::sync::{Arc, Mutex};
use tauri::{Emitter, Listener, Manager, PhysicalSize, RunEvent};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

fn main() {
    // Shared handle so the exit handler can kill the sidecar
    let sidecar_child: Arc<Mutex<Option<CommandChild>>> = Arc::new(Mutex::new(None));
    let sidecar_child_exit = sidecar_child.clone();

    let app = tauri::Builder::default()
        .manage(Arc::new(tokio::sync::Mutex::new(ws_client::WsClient::new())))
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_deep_link::init())
        // v2: register Caducean commands (thin HTTP proxies to Python FastAPI)
        // v3 (Phase 1): register WS client commands (Rust-side WebSocket)
        .invoke_handler(tauri::generate_handler![
            commands::caducean::caducean_get_state,
            commands::caducean::caducean_get_direction_signal,
            commands::caducean::caducean_set_params,
            commands::caducean::caducean_health,
            commands::ws::start_ws_client,
            commands::ws::ws_send,
            commands::ws::ws_disconnect,
            commands::ws::get_ws_connection_state,
            commands::launcher::launch_launcher,
        ])
        .setup(move |app| {
            let window = app.get_webview_window("main").unwrap();

            window.set_decorations(false).ok();
            window.set_shadow(false).ok();
            window.set_always_on_top(true).ok();
            window.set_skip_taskbar(true).ok();

            // Must be resizable=true so the JS API can expand/contract the window
            // when chat/dashboard wings open.  The user cannot drag-resize because
            // there are no window decorations, so this doesn't expose a resize handle.
            window.set_resizable(true).ok();

            let min_size = PhysicalSize::new(680u32, 680u32);
            window.set_min_size(Some(min_size)).ok();
            // No max size — the window expands dynamically when chat/dashboard wings open
            window.set_max_size(None::<PhysicalSize<u32>>).ok();

            // ── Launch the Python backend sidecar ─────────────────────────
            // Only runs in release builds (production installs).
            // In dev mode (`cargo tauri dev`) the backend is started separately
            // via start-backend.py — spawning the sidecar here would race with
            // that process for port 8000 and cause startup errors/memory spikes.
            #[cfg(not(debug_assertions))]
            match app.shell().sidecar("iris-backend") {
                Ok(cmd) => {
                    let res: Result<
                        (
                            tauri::async_runtime::Receiver<
                                tauri_plugin_shell::process::CommandEvent,
                            >,
                            tauri_plugin_shell::process::CommandChild,
                        ),
                        tauri_plugin_shell::Error,
                    > = cmd.spawn();
                    match res {
                        Ok((_rx, child)) => {
                            let pid: u32 = child.pid();
                            println!("[Tauri] Backend sidecar started (pid={})", pid);
                            *sidecar_child.lock().unwrap() = Some(child);
                        }
                        Err(e) => {
                            println!("[Tauri] Sidecar spawn failed ({})", e);
                        }
                    }
                }
                Err(e) => {
                    println!("[Tauri] Sidecar not found — assuming external backend ({})", e);
                }
            }
            #[cfg(debug_assertions)]
            println!("[Tauri] Dev mode — backend sidecar skipped (use start-backend.py)");

            // ── Deep link handler ─────────────────────────────────────────
            let app_handle = app.handle().clone();
            app.listen("deep-link", move |event| {
                if let Ok(payload) = serde_json::from_str::<Vec<String>>(&event.payload()) {
                    if let Some(url) = payload.first() {
                        println!("Deep link received: {}", url);
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let _ = window.emit("deep-link", url);
                        }
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(move |app_handle, event| {
        match event {
            RunEvent::ExitRequested { api, .. } => {
                println!("[Tauri] Exit requested - triggering cleanup");

                // Notify frontend
                if let Some(window) = app_handle.get_webview_window("main") {
                    window.emit("app-cleanup", ()).ok();
                }

                // Kill the backend sidecar so it doesn't linger after the UI closes
                if let Ok(mut guard) = sidecar_child_exit.lock() {
                    if let Some(child) = guard.take() {
                        let pid: u32 = child.pid();
                        println!("[Tauri] Stopping backend sidecar (pid={})", pid);
                        child.kill().ok();
                    }
                }

                api.prevent_exit();
            }
            RunEvent::Exit => {
                println!("[Tauri] Application exiting - cleanup complete");
            }
            _ => {}
        }
    });
}
