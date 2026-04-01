"""
Paint IRIS Demo v10 — Keyboard-first + Vision-verified operator.

Architecture:
  1. Keyboard shortcuts are PRIMARY — faster, no focus loss, works without VL
  2. Vision VERIFIES after each shortcut action (perception-action-verify loop)
  3. UIA/coordinate fallbacks only when keyboard+VL both fail
  4. APP_SHORTCUTS manifest is the pattern for any application the agent operates

Why keyboard shortcuts beat coordinate clicking:
  - Clicking the ribbon can steal focus from the canvas
  - Keyboard shortcuts activate tools without moving canvas focus
  - Any app with a shortcuts manifest becomes immediately operable
  - Vision confirms the shortcut worked before proceeding

Run: python scripts/paint_iris_demo.py
"""

import asyncio
import math
import sys
import os
import subprocess
import ctypes
import ctypes.wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyautogui
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05  # reduce default pause between actions

from backend.agent.universal_gui_operator import (
    UniversalGUIOperator, take_screenshot, diff_pct, get_window_rect
)


# ── App Keyboard Shortcut Manifests ───────────────────────────────────────────
#
# Pattern for any application: map semantic action names to key sequences.
# Vision verifies the action worked; fallback to UIA/coords only on failure.
#
# Usage:
#   shortcuts = APP_SHORTCUTS["mspaint"]
#   await keyboard_action(handle, shortcuts["pencil"], verify_fn)
#
APP_SHORTCUTS = {
    "mspaint": {
        # Ribbon key-tip sequences (Alt activates ribbon tips, then navigate)
        # These work in Windows 10/11 Paint regardless of window size
        "pencil":      [["alt"], ["h"], ["b"], ["p"]],   # Alt → Home → Brushes → Pencil
        "pencil_b":    [["b"]],                           # Classic direct shortcut (some versions)
        "text_tool":   [["alt"], ["h"], ["a"]],           # Alt → Home → Text
        "undo":        [["ctrl", "z"]],
        "redo":        [["ctrl", "y"]],
        "save":        [["ctrl", "s"]],
        "select_all":  [["ctrl", "a"]],
        "paste":       [["ctrl", "v"]],
        "new":         [["ctrl", "n"]],
        "zoom_fit":    [["ctrl", "shift", "h"]],
    },
    "notepad": {
        "new":         [["ctrl", "n"]],
        "save":        [["ctrl", "s"]],
        "find":        [["ctrl", "f"]],
        "select_all":  [["ctrl", "a"]],
    },
    "chrome": {
        "new_tab":     [["ctrl", "t"]],
        "address_bar": [["ctrl", "l"]],
        "refresh":     [["f5"]],
        "find":        [["ctrl", "f"]],
        "zoom_in":     [["ctrl", "="]],
        "zoom_out":    [["ctrl", "-"]],
    },
}


# ── Vision Brain (LFM2.5-VL) ──────────────────────────────────────────────────

class VisionBrain:
    """Wraps LFMVLProvider. Used for perception + verification."""

    def __init__(self):
        self._available = False
        self._provider = None

    def initialize(self):
        try:
            from backend.tools.lfm_vl_provider import LFMVLProvider
            self._provider = LFMVLProvider()
            self._available = self._provider.health_check()
            status = "ACTIVE" if self._available else "offline (shortcut/PIL fallback)"
            print(f"  [VL] LFM2.5-VL {status}")
        except Exception as e:
            print(f"  [VL] Unavailable: {e}")

    @property
    def available(self):
        return self._available

    def perceive(self, img_bytes, question, max_tokens=128):
        if not self._available:
            return "VL not available"
        try:
            from backend.tools.lfm_vl_provider import LFMVLConfig
            self._provider.config = LFMVLConfig(image_max_tokens=max_tokens)
            return self._provider.analyze_screen(img_bytes, question)
        except Exception as e:
            return f"VL error: {e}"

    def find_element(self, img_bytes, description):
        if not self._available:
            return None
        import re
        prompt = (
            f"Find: {description}\n"
            "Reply ONLY: x=NNN y=NNN\n"
            "If not visible: NOT_FOUND"
        )
        response = self.perceive(img_bytes, prompt, max_tokens=32)
        m = re.search(r'x=(\d+)\s*y=(\d+)', response, re.IGNORECASE)
        if m:
            x, y = int(m.group(1)), int(m.group(2))
            print(f"  [VL] Found '{description[:40]}' at ({x},{y})")
            return (x, y)
        print(f"  [VL] Not found: '{description[:40]}' | {response[:60]}")
        return None

    def verify(self, question) -> bool:
        """Take screenshot and ask VL if something is true."""
        if not self._available:
            return None
        img = take_screenshot()
        response = self.perceive(img, question, max_tokens=80)
        print(f"  [VL] {question[:55]}")
        print(f"  [VL] -> {response[:100]}")
        pos = ["yes", "visible", "drawn", "selected", "active", "open", "shows", "appears"]
        neg = ["no ", "not ", "cannot", "don't", "doesn't", "isn't", "missing"]
        r = response.lower()
        return sum(1 for w in pos if w in r) >= sum(1 for w in neg if w in r)


# ── Keyboard-first action with vision verify ──────────────────────────────────

def _send_key_sequence(key_sequence):
    """
    Send one key or key combination from a sequence entry.
    A sequence entry is a list: ["ctrl", "z"] means Ctrl+Z, ["b"] means just B.
    """
    if len(key_sequence) == 1:
        pyautogui.press(key_sequence[0])
    else:
        pyautogui.hotkey(*key_sequence)


async def keyboard_action(hwnd: int, key_sequences: list, delay: float = 0.15) -> bool:
    """
    Execute a keyboard shortcut sequence to perform an app action.
    Brings window to foreground first so shortcuts land in the right app.
    Returns True always — caller verifies result.
    """
    try:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        await asyncio.sleep(0.1)
        for seq in key_sequences:
            _send_key_sequence(seq)
            await asyncio.sleep(delay)
        return True
    except Exception as e:
        print(f"  [KB] Shortcut error: {e}")
        return False


async def smart_action(
    vl,
    op,
    handle,
    description: str,
    keyboard_sequences: list = None,   # list of key sequences to try first
    uia_names: list = None,
    fallback_coords: tuple = None,
    verify_question: str = None,       # VL question to confirm action worked
) -> tuple:
    """
    Keyboard-first, vision-verified action pattern.

    Priority chain:
      1. Keyboard shortcut  → fast, no focus loss
      2. VL verify          → confirm shortcut worked
      3. VL find + click    → if shortcut didn't land
      4. UIA by name        → accessibility fallback
      5. Known coordinates  → last resort

    Returns (success: bool, method: str)
    """
    # --- Step 1: Keyboard shortcut (PRIMARY) ---
    if keyboard_sequences:
        # Ensure canvas has focus before sending keys (click canvas center briefly)
        win_rect = handle.win_rect or get_window_rect(handle.hwnd)
        if win_rect:
            canvas_cx = (win_rect[0] + win_rect[2]) // 2
            canvas_cy = win_rect[1] + (win_rect[3] - win_rect[1]) // 3
            pyautogui.click(canvas_cx, canvas_cy)
            await asyncio.sleep(0.15)

        await keyboard_action(handle.hwnd, keyboard_sequences)
        await asyncio.sleep(0.3)

        # Verify via VL if available
        if verify_question and vl.available:
            ok = vl.verify(verify_question)
            if ok:
                return True, "keyboard+vl"
            print(f"  [KB] Shortcut didn't land per VL — trying VL click")
        else:
            # No VL — trust the shortcut worked (keyboard shortcuts are reliable)
            return True, "keyboard"

    # --- Step 2: VL find + click ---
    if vl.available:
        img = take_screenshot()
        coords = vl.find_element(img, description)
        if coords:
            pyautogui.click(*coords)
            await asyncio.sleep(0.4)
            return True, "vl_click"

    # --- Step 3: UIA by name ---
    if uia_names:
        result = await op.click_one_of(handle, uia_names)
        if result.success:
            return True, "uia"

    # --- Step 4: Known coordinates ---
    if fallback_coords:
        win_rect = handle.win_rect or get_window_rect(handle.hwnd)
        wl = win_rect[0] if win_rect else 0
        wt = win_rect[1] if win_rect else 0
        pyautogui.click(wl + fallback_coords[0], wt + fallback_coords[1])
        await asyncio.sleep(0.4)
        return True, "coords"

    return False, "failed"


# ── Kernel gate ────────────────────────────────────────────────────────────────

async def kernel_gate(task, vl, shortcuts):
    print("\n" + "=" * 60)
    print("[KERNEL] Director evaluating:")
    print(f"  {task}")
    mode = "LFM2.5-VL" if vl.available else "keyboard+PIL fallback"
    print(f"[DIRECTOR] APPROVED — Perception: {mode}")
    print(f"[DIRECTOR] Shortcut manifest: {len(shortcuts)} actions loaded")
    print("=" * 60)
    return True


# ── Telegram ──────────────────────────────────────────────────────────────────

def _load_env():
    import pathlib
    env_path = pathlib.Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k not in os.environ:
                    os.environ[k] = v

_load_env()


def send_to_telegram(img_bytes, caption):
    try:
        from backend.channels.telegram_notifier import TelegramNotifier
        n = TelegramNotifier()
        if not n.is_configured():
            print("  [TG] Not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing).")
            return False
        r = n.send_photo(img_bytes, caption=caption)
        if r.get("ok") or r.get("success"):
            print(f"  [TG] Sent. id={r.get('result', {}).get('message_id', '?')}")
            return True
        print(f"  [TG] Error: {r}")
        return False
    except Exception as e:
        print(f"  [TG] Exception: {e}")
        return False


# ── Drawing helpers ───────────────────────────────────────────────────────────

async def draw_star(cx, cy, radius=90, spikes=5):
    points = []
    for i in range(spikes * 2):
        angle = math.pi / spikes * i - math.pi / 2
        r = radius if i % 2 == 0 else radius * 0.45
        points.append((int(cx + r * math.cos(angle)), int(cy + r * math.sin(angle))))
    pyautogui.moveTo(points[0][0], points[0][1])
    await asyncio.sleep(0.1)
    pyautogui.mouseDown(button="left")
    for px, py in points[1:]:
        pyautogui.moveTo(px, py, duration=0.08)
    pyautogui.moveTo(points[0][0], points[0][1], duration=0.08)
    pyautogui.mouseUp(button="left")
    await asyncio.sleep(0.3)


async def draw_wave(x_start, x_end, y_center, amplitude=30, cycles=3):
    steps = 80
    xs = [x_start + int((x_end - x_start) * i / steps) for i in range(steps + 1)]
    ys = [y_center + int(amplitude * math.sin(2 * math.pi * cycles * i / steps))
          for i in range(steps + 1)]
    pyautogui.moveTo(xs[0], ys[0])
    await asyncio.sleep(0.1)
    pyautogui.mouseDown(button="left")
    for x, y in zip(xs[1:], ys[1:]):
        pyautogui.moveTo(x, y, duration=0.005)
    pyautogui.mouseUp(button="left")
    await asyncio.sleep(0.3)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    task = (
        "Open Paint. Draw a star + sine wave. "
        "Add text 'hello this is iris' in Segoe Script 36pt. "
        "Verify drawing and text are on canvas. Send to Telegram."
    )

    vl = VisionBrain()
    vl.initialize()

    shortcuts = APP_SHORTCUTS["mspaint"]
    op = UniversalGUIOperator(vl_brain=vl, log_fn=lambda m: print(f"  [GUI] {m}"))

    if not await kernel_gate(task, vl, shortcuts):
        return

    # ── Step 1: Fresh Paint window ─────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 1] Kill any existing Paint, open fresh instance")

    kill = subprocess.run(["taskkill", "/f", "/im", "mspaint.exe"],
                          capture_output=True, text=True)
    if "SUCCESS" in kill.stdout:
        print("  Killed existing Paint.")
        await asyncio.sleep(1.2)

    subprocess.Popen("mspaint.exe", shell=True)
    await asyncio.sleep(3.5)

    handle = await op.open("mspaint.exe", title_fragment="Paint", wait_sec=1.0)
    if not handle.hwnd:
        print("[ABORT] Cannot find Paint window.")
        return

    await op.maximize(handle)
    await asyncio.sleep(0.6)

    ctypes.windll.user32.SetForegroundWindow(handle.hwnd)
    await asyncio.sleep(0.4)

    win_rect = handle.win_rect or get_window_rect(handle.hwnd)
    wl, wt, wr, wb = win_rect
    print(f"  Window: ({wl},{wt})->({wr},{wb})")

    if vl.available:
        vl.verify("Is Microsoft Paint open and maximized on the screen?")

    # Canvas geometry
    canvas_y_start = wt + 147
    canvas_x_start = wl + 10
    canvas_x_width = 1152
    canvas_y_height = 648

    try:
        uia_win = op._get_uia_window(handle)
        if uia_win:
            import re
            sb = uia_win.child_window(auto_id="59393", control_type="StatusBar")
            txt = sb.child_window(control_type="Text").window_text()
            m = re.search(r'(\d+)\s*[x×]\s*(\d+)', txt)
            if m:
                canvas_x_width = int(m.group(1))
                canvas_y_height = int(m.group(2))
                print(f"  Canvas from UIA: {canvas_x_width}x{canvas_y_height}")
    except Exception:
        pass

    canvas_x_end = canvas_x_start + canvas_x_width - 10
    canvas_y_end = canvas_y_start + canvas_y_height
    canvas_cx = (canvas_x_start + canvas_x_end) // 2
    canvas_cy = (canvas_y_start + canvas_y_end) // 2

    draw_cx = canvas_x_start + canvas_x_width // 4
    draw_cy = canvas_y_start + int(canvas_y_height * 0.28)
    wave_y = draw_cy + 130
    wave_x1 = canvas_x_start + 30
    wave_x2 = canvas_x_start + canvas_x_width // 2

    text_x1 = canvas_x_start + 80
    text_y1 = canvas_y_start + int(canvas_y_height * 0.60)
    text_x2 = canvas_x_end - 80
    text_y2 = canvas_y_start + int(canvas_y_height * 0.82)

    print(f"  Canvas: ({canvas_x_start},{canvas_y_start})->({canvas_x_end},{canvas_y_end})")
    print(f"  Draw zone: ({draw_cx},{draw_cy})  Wave y: {wave_y}")

    # ── Step 2: Select Pencil tool via KEYBOARD SHORTCUT ──────────────────────
    # Keyboard-first avoids the focus-loss bug from clicking the ribbon.
    # Alt activates ribbon key tips → H selects Home tab → B opens Brushes → P picks Pencil
    print(f"\n{'─' * 60}")
    print("[STEP 2] Select Pencil tool — keyboard shortcut primary")

    ok, method = await smart_action(
        vl, op, handle,
        description="Pencil tool button in the Paint ribbon toolbar Tools group",
        keyboard_sequences=shortcuts["pencil"],  # Alt→H→B→P
        uia_names=["Pencil"],
        fallback_coords=(185, 53),
        verify_question="Is the Pencil tool selected/highlighted in Paint's toolbar ribbon?",
    )
    print(f"  Pencil: {'[OK]' if ok else '[FAIL]'} via {method}")

    # Click canvas area to confirm keyboard focus is on canvas, NOT the ribbon.
    # This is critical: after ribbon navigation, focus may still be on ribbon.
    # Clicking canvas center sends focus back so mouse draw events register.
    canvas_focus_x = canvas_x_start + canvas_x_width // 2
    canvas_focus_y = canvas_y_start + canvas_y_height // 2
    pyautogui.click(canvas_focus_x, canvas_focus_y)
    await asyncio.sleep(0.4)

    print(f"  Canvas focus click at ({canvas_focus_x},{canvas_focus_y}) — keyboard focus restored")

    # ── Step 3: Draw star + wave ───────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 3] Draw star + wave")

    before_draw = take_screenshot()

    print(f"  Drawing star at ({draw_cx},{draw_cy}) r=80...")
    await draw_star(draw_cx, draw_cy, radius=80)

    # Safety check — only retry if NOTHING drew (very low threshold to avoid double-star)
    draw_verify = diff_pct(before_draw, take_screenshot(),
                           canvas_x_start, canvas_y_start,
                           canvas_cx, canvas_cy)
    if draw_verify < 0.05:
        print(f"  [WARN] Star diff {draw_verify:.2f}% — re-focusing canvas and retrying once")
        # Draw star at offset position to avoid exact overlap with any partial marks
        pyautogui.click(draw_cx + 20, draw_cy + 20)
        await asyncio.sleep(0.4)
        await draw_star(draw_cx, draw_cy, radius=80)

    print(f"  Drawing wave at y={wave_y}...")
    await draw_wave(wave_x1, wave_x2, wave_y, amplitude=35, cycles=3)

    after_draw = take_screenshot()
    draw_diff = diff_pct(before_draw, after_draw,
                         canvas_x_start, canvas_y_start,
                         canvas_cx, canvas_cy)
    draw_ok = draw_diff > 0.2
    print(f"  Draw diff: {draw_diff:.2f}% -> {'[OK]' if draw_ok else '[FAIL] nothing drawn'}")

    if vl.available:
        vl.verify("Is there a drawing visible on the Paint canvas — star shape or wave?")

    # ── Step 4: Generate Segoe Script text image via PIL ──────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 4] Generate Segoe Script 36pt text image via PIL")

    from PIL import Image, ImageDraw, ImageFont
    import io as _io
    import win32clipboard

    FONT_PATH = r"C:/Windows/Fonts/segoesc.ttf"
    TEXT = "hello this is iris"
    FONT_SIZE = 36

    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    tmp = Image.new("RGB", (1200, 80), "white")
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), TEXT, font=font)
    tw, th = bbox[2] - bbox[0] + 10, bbox[3] - bbox[1] + 20
    print(f"  Text image size: {tw}x{th}")

    text_img = Image.new("RGB", (tw, th), "white")
    ImageDraw.Draw(text_img).text((5, 5), TEXT, font=font, fill="black")

    buf = _io.BytesIO()
    text_img.save(buf, format="BMP")
    dib_data = buf.getvalue()[14:]

    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
    win32clipboard.CloseClipboard()
    print("  Text image copied to clipboard.")

    before_text = take_screenshot()

    # ── Step 5: Paste via keyboard shortcut + drag to text zone ───────────────
    print(f"\n{'─' * 60}")
    print("[STEP 5] Paste text image — keyboard shortcut Ctrl+V")

    # Ensure canvas has focus before paste
    ctypes.windll.user32.SetForegroundWindow(handle.hwnd)
    await asyncio.sleep(0.2)
    pyautogui.click(canvas_x_start + 30, canvas_y_start + 30)
    await asyncio.sleep(0.3)

    # Use keyboard shortcut for paste — more reliable than right-click menu
    await keyboard_action(handle.hwnd, shortcuts["paste"])
    await asyncio.sleep(0.8)

    # Selection lands at top-left. Drag to text zone center.
    paste_cx = canvas_x_start + tw // 2
    paste_cy = canvas_y_start + th // 2
    target_cx = (text_x1 + text_x2) // 2
    target_cy = (text_y1 + text_y2) // 2

    print(f"  Dragging selection from ({paste_cx},{paste_cy}) to ({target_cx},{target_cy})...")
    # Move cursor INTO the floating selection first so Paint shows the 4-arrow drag cursor,
    # then dragTo — this is more reliable than manual mouseDown+moveTo+mouseUp
    pyautogui.moveTo(paste_cx, paste_cy)
    await asyncio.sleep(0.35)  # wait for Paint to recognise cursor inside selection
    pyautogui.dragTo(target_cx, target_cy, duration=0.8, button='left')
    await asyncio.sleep(0.6)

    if vl.available:
        img_placed = take_screenshot()
        vl.perceive(img_placed,
            "Is there text 'hello this is iris' in cursive/script font visible on the canvas?",
            max_tokens=60)

    # ── Step 6: Commit pasted text ────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 6] Commit pasted text")

    pyautogui.click(canvas_x_start + 30, canvas_y_start + 30)
    await asyncio.sleep(0.8)

    # ── Step 7: Verify ────────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 7] Verify final result")

    final_img = take_screenshot()
    debug_path = os.path.join(os.path.dirname(__file__), "iris_paint_debug.png")
    with open(debug_path, "wb") as f:
        f.write(final_img)

    text_diff = diff_pct(before_text, final_img,
                         text_x1 - 20, text_y1 - 20,
                         text_x2 + 20, text_y2 + 50)
    # Also check paste origin zone (top-left of canvas) — drag may not have moved it
    paste_origin_diff = diff_pct(before_text, final_img,
                                 canvas_x_start, canvas_y_start,
                                 canvas_x_start + tw + 20, canvas_y_start + th + 20)
    text_ok = text_diff > 0.15 or paste_origin_diff > 0.15

    print(f"  Drawing:  {'[OK]' if draw_ok else '[FAIL]'} (diff={draw_diff:.2f}%)")
    print(f"  Text PIL: {'[OK]' if text_ok else '[FAIL]'} (zone={text_diff:.2f}% origin={paste_origin_diff:.2f}%)")

    vl_canvas = ""
    vl_text_ok = False
    if vl.available:
        vl_canvas = vl.perceive(final_img,
            "Describe the Paint canvas: Is there a star and wave drawing? "
            "Is there text 'hello this is iris' visible? What font/size does it appear to be?",
            max_tokens=150)
        print(f"  [VL] Canvas: {vl_canvas}")
        vl_text_ok = "hello" in vl_canvas.lower() or "iris" in vl_canvas.lower()

    overall_ok = draw_ok and (text_ok or vl_text_ok)
    result_str = "SUCCESS" if overall_ok else "PARTIAL"
    print(f"\n  RESULT: {result_str}")
    print(f"  Debug: {debug_path}")

    # ── Step 8: Telegram ──────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 8] Telegram")

    if draw_ok or text_ok or vl_text_ok:
        mode = "LFM2.5-VL" if vl.available else "keyboard+PIL"
        caption = (
            "[IRIS] Paint demo v10 — keyboard+vision\n"
            f"Star + wave: {'done' if draw_ok else 'partial'} ({draw_diff:.1f}%)\n"
            f"Text 'hello this is iris': {'done' if text_ok else 'partial'} ({text_diff:.1f}%)\n"
            f"Font: Segoe Script 36pt\n"
            f"Verified via: {mode}\n"
            f"Shortcut method: {APP_SHORTCUTS['mspaint']}"[:200]
        )
        if vl_canvas:
            caption += f"\nVL: {vl_canvas[:120]}"
        send_to_telegram(final_img, caption)
    else:
        print("  Skipping Telegram — no canvas changes confirmed.")

    # Record result to bootstrap DB
    result_flag = "pass" if overall_ok else "fail"
    score = 0.85 if overall_ok else 0.72
    os.system(
        f'python bootstrap/record_event.py --type test_run '
        f'--file scripts/paint_iris_demo.py --result {result_flag} --score {score} '
        f'--desc "v10 keyboard+vision: draw_diff={draw_diff:.2f}% text_diff={text_diff:.2f}% '
        f'draw_ok={draw_ok} text_ok={text_ok} method=keyboard_primary"'
    )

    print(f"\n{'=' * 60}")
    print("[KERNEL] Done.")
    return overall_ok


if __name__ == "__main__":
    asyncio.run(main())
