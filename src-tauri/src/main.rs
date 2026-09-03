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
            commands::launcher::launch_widget,
            commands::wings::detach_wing,
            commands::wings::reattach_wing,
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

            // 420 is the idle frame in lib/orbWingGeometry — the orb alone,
            // with room for its labels, the voice haze and the level-2 radial
            // menu. It was 680, which silently floored every attempt the
            // frontend made to shrink the window at idle; a transparent window
            // cannot be clicked through, so those extra pixels blocked the
            // desktop underneath for nothing.
            let min_size = PhysicalSize::new(420u32, 420u32);
            window.set_min_size(Some(min_size)).ok();
            // No max size — the window expands dynamically when chat/dashboard wings open
            window.set_max_size(None::<PhysicalSize<u32>>).ok();

            // ── The launcher window ───────────────────────────────────────
            // The launcher used to be a SEPARATE Tauri application in the
            // iris-launcher submodule. It is now a second window of this one,
            // so showing it costs a show() instead of a cargo build plus a
            // dev-server boot.
            //
            // ── The launcher window ───────────────────────────────────────
            // The window the user meets first: the widget is hidden at startup
            // so a fresh install picks a mode, and can set up a wallet, before
            // the widget ever appears.
            //
            // Built by commands::launcher::build_launcher_window so that
            // launch_launcher can REBUILD it — closing a Tauri window destroys
            // it, and "show the existing one" is not enough once the user has
            // closed the launcher even once.
            match commands::launcher::build_launcher_window(&app.handle()) {
                Ok(_) => println!("[Tauri] Launcher window created"),
                Err(e) => {
                    // Never fatal. If the launcher cannot come up, the widget
                    // must still be reachable rather than leaving the user with
                    // no window at all.
                    println!("[Tauri] Launcher window failed ({e}) — showing the widget instead");
                    window.show().ok();
                    window.set_focus().ok();
                }
            }

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
