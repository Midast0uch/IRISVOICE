use std::process::Command;

/// Launch the IRIS Launcher app from the widget.
///
/// Dev: spawns `npx tauri dev` inside the launcher submodule directory so the
/// launcher dev server + window come up. Prod: launches the installed launcher
/// executable (set IRIS_LAUNCHER_EXE). The widget and launcher are separate
/// Tauri apps that share the backend on :8090 for mode sync.
#[tauri::command]
pub async fn launch_launcher() {
    #[cfg(debug_assertions)]
    {
        let dir = std::env::var("IRIS_LAUNCHER_DIR").unwrap_or_else(|_| "../iris-launcher".to_string());
        let _ = Command::new("cmd")
            .args(["/c", "npx", "tauri", "dev"])
            .current_dir(&dir)
            .spawn();
    }
    #[cfg(not(debug_assertions))]
    {
        if let Ok(exe) = std::env::var("IRIS_LAUNCHER_EXE") {
            let _ = Command::new(exe).spawn();
        }
    }
}
