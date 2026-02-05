#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::Command;
use std::time::Duration;
use std::thread;
use tauri::{Manager, PhysicalSize};

/// Check if backend is already running
fn is_backend_running() -> bool {
    reqwest::blocking::get("http://localhost:8000/api/voice/status")
        .map(|resp| resp.status().is_success())
        .unwrap_or(false)
}

/// Start the Python backend
fn start_backend(app_handle: &tauri::AppHandle) -> Result<(), String> {
    let app_dir = app_handle.path().app_local_data_dir().map_err(|e| e.to_string())?;
    let project_dir = app_dir.parent().unwrap_or(&app_dir);
    
    // Determine Python executable path
    let python_path = if cfg!(target_os = "windows") {
        project_dir.join(".venv\\Scripts\\python.exe")
    } else {
        project_dir.join(".venv/bin/python")
    };
    
    let python_path = if python_path.exists() {
        python_path
    } else {
        std::path::PathBuf::from("python")
    };
    
    println!("[IRIS] Starting backend with: {:?}", python_path);
    
    // Spawn backend process
    let mut child = Command::new(python_path)
        .arg("-m")
        .arg("backend.main")
        .current_dir(&project_dir)
        .spawn()
        .map_err(|e| format!("Failed to start backend: {}", e))?;
    
    // Wait for backend to be ready (max 30 seconds)
    for i in 0..30 {
        thread::sleep(Duration::from_secs(1));
        if is_backend_running() {
            println!("[IRIS] Backend started successfully after {}s", i + 1);
            return Ok(());
        }
    }
    
    let _ = child.kill();
    Err("Backend failed to start within 30 seconds".to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let window = app.get_webview_window("main").unwrap();
            
            // Auto-start backend if not running
            std::thread::spawn({
                let app_handle = app.handle().clone();
                move || {
                    if is_backend_running() {
                        println!("[IRIS] Backend already running");
                    } else {
                        println!("[IRIS] Starting backend...");
                        if let Err(e) = start_backend(&app_handle) {
                            eprintln!("[IRIS] Failed to start backend: {}", e);
                        }
                    }
                }
            });
            
            // Keep all your existing setup
            window.set_decorations(false).ok();
            window.set_shadow(false).ok();
            window.set_always_on_top(true).ok();
            window.set_skip_taskbar(true).ok();
            
            // Keep size locked (prevents resizing/snap assist from changing size)
            let size = PhysicalSize::new(800, 800);
            window.set_min_size(Some(size)).ok();
            window.set_max_size(Some(size)).ok();
            
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}