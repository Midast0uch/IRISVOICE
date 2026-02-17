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
    println!("[IRIS-DEBUG] Attempting to start backend...");

    // In development, the backend is in the project root. In production, it's in the resource dir.
    let project_dir = if cfg!(debug_assertions) {
        // In dev, run from the project root
        let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").map_err(|_| "CARGO_MANIFEST_DIR not set".to_string())?;
        std::path::Path::new(&manifest_dir).parent().unwrap().to_path_buf()
    } else {
        // In production, the backend is bundled with the app
        app_handle.path().resource_dir().map_err(|e| format!("Failed to find resource directory: {}", e))?
    };

    println!("[IRIS-DEBUG] Using project directory: {:?}", project_dir);

    // Determine the correct path to the Python executable within the venv
    let python_path = if cfg!(target_os = "windows") {
        // On Windows, the venv executable is in venv/Scripts/python.exe
        project_dir.join("venv/Scripts/python.exe")
    } else {
        // On Linux/macOS, the venv executable is in venv/bin/python
        project_dir.join("venv/bin/python")
    };
    
    println!("[IRIS-DEBUG] Python executable path check: {:?}", python_path);

    if !python_path.exists() {
        return Err(format!("Python executable not found at: {:?}", python_path));
    }

    // The project directory for the backend is also inside the resource bundle.
    let backend_dir = project_dir.join("backend");
    println!("[IRIS-DEBUG] Backend project directory check: {:?}", backend_dir);

    if !backend_dir.join("main.py").exists() {
        return Err(format!("backend/main.py not found in: {:?}", backend_dir));
    }

    println!("[IRIS-DEBUG] Spawning backend process...");
    println!("[IRIS-DEBUG] Command: `{} -m backend.main`", python_path.display());
    println!("[IRIS-DEBUG] Working Directory: `{}`", project_dir.display());

    // Spawn backend process
    let mut child = Command::new(&python_path)
        .arg("-m")
        .arg("backend.main")
        .current_dir(&project_dir) // Run the command from the project root to find 'backend' package
        .spawn()
        .map_err(|e| format!("Failed to start backend with {:?}: {}", python_path, e))?;

    println!("[IRIS-DEBUG] Process spawned, waiting for backend to be ready...");

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
            let size = PhysicalSize::new(460, 460);
            window.set_min_size(Some(size)).ok();
            window.set_max_size(Some(size)).ok();
            
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}