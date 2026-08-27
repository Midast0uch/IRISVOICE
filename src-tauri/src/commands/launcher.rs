use tauri::{AppHandle, Manager};

/// Label of the launcher window created in `main.rs` at startup.
pub const LAUNCHER_LABEL: &str = "launcher";
/// Label of the widget window declared in `tauri.conf.json`.
pub const WIDGET_LABEL: &str = "main";

/// Bring a window to the front, creating nothing and building nothing.
///
/// The launcher and the widget used to be two separate Tauri applications, and
/// each of these commands ran `cmd /c npx tauri dev` on the other one. That is
/// a whole dev toolchain per click — a cargo build plus the other app's dev
/// server — which is why switching modes took minutes. It also started a SECOND
/// instance when the app was already running, so the new `tauri dev` then sat
/// waiting on a port the first one already held.
///
/// Both windows now live in this one application and exist from startup, so
/// switching is a show and a focus.
fn reveal(app: &AppHandle, label: &str) -> Result<(), String> {
    let window = app
        .get_webview_window(label)
        .ok_or_else(|| format!("window '{label}' does not exist"))?;

    // Order matters: a minimised window ignores set_focus until it is restored,
    // and a hidden one ignores unminimize until it is shown.
    window.show().map_err(|e| e.to_string())?;
    if window.is_minimized().unwrap_or(false) {
        window.unminimize().map_err(|e| e.to_string())?;
    }
    window.set_focus().map_err(|e| e.to_string())?;
    Ok(())
}

/// Show the IRIS Launcher window. Called from the widget's chat and dashboard
/// headers.
#[tauri::command]
pub async fn launch_launcher(app: AppHandle) -> Result<(), String> {
    reveal(&app, LAUNCHER_LABEL)
}

/// Show the IRIS Widget window. Called by the launcher once a mode is picked.
///
/// The widget starts hidden (`"visible": false` in tauri.conf.json) so the
/// launcher is what the user meets first and can choose a mode and set up a
/// wallet before the widget appears. The widget's frontend still loads at
/// startup behind the hidden window, so this is instant.
#[tauri::command]
pub async fn launch_widget(app: AppHandle) -> Result<(), String> {
    reveal(&app, WIDGET_LABEL)
}
