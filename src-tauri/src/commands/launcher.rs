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
/// Block until `url` returns a success status, or the deadline passes.
///
/// Dev only. A cold Next route can take tens of seconds to compile, and a
/// webview that navigates during that time lands on a failed load with no
/// retry. Capped so a genuinely dead server delays startup rather than hanging
/// it, and never fatal — if it gives up, the window is built anyway and the
/// user can reload.
#[cfg(debug_assertions)]
fn wait_for_dev_route(url: &str) {
    use std::time::{Duration, Instant};

    let deadline = Instant::now() + Duration::from_secs(90);
    let client = match reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(20))
        .build()
    {
        Ok(c) => c,
        Err(_) => return,
    };

    let mut reported = false;
    while Instant::now() < deadline {
        match client.get(url).send() {
            Ok(resp) if resp.status().is_success() => {
                println!("[Tauri] dev route ready: {url}");
                return;
            }
            _ => {
                if !reported {
                    println!("[Tauri] waiting for dev route to compile: {url}");
                    reported = true;
                }
                std::thread::sleep(Duration::from_millis(500));
            }
        }
    }
    println!("[Tauri] dev route still not ready, building the window anyway: {url}");
}

/// Build the launcher window.
///
/// Lives here rather than inline in main.rs so `launch_launcher` can REBUILD it.
/// Closing a Tauri window DESTROYS it, so after the user closed the launcher
/// once, get_webview_window("launcher") returned None forever and the widget's
/// "Open IRIS Launcher" button failed silently — the log showed
/// `reveal('launcher') called` with no `shown + focused` after it.
pub fn build_launcher_window(app: &AppHandle) -> Result<tauri::WebviewWindow, String> {
    // DEV uses an explicit url rather than the App path. Measured:
    // WebviewUrl::App("launcher/index.html") did NOT apply the path in dev —
    // the window loaded the dev-server ROOT and rendered the WIDGET. The origin
    // is the SAME as devUrl, which is what keeps the window "local" and keeps
    // its IPC; the earlier IPC failure was an External url on a DIFFERENT
    // origin (:8080).
    #[cfg(debug_assertions)]
    let dev_url: tauri::Url = "http://localhost:3000/launcher/index.html"
        .parse()
        .map_err(|_| "could not build the launcher dev url".to_string())?;
    #[cfg(debug_assertions)]
    let url = tauri::WebviewUrl::External(dev_url.clone());
    #[cfg(not(debug_assertions))]
    let url = tauri::WebviewUrl::App("launcher/index.html".into());

    // Wait until the dev server can actually SERVE that url before pointing a
    // window at it.
    //
    // Tauri waits for devUrl to answer, but that only proves the server is
    // listening — Next still has to COMPILE the route, which for this project
    // takes 12s+ on a cold start. A window created during that window navigates,
    // fails, and never retries: it just sits there blank and white, which is
    // exactly what the user saw. Polling costs nothing once the route is warm
    // (a few ms) and turns a permanent blank page into a short startup delay.
    // A readiness check on the launcher's own route only.
    //
    // Warming the widget's "/" here too was tried and removed: it blocks
    // Tauri's setup() — and therefore the whole app — for as long as Turbopack
    // takes, and it still did not fix the blank window. Waiting is the wrong
    // instrument; the retry below is the one that actually works, because it
    // does not need to predict when the server will be ready.
    #[cfg(debug_assertions)]
    wait_for_dev_route("http://localhost:3000/launcher/index.html");

    let widget_fallback = app.get_webview_window(WIDGET_LABEL);

    let window = tauri::WebviewWindowBuilder::new(app, LAUNCHER_LABEL, url)
        .title("IRIS Launcher")
        .inner_size(1100.0, 720.0)
        .min_inner_size(900.0, 600.0)
        .resizable(true)
        .center()
        .visible(true)
        .build()
        .map_err(|e| e.to_string())?;

    // Closing the launcher must never strand the user. RunEvent::ExitRequested
    // calls prevent_exit(), so a process whose only visible window has just been
    // closed stays alive with nothing on screen — and the widget is skipTaskbar,
    // so it would not even appear in the taskbar.
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { .. } = event {
            if let Some(widget) = &widget_fallback {
                if !widget.is_visible().unwrap_or(false) {
                    widget.show().ok();
                    widget.set_focus().ok();
                }
            }
        }
    });

    // SELF-HEAL. The window's initial navigation can fail outright — the dev
    // server is mid-compile, or busy serving the widget's "/" — and a webview
    // that fails to load does NOT retry. It just sits on about:blank showing a
    // blank white page, which is precisely what the user saw.
    //
    // Two attempts to fix this by WAITING (a readiness gate on the launcher
    // route, then on both routes) both failed: the route was verifiably ready
    // and the window was still blank. So stop trying to predict the right
    // moment and simply check the outcome — if the window is still on
    // about:blank, navigate it again. This is timing-independent by
    // construction, and it costs nothing once the page is up because the first
    // check ends the loop.
    #[cfg(debug_assertions)]
    {
        let healer = window.clone();
        let target = dev_url;
        std::thread::spawn(move || {
            for attempt in 1..=12 {
                std::thread::sleep(std::time::Duration::from_secs(3));
                let current = healer.url().map(|u| u.to_string()).unwrap_or_default();
                if !current.is_empty() && current != "about:blank" {
                    println!("[Tauri] launcher window loaded: {current}");
                    return;
                }
                println!(
                    "[Tauri] launcher still blank (attempt {attempt}) — navigating explicitly"
                );
                if let Err(e) = healer.navigate(target.clone()) {
                    println!("[Tauri] launcher navigate failed: {e}");
                }
            }
            println!("[Tauri] launcher never left about:blank after 12 attempts");
        });
    }

    Ok(window)
}

fn reveal(app: &AppHandle, label: &str) -> Result<(), String> {
    // Logged on ARRIVAL, before anything can fail. A remote-origin window whose
    // capability does not match drops invoke() silently on the JS side, so the
    // only way to tell "the command failed" from "the command never arrived" is
    // to print the moment it lands.
    println!("[Tauri] reveal('{label}') called");

    let window = match app.get_webview_window(label) {
        Some(w) => w,
        // Gone. Closing a window destroys it, so the launcher has to be
        // rebuilt rather than merely shown. The widget is only ever hidden, so
        // it should always be found; if it is not, there is nothing to rebuild
        // it from and the error is the honest answer.
        None if label == LAUNCHER_LABEL => {
            println!("[Tauri] launcher window was destroyed — rebuilding");
            build_launcher_window(app)?
        }
        None => return Err(format!("window '{label}' does not exist")),
    };

    // Order matters: a minimised window ignores set_focus until it is restored,
    // and a hidden one ignores unminimize until it is shown.
    if let Err(e) = window.show() {
        println!("[Tauri] reveal('{label}') show failed: {e}");
        return Err(e.to_string());
    }
    if window.is_minimized().unwrap_or(false) {
        if let Err(e) = window.unminimize() {
            println!("[Tauri] reveal('{label}') unminimize failed: {e}");
        }
    }
    if let Err(e) = window.set_focus() {
        println!("[Tauri] reveal('{label}') set_focus failed: {e}");
        return Err(e.to_string());
    }
    println!("[Tauri] reveal('{label}') shown + focused");
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
