"""
UniversalGUIOperator — Control any Windows application reliably.

Priority chain for finding/clicking controls:
  1. UIA accessibility (pywinauto) — finds buttons BY NAME, no coordinates
  2. VL model coordinate prediction  — screenshot + natural language query
  3. PIL fallback verification        — pixel diff before/after

This works with ANY Windows app: Paint, Notepad, Chrome, Office, etc.
No application-specific coordinate hardcoding.
"""

import asyncio
import ctypes
import ctypes.wintypes
import io
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ActionResult:
    success: bool
    method: str          # "uia", "vl", "pil_fallback", "error"
    message: str = ""
    coords: Optional[Tuple[int, int]] = None


@dataclass
class AppHandle:
    process: Any         # subprocess.Popen or None
    hwnd: Optional[int]
    title: str
    uia_app: Any = None  # pywinauto Application object
    win_rect: Optional[Tuple[int, int, int, int]] = None  # (left,top,right,bottom)


# ── Screenshot helpers ────────────────────────────────────────────────────────

def take_screenshot() -> bytes:
    import mss, mss.tools
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        return mss.tools.to_png(shot.rgb, shot.size)


def diff_pct(before: bytes, after: bytes,
             x1: int, y1: int, x2: int, y2: int) -> float:
    from PIL import Image
    def crop(b):
        return Image.open(io.BytesIO(b)).convert("RGB").crop((x1, y1, x2, y2))
    bp = list(crop(before).getdata())
    ap = list(crop(after).getdata())
    if not bp:
        return 0.0
    changed = sum(1 for b, a in zip(bp, ap)
                  if abs(b[0]-a[0]) + abs(b[1]-a[1]) + abs(b[2]-a[2]) > 25)
    return (changed / len(bp)) * 100.0


# ── Win32 helpers ─────────────────────────────────────────────────────────────

def find_hwnd(title_fragment: str) -> Optional[int]:
    found = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _):
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            n = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_fragment.lower() in buf.value.lower():
                found.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(CB(cb), 0)
    return found[0] if found else None


def get_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def is_process_running(exe_name: str) -> bool:
    try:
        r = subprocess.run(["tasklist", "/fi", f"imagename eq {exe_name}"],
                           capture_output=True, text=True, timeout=5)
        return exe_name.lower() in r.stdout.lower()
    except Exception:
        return False


# ── Universal GUI Operator ────────────────────────────────────────────────────

class UniversalGUIOperator:
    """
    Operate any Windows application without hardcoded coordinates.

    Usage:
        op = UniversalGUIOperator(vl_brain=VisionBrain())
        handle = await op.open("mspaint.exe", title_fragment="Paint")
        await op.maximize(handle)
        await op.click_control(handle, "Text")          # UIA by name
        await op.type_into(handle, "Font", "Segoe Script")
        await op.drag(handle, x1,y1, x2,y2)            # canvas operations
        await op.type_text("hello this is iris")
        verified = await op.verify_screen_changed(before_bytes, handle)
    """

    def __init__(self, vl_brain=None, log_fn=None):
        self.vl = vl_brain
        self._log = log_fn or (lambda msg: print(f"  [GUI] {msg}"))

    # ── App lifecycle ──────────────────────────────────────────────────────────

    async def open(self, exe_or_cmd: str, title_fragment: str,
                   wait_sec: float = 4.0) -> AppHandle:
        """
        Launch an application and return an AppHandle.
        If already running, connects to existing instance.
        """
        if not is_process_running(exe_or_cmd.split("/")[-1].split("\\")[-1]):
            self._log(f"Launching: {exe_or_cmd}")
            proc = subprocess.Popen(exe_or_cmd, shell=True)
            await asyncio.sleep(wait_sec)
        else:
            self._log(f"Already running: {exe_or_cmd}")
            proc = None

        # Find window
        hwnd = None
        for _ in range(8):
            hwnd = find_hwnd(title_fragment)
            if hwnd:
                break
            await asyncio.sleep(0.8)

        if not hwnd:
            return AppHandle(process=proc, hwnd=None, title=title_fragment)

        # Connect pywinauto
        uia_app = None
        try:
            from pywinauto import Application
            uia_app = Application(backend="uia").connect(handle=hwnd)
        except Exception as e:
            self._log(f"pywinauto UIA connect failed: {e}")

        handle = AppHandle(
            process=proc,
            hwnd=hwnd,
            title=title_fragment,
            uia_app=uia_app,
        )
        return handle

    async def maximize(self, handle: AppHandle) -> ActionResult:
        """Maximize the application window."""
        if not handle.hwnd:
            return ActionResult(False, "error", "No hwnd")

        # Method 1: Win32 SW_MAXIMIZE
        ctypes.windll.user32.ShowWindow(handle.hwnd, 3)
        ctypes.windll.user32.SetForegroundWindow(handle.hwnd)
        await asyncio.sleep(0.3)

        # Method 2: pywinauto maximize
        if handle.uia_app:
            try:
                handle.uia_app.top_window().maximize()
                await asyncio.sleep(0.2)
            except Exception:
                pass

        # Method 3: Win+Up keyboard
        import pyautogui
        pyautogui.hotkey("win", "up")
        await asyncio.sleep(0.5)

        # Read and store final rect
        rect = get_window_rect(handle.hwnd)
        handle.win_rect = rect
        sw = pyautogui.size()[0]
        w = rect[2] - rect[0]
        self._log(f"Window {rect} = {w}px wide (screen={sw})")

        return ActionResult(True, "win32",
                            f"rect={rect}, width={w}")

    def _get_uia_window(self, handle: AppHandle):
        """Get the pywinauto window wrapper."""
        if not handle.uia_app:
            return None
        try:
            return handle.uia_app.top_window()
        except Exception:
            return None

    def dump_controls(self, handle: AppHandle) -> str:
        """Dump UIA control tree for debugging."""
        win = self._get_uia_window(handle)
        if not win:
            return "No UIA window"
        try:
            import io as _io
            from contextlib import redirect_stdout
            buf = _io.StringIO()
            with redirect_stdout(buf):
                win.print_control_identifiers(depth=4)
            return buf.getvalue()[:3000]  # first 3000 chars
        except Exception as e:
            return f"dump_controls error: {e}"

    # ── Control interaction (UIA → VL fallback) ───────────────────────────────

    async def click_control(self, handle: AppHandle, control_name: str,
                             control_type: str = "Button") -> ActionResult:
        """
        Click a control by its name/text using UIA accessibility.
        Falls back to VL coordinate prediction if UIA fails.
        """
        # ── Attempt 1: UIA direct ─────────────────────────────────────────────
        win = self._get_uia_window(handle)
        if win:
            # Try common ways pywinauto exposes a named control
            for selector in [
                lambda: win[control_name].click_input(),
                lambda: win.child_window(title=control_name, control_type=control_type).click_input(),
                lambda: win.child_window(title_re=f".*{control_name}.*").click_input(),
                lambda: win.child_window(auto_id=control_name).click_input(),
            ]:
                try:
                    selector()
                    await asyncio.sleep(0.4)
                    self._log(f"[UIA] Clicked '{control_name}'")
                    return ActionResult(True, "uia", f"clicked '{control_name}'")
                except Exception:
                    pass

        self._log(f"[UIA] '{control_name}' not found in accessibility tree")

        # ── Attempt 2: VL coordinate prediction ──────────────────────────────
        if self.vl and self.vl.available and handle.win_rect:
            img = take_screenshot()
            win_left, win_top = handle.win_rect[0], handle.win_rect[1]
            coords = self.vl.suggest_click_coords(img, control_name, win_left, win_top)
            if coords:
                import pyautogui
                before = take_screenshot()
                pyautogui.click(*coords)
                await asyncio.sleep(0.5)
                return ActionResult(True, "vl", f"VL click at {coords}", coords)

        return ActionResult(False, "error", f"Could not locate '{control_name}'")

    async def type_into(self, handle: AppHandle, field_name: str,
                         text: str) -> ActionResult:
        """
        Find a text field by name and type into it.
        Uses pywinauto type_keys() exclusively — avoids focus race with pyautogui.
        """
        # ── UIA: find and set value ───────────────────────────────────────────
        win = self._get_uia_window(handle)
        if win:
            for selector in [
                lambda: win.child_window(title=field_name, control_type="Edit"),
                lambda: win.child_window(title_re=f".*{field_name}.*", control_type="Edit"),
                lambda: win[field_name],
            ]:
                try:
                    ctrl = selector()
                    ctrl.set_focus()
                    await asyncio.sleep(0.15)
                    ctrl.click_input()
                    await asyncio.sleep(0.2)
                    # Use pywinauto type_keys — stays on the focused control
                    ctrl.type_keys("^a", with_spaces=True)
                    await asyncio.sleep(0.1)
                    ctrl.type_keys(text, with_spaces=True)
                    await asyncio.sleep(0.1)
                    ctrl.type_keys("{ENTER}")
                    await asyncio.sleep(0.3)
                    self._log(f"[UIA] Typed '{text}' into '{field_name}'")
                    return ActionResult(True, "uia", f"typed into '{field_name}'")
                except Exception:
                    pass

        self._log(f"[UIA] Field '{field_name}' not found")

        # ── VL fallback ───────────────────────────────────────────────────────
        if self.vl and self.vl.available and handle.win_rect:
            img = take_screenshot()
            win_left, win_top = handle.win_rect[0], handle.win_rect[1]
            coords = self.vl.suggest_click_coords(
                img, f"{field_name} text input field", win_left, win_top)
            if coords:
                pyautogui.click(*coords)
                await asyncio.sleep(0.2)
                pyautogui.hotkey("ctrl", "a")
                await asyncio.sleep(0.1)
                pyautogui.write(text, interval=0.04)
                pyautogui.press("enter")
                await asyncio.sleep(0.3)
                return ActionResult(True, "vl", f"VL typed '{text}' at {coords}", coords)

        return ActionResult(False, "error", f"Could not find field '{field_name}'")

    async def click_at(self, x: int, y: int, description: str = "") -> ActionResult:
        """Click at absolute screen coordinates."""
        import pyautogui
        pyautogui.click(x, y)
        await asyncio.sleep(0.3)
        return ActionResult(True, "coords", description or f"clicked ({x},{y})")

    async def drag(self, x1: int, y1: int, x2: int, y2: int,
                   duration: float = 0.5) -> ActionResult:
        """Click-drag from (x1,y1) to (x2,y2)."""
        import pyautogui
        pyautogui.moveTo(x1, y1)
        await asyncio.sleep(0.15)
        pyautogui.mouseDown(button="left")
        await asyncio.sleep(0.1)
        pyautogui.moveTo(x2, y2, duration=duration)
        pyautogui.mouseUp(button="left")
        await asyncio.sleep(0.4)
        return ActionResult(True, "coords", f"drag ({x1},{y1})->({x2},{y2})")

    async def type_text(self, text: str, interval: float = 0.06) -> ActionResult:
        """Type text at current cursor position."""
        import pyautogui
        pyautogui.write(text, interval=interval)
        await asyncio.sleep(0.3)
        return ActionResult(True, "keyboard", f"typed: {text!r}")

    async def hotkey(self, *keys) -> ActionResult:
        """Send a keyboard hotkey."""
        import pyautogui
        pyautogui.hotkey(*keys)
        await asyncio.sleep(0.3)
        return ActionResult(True, "keyboard", f"hotkey: {'+'.join(keys)}")

    # ── Verification ──────────────────────────────────────────────────────────

    async def verify_screen_changed(self, before: bytes,
                                     region: Optional[Tuple] = None,
                                     threshold: float = 1.0) -> Tuple[bool, float]:
        """
        Verify screen changed vs before.
        Returns (changed: bool, diff_pct: float).
        """
        import pyautogui
        after = take_screenshot()
        if region:
            x1, y1, x2, y2 = region
        else:
            sw, sh = pyautogui.size()
            x1, y1, x2, y2 = 0, 0, sw, sh
        pct = diff_pct(before, after, x1, y1, x2, y2)
        return pct >= threshold, pct

    async def vl_verify(self, question: str) -> Optional[bool]:
        """
        Ask VL brain if something is true in the current screen.
        Returns None if VL not available.
        """
        if not self.vl or not self.vl.available:
            return None
        img = take_screenshot()
        return self.vl.verify(img, question)

    async def vl_ask(self, question: str, max_tokens: int = 128) -> str:
        """Ask VL brain a question about current screen."""
        if not self.vl or not self.vl.available:
            return "VL not available"
        img = take_screenshot()
        return self.vl.ask(img, question, max_tokens)

    # ── Convenience: scan for a control by trying multiple names ──────────────

    async def click_one_of(self, handle: AppHandle,
                            candidates: List[str]) -> ActionResult:
        """Try clicking each candidate name until one succeeds."""
        for name in candidates:
            before = take_screenshot()
            result = await self.click_control(handle, name)
            if result.success:
                return result
            # Also check if screen changed (tool might have been activated
            # even if UIA raised an exception on the return path)
            import pyautogui
            sw, sh = pyautogui.size()
            pct = diff_pct(before, take_screenshot(), 0, 0, sw, sh)
            if pct > 1.5:
                self._log(f"Screen changed {pct:.1f}% after clicking '{name}' — treating as success")
                return ActionResult(True, "pil_diff", f"'{name}' caused screen change")
        return ActionResult(False, "error", f"None of {candidates} worked")
