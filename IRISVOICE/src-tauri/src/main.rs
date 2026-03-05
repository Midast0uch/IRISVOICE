#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{Emitter, Listener, Manager, PhysicalSize, RunEvent};

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_deep_link::init())
        .setup(|app| {
            let window = app.get_webview_window("main").unwrap();
            
            // Keep all your existing setup
            window.set_decorations(false).ok();
            window.set_shadow(false).ok();
            window.set_always_on_top(true).ok();
            window.set_skip_taskbar(true).ok();
            
            // Keep size locked (prevents resizing/snap assist from changing size)
            let size = PhysicalSize::new(680, 680);
            window.set_min_size(Some(size)).ok();
            window.set_max_size(Some(size)).ok();
            
            // Handle deep links for OAuth callbacks
            let app_handle = app.handle().clone();
            app.listen("deep-link", move |event| {
                if let Ok(payload) = serde_json::from_str::<Vec<String>>(&event.payload()) {
                    if let Some(url) = payload.first() {
                        println!("Deep link received: {}", url);
                        
                        // Emit event to frontend with the URL
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
    
    // Run with shutdown cleanup
    app.run(|_app_handle, event| {
        match event {
            RunEvent::ExitRequested { api, .. } => {
                println!("[Tauri] Exit requested - triggering cleanup");
                
                // Emit cleanup event to frontend before exit
                if let Some(window) = _app_handle.get_webview_window("main") {
                    window.emit("app-cleanup", ()).ok();
                }
                
                // Allow exit to proceed
                api.prevent_exit();
            }
            RunEvent::Exit => {
                println!("[Tauri] Application exiting - cleanup complete");
            }
            _ => {}
        }
    });
}