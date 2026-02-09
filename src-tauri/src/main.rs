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
fn start_backend(_app_handle: &tauri::AppHandle) -> Result<(), String> {
    // Get the directory where the executable is located
    let exe_path = std::env::current_exe().map_err(|e| e.to_string())?;
    println!("[IRIS-DEBUG] Executable path: {:?}", exe_path);
    
    // Try to find the project root by looking for characteristic files
    let project_dir = find_project_root(&exe_path);
    
    println!("[IRIS-DEBUG] Resolved project directory: {:?}", project_dir);
    
    // Determine Python executable path - check both .venv and venv
    let venv_paths = if cfg!(target_os = "windows") {
        vec![
            project_dir.join(".venv\\Scripts\\python.exe"),
            project_dir.join("venv\\Scripts\\python.exe"),
        ]
    } else {
        vec![
            project_dir.join(".venv/bin/python"),
            project_dir.join("venv/bin/python"),
        ]
    };
    
    let mut python_path = std::path::PathBuf::from("python");
    for path in &venv_paths {
        println!("[IRIS-DEBUG] Checking venv path: {:?}", path);
        if path.exists() {
            println!("[IRIS-DEBUG] Found venv python at: {:?}", path);
            python_path = path.clone();
            break;
        }
    }
    
    println!("[IRIS-DEBUG] Starting backend with: {:?}", python_path);
    
    // Verify backend module exists
    let backend_main = project_dir.join("backend").join("main.py");
    println!("[IRIS-DEBUG] backend/main.py exists: {:?}", backend_main.exists());
    
    // Spawn backend process
    let mut child = Command::new(&python_path)
        .arg("-m")
        .arg("backend.main")
        .current_dir(&project_dir)
        .spawn()
        .map_err(|e| {
            println!("[IRIS-DEBUG] Failed to spawn process: {}", e);
            format!("Failed to start backend: {}", e)
        })?;
    
    println!("[IRIS-DEBUG] Process spawned, waiting for backend to be ready...");
    
    // Wait for backend to be ready (max 30 seconds)
    for i in 0..30 {
        thread::sleep(Duration::from_secs(1));
        if is_backend_running() {
            println!("[IRIS] Backend started successfully after {}s", i + 1);
            return Ok(());
        }
        println!("[IRIS-DEBUG] Attempt {}: Backend not ready yet", i + 1);
    }
    
    let _ = child.kill();
    Err("Backend failed to start within 30 seconds".to_string())
}

/// Find the project root - uses compile-time env var for dev, file search for release
fn find_project_root(exe_path: &std::path::Path) -> std::path::PathBuf {
    // In dev mode, use the compile-time CARGO_MANIFEST_DIR (src-tauri folder)
    // and go up one level to get the project root
    let manifest_dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    println!("[IRIS-DEBUG] Cargo manifest dir: {:?}", manifest_dir);
    
    // Go up from src-tauri to project root
    if let Some(project_root) = manifest_dir.parent() {
        let project_root = project_root.to_path_buf();
        if project_root.join("backend").join("main.py").exists() {
            println!("[IRIS-DEBUG] Found project root via Cargo: {:?}", project_root);
            return project_root;
        }
    }
    
    // Fallback: walk up from executable directory (for release builds)
    let mut current = exe_path.parent();
    while let Some(dir) = current {
        if dir.join("backend").join("main.py").exists() {
            println!("[IRIS-DEBUG] Found project root via walk: {:?}", dir);
            return dir.to_path_buf();
        }
        if dir.join("pyproject.toml").exists() || dir.join("package.json").exists() {
            if dir.join("backend").exists() {
                println!("[IRIS-DEBUG] Found project root via package files: {:?}", dir);
                return dir.to_path_buf();
            }
        }
        current = dir.parent();
    }
    
    // Ultimate fallback
    println!("[IRIS-DEBUG] Using fallback directory");
    exe_path.parent()
        .and_then(|p| p.parent())
        .and_then(|p| p.parent())
        .unwrap_or_else(|| exe_path.parent().unwrap_or(exe_path))
        .to_path_buf()
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