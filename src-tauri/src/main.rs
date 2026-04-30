#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::{Arc, Mutex};
use tauri::{Emitter, Listener, Manager, PhysicalSize, RunEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

#[tauri::command]
fn open_widget(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn main() {
    // Shared handle so the exit handler can kill the sidecar
    let sidecar_child: Arc<Mutex<Option<CommandChild>>> = Arc::new(Mutex::new(None));
    let sidecar_child_exit = sidecar_child.clone();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_deep_link::init())
        .invoke_handler(tauri::generate_handler![open_widget])
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
                    match cmd.spawn() {
                        Ok((_rx, child)) => {
                            println!("[Tauri] Backend sidecar started (pid={})", child.pid());
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

                // Kill the backend sidecar so it doesn't linger after the UI closes.
                //
                // CRITICAL: PyInstaller --onefile binaries spawn a separate child
                // Python process (~420 MB private memory). Tauri's CommandChild::kill()
                // only signals the parent stub; the child becomes orphaned and keeps
                // running forever, eating ~420 MB per orphan accumulating across runs.
                //
                // On Windows, taskkill /T /F kills the entire process tree by image
                // name. On Unix, pkill -9 -f does the same job. We do this in addition
                // to child.kill() to catch the orphan child.
                if let Ok(mut guard) = sidecar_child_exit.lock() {
                    if let Some(child) = guard.take() {
                        println!("[Tauri] Stopping backend sidecar (pid={})", child.pid());
                        child.kill().ok();
                    }
                }
                #[cfg(target_os = "windows")]
                {
                    let _ = std::process::Command::new("taskkill")
                        .args(["/F", "/T", "/IM", "iris-backend*"])
                        .output();
                }
                #[cfg(not(target_os = "windows"))]
                {
                    let _ = std::process::Command::new("pkill")
                        .args(["-9", "-f", "iris-backend"])
                        .output();
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
