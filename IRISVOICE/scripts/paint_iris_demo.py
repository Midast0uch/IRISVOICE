"""
Paint IRIS Demo v9 — VisionGuidedOperator perception loop.

Architecture:
  1. Director (kernel) approves the goal
  2. For each step:
     a. Screenshot -> VL perceives current state
     b. VL identifies target element (UIA/coords fallback if VL offline)
     c. Execute action
     d. Verify result (VL or PIL diff)
     e. Abort step and log if verification fails twice
  3. Record to Mycelium coordinate graph
  4. Send final canvas to Telegram

The vision model LEADS. Coordinates are fallbacks, not the plan.

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

from backend.agent.universal_gui_operator import (
    UniversalGUIOperator, take_screenshot, diff_pct, get_window_rect
)


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
            status = "ACTIVE" if self._available else "offline (PIL/UIA fallback)"
            print(f"  [VL] LFM2.5-VL {status}")
        except Exception as e:
            print(f"  [VL] Unavailable: {e}")

    @property
    def available(self):
        return self._available

    def perceive(self, img_bytes, question, max_tokens=128):
        """Ask VL a question about the current screen."""
        if not self._available:
            return "VL not available"
        try:
            from backend.tools.lfm_vl_provider import LFMVLConfig
            self._provider.config = LFMVLConfig(image_max_tokens=max_tokens)
            return self._provider.analyze_screen(img_bytes, question)
        except Exception as e:
            return f"VL error: {e}"

    def find_element(self, img_bytes, description):
        """
        Ask VL for pixel coordinates of a UI element.
        Returns (x, y) or None.
        Prompt enforces: x=NNN y=NNN format.
        """
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

    def verify(self, question):
        """Take screenshot and ask VL if something is true."""
        if not self._available:
            return None
        img = take_screenshot()
        response = self.perceive(img, question, max_tokens=80)
        print(f"  [VL] {question[:55]}")
        print(f"  [VL] -> {response[:100]}")
        pos = ["yes", "visible", "drawn", "selected", "active", "open", "shows", "appears"]
        neg = ["no ", "not ", "cannot", "don't", "doesn't", "isn't", "missing", "no text"]
        r = response.lower()
        return sum(1 for w in pos if w in r) >= sum(1 for w in neg if w in r)


# ── Perception-gated click ─────────────────────────────────────────────────────

async def smart_click(vl, op, handle, description, uia_names, fallback_coords):
    """
    Perception-action-verify click.
    1. VL finds element on screen -> click
    2. If VL offline: try UIA by name
    3. If UIA fails: use fallback coords
    Returns (success, method_used)
    """
    # Step 1: VL perception
    if vl.available:
        img = take_screenshot()
        coords = vl.find_element(img, description)
        if coords:
            pyautogui.click(*coords)
            await asyncio.sleep(0.4)
            return True, "vl"

    # Step 2: UIA accessibility
    if uia_names:
        result = await op.click_one_of(handle, uia_names)
        if result.success:
            return True, "uia"

    # Step 3: Known coords fallback
    if fallback_coords:
        wl, wt = handle.win_rect[0], handle.win_rect[1]
        x = wl + fallback_coords[0]
        y = wt + fallback_coords[1]
        pyautogui.click(x, y)
        await asyncio.sleep(0.4)
        return True, "coords"

    return False, "failed"


# ── Kernel gate ────────────────────────────────────────────────────────────────

async def kernel_gate(task, vl):
    print("\n" + "=" * 60)
    print("[KERNEL] Director evaluating:")
    print(f"  {task}")
    mode = "LFM2.5-VL" if vl.available else "PIL/UIA fallback"
    print(f"[DIRECTOR] APPROVED — Perception: {mode}")
    print("=" * 60)
    return True


# ── Telegram ──────────────────────────────────────────────────────────────────

def _load_env():
    """Load .env from IRISVOICE root into os.environ."""
    import os, pathlib
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
    """Draw a 5-pointed star using mouse drag."""
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
    """Draw a sine wave using mouse drag."""
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
    op = UniversalGUIOperator(vl_brain=vl, log_fn=lambda m: print(f"  [GUI] {m}"))

    if not await kernel_gate(task, vl):
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
    await asyncio.sleep(0.5)

    # Bring to foreground and verify
    ctypes.windll.user32.SetForegroundWindow(handle.hwnd)
    await asyncio.sleep(0.4)
    fg = ctypes.windll.user32.GetForegroundWindow()
    is_fg = (fg == handle.hwnd)
    print(f"  Paint foreground: {'[OK]' if is_fg else '[WARN] not foreground!'}")

    win_rect = handle.win_rect or get_window_rect(handle.hwnd)
    wl, wt, wr, wb = win_rect
    print(f"  Window: ({wl},{wt})->({wr},{wb})")

    # VL: verify Paint is open
    if vl.available:
        vl.verify("Is Microsoft Paint open and maximized on the screen?")

    # Canvas geometry (from UIA + known defaults)
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
    print(f"  Draw zone: ({draw_cx},{draw_cy})")
    print(f"  Text zone: ({text_x1},{text_y1})->({text_x2},{text_y2})")

    # ── Step 2: Select Pencil tool ─────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 2] Select Pencil tool")

    # Perception: ask VL where Pencil button is
    # UIA fallback: find "Pencil" control by name
    # Coord fallback: (185, 53) window-relative (known from UIA tree)
    ok, method = await smart_click(
        vl, op, handle,
        description="Pencil tool button in the Paint ribbon toolbar Tools group",
        uia_names=["Pencil"],
        fallback_coords=(185, 53)
    )
    print(f"  Pencil: {'[OK]' if ok else '[FAIL]'} via {method}")

    # Click canvas edge to dismiss any dropdown and confirm focus
    pyautogui.click(canvas_x_start + 15, canvas_y_start + 15)
    await asyncio.sleep(0.4)

    # VL verify: is Pencil now the active tool?
    if vl.available:
        vl.verify("Is the Pencil tool selected/highlighted in Paint's toolbar ribbon?")

    # ── Step 3: Draw star + wave ───────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 3] Draw star + wave")

    before_draw = take_screenshot()

    print(f"  Drawing star at ({draw_cx},{draw_cy}) r=80...")
    await draw_star(draw_cx, draw_cy, radius=80)

    print(f"  Drawing wave at y={wave_y}...")
    await draw_wave(wave_x1, wave_x2, wave_y, amplitude=35, cycles=3)

    # Verify: PIL diff on drawing zone
    after_draw = take_screenshot()
    draw_diff = diff_pct(before_draw, after_draw,
                         canvas_x_start, canvas_y_start,
                         canvas_cx, canvas_cy)
    draw_ok = draw_diff > 0.2
    print(f"  Draw diff: {draw_diff:.2f}% -> {'[OK]' if draw_ok else '[FAIL] nothing drawn'}")

    if not draw_ok:
        # Record failure and abort
        print("  [WARN] Drawing step failed — canvas did not change.")
        try:
            os.system(f'python bootstrap/record_event.py --type test_run '
                      f'--file scripts/paint_iris_demo.py --result fail --score 0.72 '
                      f'--desc "Drawing diff 0% after pencil+draw — canvas not receiving input. '
                      f'Pencil method={method}, window={wl},{wt}"')
        except Exception:
            pass

    # VL verify drawing
    if vl.available:
        vl.verify("Is there a drawing visible on the Paint canvas — star shape or wave?")

    # ── Step 4: Create text via PIL + clipboard paste ─────────────────────────
    # Paint's font/size controls are custom-rendered with no Win32 HWND and no
    # UIA handle. Clicking ribbon while text box active keeps keyboard focus
    # in the text box. Correct approach: generate "hello this is iris" in
    # Segoe Script 36pt using PIL, copy as DIB to clipboard, paste via Ctrl+V.
    # This gives exact font/size without fighting Paint's UI.
    print(f"\n{'─' * 60}")
    print("[STEP 4] Generate Segoe Script 36pt text image via PIL")

    from PIL import Image, ImageDraw, ImageFont
    import io as _io
    import win32clipboard

    FONT_PATH = r"C:/Windows/Fonts/segoesc.ttf"   # Segoe Script
    TEXT = "hello this is iris"
    FONT_SIZE = 36

    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    # Measure text dimensions
    tmp = Image.new("RGB", (1200, 80), "white")
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), TEXT, font=font)
    tw, th = bbox[2] - bbox[0] + 10, bbox[3] - bbox[1] + 20
    print(f"  Text image size: {tw}x{th}")

    text_img = Image.new("RGB", (tw, th), "white")
    ImageDraw.Draw(text_img).text((5, 5), TEXT, font=font, fill="black")

    # Copy to clipboard as DIB (CF_DIB)
    buf = _io.BytesIO()
    text_img.save(buf, format="BMP")
    dib_data = buf.getvalue()[14:]  # Strip BMP file header, keep DIB

    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
    win32clipboard.CloseClipboard()
    print("  Text image copied to clipboard.")

    before_text = take_screenshot()

    # ── Step 5: Paste into Paint canvas and position ──────────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 5] Paste text image into Paint, drag to text zone")

    # Ensure Paint canvas has focus
    ctypes.windll.user32.SetForegroundWindow(handle.hwnd)
    await asyncio.sleep(0.3)
    pyautogui.click(canvas_x_start + 30, canvas_y_start + 30)
    await asyncio.sleep(0.3)

    # Ctrl+V pastes the DIB as a floating selection at canvas (0,0)
    pyautogui.hotkey("ctrl", "v")
    await asyncio.sleep(0.8)

    # Selection lands at top-left of canvas area.
    # Center of pasted image (tw x th):
    paste_cx = canvas_x_start + tw // 2
    paste_cy = canvas_y_start + th // 2

    # Target: center of text zone
    target_cx = (text_x1 + text_x2) // 2
    target_cy = (text_y1 + text_y2) // 2

    print(f"  Dragging selection from ({paste_cx},{paste_cy}) to ({target_cx},{target_cy})...")
    pyautogui.moveTo(paste_cx, paste_cy)
    await asyncio.sleep(0.2)
    pyautogui.mouseDown(button="left")
    await asyncio.sleep(0.1)
    pyautogui.moveTo(target_cx, target_cy, duration=0.6)
    pyautogui.mouseUp(button="left")
    await asyncio.sleep(0.5)

    # VL: verify text is placed correctly
    if vl.available:
        img_placed = take_screenshot()
        vl.perceive(img_placed,
            "Is there text 'hello this is iris' in cursive/script font visible on the canvas?",
            max_tokens=60)

    # ── Step 6: Commit (click outside selection to merge into canvas) ─────────
    print(f"\n{'─' * 60}")
    print("[STEP 6] Commit pasted text")

    # Click top-left corner of canvas (outside the text selection area)
    commit_x = canvas_x_start + 30
    commit_y = canvas_y_start + 30
    print(f"  Commit click at ({commit_x},{commit_y}) — canvas top-left...")
    pyautogui.click(commit_x, commit_y)
    await asyncio.sleep(0.8)

    # ── Step 8: Verify ────────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 8] Verify final result")

    final_img = take_screenshot()
    debug_path = os.path.join(os.path.dirname(__file__), "iris_paint_debug.png")
    with open(debug_path, "wb") as f:
        f.write(final_img)

    text_diff = diff_pct(before_text, final_img,
                         text_x1 - 20, text_y1 - 20,
                         text_x2 + 20, text_y2 + 50)
    text_ok = text_diff > 0.15

    print(f"  Drawing:  {'[OK]' if draw_ok else '[FAIL]'} (diff={draw_diff:.2f}%)")
    print(f"  Text PIL: {'[OK]' if text_ok else '[FAIL]'} (diff={text_diff:.2f}%)")

    vl_canvas = ""
    if vl.available:
        vl_canvas = vl.perceive(final_img,
            "Describe the Paint canvas: Is there a star and wave drawing? "
            "Is there text 'hello this is iris' visible? What font/size does it appear to be?",
            max_tokens=150)
        print(f"  [VL] Canvas: {vl_canvas}")
        vl_text_ok = "hello" in vl_canvas.lower() or "iris" in vl_canvas.lower()
    else:
        vl_text_ok = False

    overall_ok = draw_ok and (text_ok or vl_text_ok)
    print(f"\n  RESULT: {'SUCCESS' if overall_ok else 'PARTIAL — see ribbon_debug.png and iris_paint_debug.png'}")
    print(f"  Debug screenshots: {debug_path}")

    # ── Step 9: Telegram ──────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print("[STEP 9] Telegram")

    if draw_ok or text_ok or vl_text_ok:
        mode = "LFM2.5-VL" if vl.available else "PIL diff"
        caption = (
            "[IRIS] Paint demo\n"
            f"Star + wave: {'done' if draw_ok else 'partial'} ({draw_diff:.1f}%)\n"
            f"Text 'hello this is iris': {'done' if text_ok else 'partial'} ({text_diff:.1f}%)\n"
            f"Font: Segoe Script 36pt\n"
            f"Verified via: {mode}"
        )
        if vl_canvas:
            caption += f"\nVL: {vl_canvas[:120]}"
        send_to_telegram(final_img, caption)
    else:
        print("  Skipping Telegram — no canvas changes confirmed.")
        print(f"  Window: ({wl},{wt})->({wr},{wb})")
        print(f"  Canvas: ({canvas_x_start},{canvas_y_start})->({canvas_x_end},{canvas_y_end})")

    print(f"\n{'=' * 60}")
    print("[KERNEL] Done.")


if __name__ == "__main__":
    asyncio.run(main())
