#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::Command;
use std::time::Duration;
use std::thread;
use std::path::PathBuf;
use tauri::{Manager, PhysicalSize};

/// Check if backend is already running
fn is_backend_running() -> bool {
    reqwest::blocking::get("http://localhost:8000/api/voice/status")
        .map(|resp| resp.status().is_success())
        .unwrap_or(false)
}

/// Start the Python backend
fn start_backend(app_handle: &tauri::AppHandle) -> Result<(), String> {
    let exe_path = std::env::current_exe().map_err(|e| e.to_string())?;
    println!("[IRIS-DEBUG] Executable path: {:?}", exe_path);
    
    // Find the directory containing backend/ folder
    let project_dir = find_project_root(app_handle, &exe_path);
    println!("[IRIS-DEBUG] Resolved project directory: {:?}", project_dir);
    
    // Determine Python executable - search multiple locations
    let python_path = find_python(&project_dir, &exe_path);
    println!("[IRIS-DEBUG] Using Python: {:?}", python_path);
    
    // Verify backend module exists
    let backend_main = project_dir.join("backend").join("main.py");
    println!("[IRIS-DEBUG] backend/main.py exists: {}", backend_main.exists());
    
    if !backend_main.exists() {
        return Err(format!(
            "backend/main.py not found at {:?}. Searched project dir: {:?}",
            backend_main, project_dir
        ));
    }
    
    // Spawn backend process
    let mut child = Command::new(&python_path)
        .arg("-m")
        .arg("backend.main")
        .current_dir(&project_dir)
        .spawn()
        .map_err(|e| {
            println!("[IRIS-DEBUG] Failed to spawn process: {}", e);
            format!("Failed to start backend with {:?}: {}", python_path, e)
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

/// Find Python executable - checks venv in project dir, next to exe, and system PATH
fn find_python(project_dir: &std::path::Path, exe_path: &std::path::Path) -> PathBuf {
    let exe_dir = exe_path.parent().unwrap_or(exe_path);
    
    // All candidate venv locations to check
    let candidates: Vec<PathBuf> = if cfg!(target_os = "windows") {
        vec![
            // Venv in project root (dev mode)
            project_dir.join(".venv\\Scripts\\python.exe"),
            project_dir.join("venv\\Scripts\\python.exe"),
            // Venv next to the executable (release mode)
            exe_dir.join(".venv\\Scripts\\python.exe"),
            exe_dir.join("venv\\Scripts\\python.exe"),
            // Venv one level up from exe (release: exe is in bin/ or similar)
            exe_dir.parent().map(|p| p.join("venv\\Scripts\\python.exe")).unwrap_or_default(),
            exe_dir.parent().map(|p| p.join(".venv\\Scripts\\python.exe")).unwrap_or_default(),
        ]
    } else {
        vec![
            project_dir.join(".venv/bin/python"),
            project_dir.join("venv/bin/python"),
            exe_dir.join(".venv/bin/python"),
            exe_dir.join("venv/bin/python"),
            exe_dir.parent().map(|p| p.join("venv/bin/python")).unwrap_or_default(),
            exe_dir.parent().map(|p| p.join(".venv/bin/python")).unwrap_or_default(),
        ]
    };
    
    for path in &candidates {
        if !path.as_os_str().is_empty() && path.exists() {
            println!("[IRIS-DEBUG] Found Python at: {:?}", path);
            return path.clone();
        }
    }
    
    // Fallback to system Python
    println!("[IRIS-DEBUG] No venv found, falling back to system 'python'");
    PathBuf::from("python")
}

/// Find the project root containing backend/main.py
/// Priority order:
///   1. Dev mode: CARGO_MANIFEST_DIR parent (compile-time, always correct in dev)
///   2. Release mode: Tauri resource directory (backend/ bundled as resource)
///   3. Fallback: Walk up from exe directory looking for backend/main.py
///   4. Fallback: Directory next to exe
fn find_project_root(app_handle: &tauri::AppHandle, exe_path: &std::path::Path) -> PathBuf {
    // 1. Dev mode: Use compile-time CARGO_MANIFEST_DIR (src-tauri/) -> parent = project root
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    println!("[IRIS-DEBUG] CARGO_MANIFEST_DIR: {:?}", manifest_dir);
    
    if let Some(project_root) = manifest_dir.parent() {
        let project_root = project_root.to_path_buf();
        if project_root.join("backend").join("main.py").exists() {
            println!("[IRIS-DEBUG] Found project root via CARGO_MANIFEST_DIR: {:?}", project_root);
            return project_root;
        }
    }
    
    // 2. Release mode: Tauri resource directory
    //    In release builds, resources are placed next to the exe or in a _up_/resources/ dir
    if let Ok(resource_dir) = app_handle.path().resource_dir() {
        println!("[IRIS-DEBUG] Tauri resource_dir: {:?}", resource_dir);
        if resource_dir.join("backend").join("main.py").exists() {
            println!("[IRIS-DEBUG] Found backend in Tauri resource_dir: {:?}", resource_dir);
            return resource_dir;
        }
    }
    
    // 3. Walk up from executable directory
    let mut current = exe_path.parent();
    while let Some(dir) = current {
        if dir.join("backend").join("main.py").exists() {
            println!("[IRIS-DEBUG] Found project root via walk-up: {:?}", dir);
            return dir.to_path_buf();
        }
        current = dir.parent();
    }
    
    // 4. Ultimate fallback: exe's parent directory
    let fallback = exe_path.parent().unwrap_or(exe_path).to_path_buf();
    println!("[IRIS-DEBUG] Using fallback (exe parent): {:?}", fallback);
    fallback
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