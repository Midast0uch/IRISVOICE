use tauri::{AppHandle, Emitter, Manager};

/// Validate a caller-supplied pane name into (pane, window label).
///
/// The label is `wing-<pane>`, and the frontend reads the pane back OUT of the
/// label, so this one match is the only place the set of panes is defined.
/// Rejecting anything else keeps an arbitrary string from becoming a window
/// label, and keeps `reattach_wing` from closing a window it has no business
/// closing.
fn pane_label(pane: &str) -> Result<(&'static str, &'static str), String> {
    match pane {
        "chat" => Ok(("chat", "wing-chat")),
        "dashboard" => Ok(("dashboard", "wing-dashboard")),
        other => Err(format!("unknown pane '{other}'")),
    }
}

fn pane_title(pane: &str) -> &'static str {
    match pane {
        "chat" => "IRIS Chat",
        _ => "IRIS Dashboard",
    }
}

/// Pop a wing out of the widget into its own window.
///
/// WHY A WINDOW AND NOT A PANEL. The widget window is transparent, borderless
/// and always-on-top, and Windows will not let one window straddle two
/// monitors usefully. A wing the user wants on a second screen has to BE a
/// window, so the OS owns its placement and it stays where it is put.
///
/// The detached window shares this process, and that is what makes it cheap:
/// ws_client.rs emits on the AppHandle, which broadcasts to EVERY window, and
/// start_ws_client is idempotent. So the new window receives the same live
/// event stream over the SAME backend socket. It must not open its own — the
/// backend keeps one socket per client id and evicts the previous one, which
/// is the reconnect storm that cancelled in-flight agent work (pin_a414a1cc8e87).
///
/// Decorated on purpose: the titlebar is how the user drags it to the other
/// monitor, and it gives them a close button that reattaches.
#[tauri::command]
pub async fn detach_wing(app: AppHandle, pane: String) -> Result<(), String> {
    let (pane, label) = pane_label(&pane)?;

    // Already detached — the user clicked twice, or clicked while it was
    // behind something. Raise it rather than building a second one.
    if let Some(existing) = app.get_webview_window(label) {
        existing.show().map_err(|e| e.to_string())?;
        if existing.is_minimized().unwrap_or(false) {
            existing.unminimize().map_err(|e| e.to_string())?;
        }
        existing.set_focus().map_err(|e| e.to_string())?;
        return Ok(());
    }

    // The plain app root, with NOTHING encoded in the URL. Which wing this
    // window shows comes from its LABEL, which the frontend reads back through
    // getCurrentWindow().label.
    //
    // The pane was in the URL first, as ?pane=<name>. That cannot survive
    // packaging: WebviewUrl::App takes a PathBuf, so "index.html?pane=chat" is
    // a FILENAME to the asset resolver, not a path plus a query, and it 404s
    // in a bundle while working perfectly in dev. The label is the same value
    // in both profiles and needs no encoding.
    #[cfg(debug_assertions)]
    let url = tauri::WebviewUrl::External(
        "http://localhost:3000/"
            .parse()
            .map_err(|_| "could not build the wing dev url".to_string())?,
    );
    #[cfg(not(debug_assertions))]
    let url = tauri::WebviewUrl::App("index.html".into());

    let reattach_app = app.clone();

    let window = tauri::WebviewWindowBuilder::new(&app, label, url)
        .title(pane_title(pane))
        .inner_size(760.0, 880.0)
        .min_inner_size(420.0, 480.0)
        .resizable(true)
        // Decorated and opaque, unlike the widget. A wing on a second monitor
        // is a normal window the user manages normally; the frameless glass
        // treatment only makes sense for the orb floating over the desktop.
        .decorations(true)
        .transparent(false)
        .always_on_top(false)
        .skip_taskbar(false)
        .visible(true)
        .build()
        .map_err(|e| e.to_string())?;

    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { .. } = event {
            // Closing a detached wing puts it back in the widget. Without this
            // the wing would simply vanish, and the only way back would be to
            // work out that it is still "open" somewhere.
            let _ = reattach_app.emit("wing:reattach", pane);
        }
    });

    Ok(())
}

/// Close a detached wing from the wing itself, reattaching it to the widget.
///
/// The window event above does the reattach, so this only has to close.
#[tauri::command]
pub async fn reattach_wing(app: AppHandle, pane: String) -> Result<(), String> {
    let (_, label) = pane_label(&pane)?;
    if let Some(window) = app.get_webview_window(label) {
        window.close().map_err(|e| e.to_string())?;
    }
    Ok(())
}
