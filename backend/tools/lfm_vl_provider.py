"""
LFM2.5-VL Vision Provider
HTTP client wrapping llama-server on port 8081.
Provides synchronous screen analysis, UI element detection, OCR, and action suggestion.

Auto-start: If llama-server is not running on port 8081, the provider attempts to
spawn it using the LFM2.5-VL-450M GGUF model found in ~/models/LFM2.5-VL-450M/.
"""
import base64
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class LFMVLConfig:
    """Configuration for LFM2.5-VL vision provider."""
    base_url: str = "http://localhost:8081/v1"
    temperature: float = 0.1
    min_p: float = 0.15
    repetition_penalty: float = 1.05
    image_max_tokens: int = 128  # 64 for speed, 256 for detail
    timeout: float = 30.0


def _find_vision_model() -> Optional[Tuple[str, str]]:
    """
    Find the LFM2.5-VL-450M GGUF model + mmproj files.
    Searches the same directory LocalModelManager uses for brain models
    (IRIS_MODELS_DIR env var → ~/.lmstudio/models → project root models/gguf).
    This avoids duplicating models across different paths.
    Returns (model_path, mmproj_path) or None if not found.
    """
    # Resolve project root from this file's location: backend/tools/ -> project root
    project_root = Path(__file__).resolve().parents[2]

    # Import LocalModelManager to reuse its MODELS_DIR resolution
    try:
        from backend.agent.local_model_manager import LocalModelManager
        lm_models_dir = LocalModelManager.MODELS_DIR
    except Exception:
        lm_models_dir = None

    search_dirs = [
        # Dedicated vision subdir inside the shared models dir
        lm_models_dir / "LFM2.5-VL-450M" if lm_models_dir else None,
        # LM Studio nests models as author/repo-name/ — scan for it
        lm_models_dir / "LiquidAI" / "LFM2.5-VL-450M-GGUF" if lm_models_dir else None,
        # Fallback paths
        project_root / "models" / "LFM2.5-VL-450M",
        Path.home() / "models" / "LFM2.5-VL-450M",
        Path.home() / ".iris" / "models" / "LFM2.5-VL-450M",
    ]

    for d in search_dirs:
        if d is None or not d.exists():
            continue
        ggufs = list(d.glob("*.gguf"))
        mmproj = list(d.glob("mmproj*.gguf"))
        if ggufs and mmproj:
            return str(ggufs[0]), str(mmproj[0])

    # Last resort: recursive scan of the shared models dir for any dir
    # containing both a .gguf and mmproj*.gguf (catches arbitrary nesting)
    if lm_models_dir and lm_models_dir.exists():
        for d in lm_models_dir.rglob("*/"):
            ggufs = list(d.glob("*.gguf"))
            mmproj = list(d.glob("mmproj*.gguf"))
            if ggufs and mmproj:
                # Verify it's actually the vision model by checking the stem
                if any("LFM2.5-VL" in g.name for g in ggufs):
                    return str(ggufs[0]), str(mmproj[0])

    return None


def _find_llama_server_binary() -> Optional[str]:
    """
    Find llama-server binary for the vision model.

    Priority: upstream ggml-org/llama.cpp (supports LFM2/LFM2-VL)
             → LocalModelManager discovery (ik_llama.cpp, PATH, etc.)
             → basic PATH search

    We prefer upstream llama.cpp for vision because ik_llama.cpp
    (Kimi-K2 fork) does not support the LFM2 model architecture.
    Brain models on port 8082 continue to use whatever binary
    LocalModelManager resolves (ik_llama.cpp for Kimi-K2).
    """
    # 1. Prefer upstream llama.cpp which supports LFM2/LFM2-VL
    upstream = Path.home() / "llama.cpp-upstream" / "llama-server"
    if upstream.exists():
        return str(upstream)

    # 2. Reuse LocalModelManager discovery
    try:
        from backend.agent.local_model_manager import LocalModelManager
        return LocalModelManager._find_llama_server_binary()
    except Exception:
        pass

    # 3. Fallback: basic PATH search
    import shutil
    found = shutil.which("llama-server")
    if found:
        return found
    return None


def _ensure_vision_server_running(base_url: str = "http://localhost:8081") -> bool:
    """
    Check if llama-server is running. If not, try to spawn it.
    Returns True if server is reachable (either already running or successfully started).
    """
    try:
        import httpx
        r = httpx.get(f"{base_url}/v1/models", timeout=2.0)
        if r.status_code == 200:
            return True
    except Exception:
        pass

    # Not running — try to auto-start
    logger.info("[LFMVLProvider] Vision server not running on port 8081. Attempting auto-start...")

    model_files = _find_vision_model()
    if not model_files:
        logger.warning("[LFMVLProvider] Vision model not found. Run: python scripts/models/download_vision_model.py")
        return False

    binary = _find_llama_server_binary()
    if not binary:
        logger.warning("[LFMVLProvider] llama-server binary not found in PATH. Install llama.cpp or set PATH.")
        return False

    model_path, mmproj_path = model_files
    cmd = [
        binary,
        "-m", model_path,
        "--mmproj", mmproj_path,
        "--port", "8081",
        "--host", "127.0.0.1",
        "-c", "4096",
        "-np", "1",
        "-n", "512",
        "--no-warmup",  # Prevents crash with upstream llama.cpp on WSL
    ]

    # If using the upstream binary, it needs its shared libraries in LD_LIBRARY_PATH
    env = os.environ.copy()
    binary_path = Path(binary)
    if "llama.cpp-upstream" in str(binary_path):
        env["LD_LIBRARY_PATH"] = str(binary_path.parent) + ":" + env.get("LD_LIBRARY_PATH", "")

    logger.info(f"[LFMVLProvider] Spawning vision server: {' '.join(cmd)}")
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent
            env=env,
        )
        # Wait up to 30s for server to be ready
        for _ in range(60):
            time.sleep(0.5)
            try:
                r = httpx.get(f"{base_url}/v1/models", timeout=1.0)
                if r.status_code == 200:
                    logger.info("[LFMVLProvider] Vision server ready.")
                    return True
            except Exception:
                pass
        logger.warning("[LFMVLProvider] Vision server did not become ready within 30s.")
        return False
    except Exception as e:
        logger.warning(f"[LFMVLProvider] Failed to spawn vision server: {e}")
        return False


def screenshot_to_bytes(region: Optional[Tuple[int, int, int, int]] = None) -> bytes:
    """
    Capture screen and return as PNG bytes.
    Uses mss for cross-platform support. Latency: <5ms.

    Args:
        region: Optional (left, top, width, height) bounding box.

    Returns:
        PNG bytes of the screenshot.
    """
    import mss
    import mss.tools

    with mss.mss() as sct:
        if region:
            left, top, width, height = region
            monitor = {"left": left, "top": top, "width": width, "height": height}
        else:
            monitor = sct.monitors[1]  # Primary monitor

        sct_img = sct.grab(monitor)
        return mss.tools.to_png(sct_img.rgb, sct_img.size)


def _img_to_base64(img_bytes: bytes) -> str:
    """Convert PNG bytes to base64 string."""
    return base64.b64encode(img_bytes).decode("utf-8")


class LFMVLProvider:
    """
    Synchronous HTTP client for LFM2.5-VL vision model via llama-server.

    Design principles:
    - No state held between calls
    - Every call is independent (screenshot, query, response)
    - All methods return strings/dicts — never raise on failure
    - Uses httpx for sync HTTP requests

    Sampling (Liquid AI official recommendations):
    - temperature: 0.1   (deterministic outputs)
    - min_p: 0.15        (nucleus sampling threshold)
    - repetition_penalty: 1.05 (prevent repetition)
    """

    def __init__(self, config: Optional[LFMVLConfig] = None):
        self.config = config or LFMVLConfig()

    def _call(self, img_bytes: bytes, prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        Send image + prompt to llama-server /v1/chat/completions.
        Auto-starts the vision server if not already running.
        Returns model response text, or error string on any failure.
        """
        # Ensure server is running before first call
        _ensure_vision_server_running(self.config.base_url)

        try:
            import httpx

            img_b64 = _img_to_base64(img_bytes)
            tokens = max_tokens or self.config.image_max_tokens

            payload = {
                "model": "lfm2.5-vl",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{img_b64}"}
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ],
                "temperature": self.config.temperature,
                "min_p": self.config.min_p,
                "repetition_penalty": self.config.repetition_penalty,
                "max_tokens": tokens,
            }

            response = httpx.post(
                f"{self.config.base_url}/chat/completions",
                json=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            logger.warning(f"[LFMVLProvider] Call failed: {e}")
            return f"Vision unavailable: {e}"

    def health_check(self) -> bool:
        """
        Check if llama-server is reachable and has a vision model loaded.
        Returns True if server responds, False otherwise.
        """
        try:
            import httpx
            response = httpx.get(
                f"{self.config.base_url}/models",
                timeout=5.0
            )
            return response.status_code == 200
        except Exception:
            return False

    def analyze_screen(self, img_bytes: bytes, question: str = "") -> str:
        """
        Analyze screen content and answer a question about it.

        Args:
            img_bytes: PNG screenshot bytes
            question: Optional specific question about the screen

        Returns:
            Text description of screen content.
        """
        prompt = question if question else "Describe what is visible on this screen in detail."
        return self._call(img_bytes, prompt, max_tokens=256)

    def find_ui_element(self, img_bytes: bytes, description: str) -> dict:
        """
        Locate a UI element on screen by description.

        Args:
            img_bytes: PNG screenshot bytes
            description: Natural language description of the element

        Returns:
            {"found": bool, "location_hint": str}
        """
        prompt = (
            f'Find the UI element described as: "{description}". '
            "Describe where it is located on screen (top-left, center, bottom-right, etc.) "
            "and whether it is visible. Keep response brief."
        )
        response = self._call(img_bytes, prompt, max_tokens=64)

        if response.startswith("Vision unavailable"):
            return {"found": False, "location_hint": response}

        found = not any(
            word in response.lower()
            for word in ["not found", "not visible", "cannot find", "don't see", "no such"]
        )
        return {"found": found, "location_hint": response}

    def read_text(self, img_bytes: bytes, region: Optional[Tuple] = None) -> str:
        """
        Extract text from screen or a specific region.

        Args:
            img_bytes: PNG screenshot bytes
            region: Optional region description hint

        Returns:
            Extracted text string.
        """
        hint = f" Focus on: {region}." if region else ""
        prompt = f"Extract all readable text from this screenshot.{hint} Return only the text content, no commentary."
        return self._call(img_bytes, prompt, max_tokens=256)

    def suggest_action(self, img_bytes: bytes, goal: str) -> dict:
        """
        Suggest the next UI action to achieve a goal.

        Args:
            img_bytes: PNG screenshot bytes
            goal: What the user wants to accomplish

        Returns:
            {"action": str, "target": str, "reasoning": str}
        """
        prompt = (
            f'Goal: "{goal}". '
            "Looking at the current screen, what is the single best next action? "
            "Reply with: ACTION: [click/type/scroll/wait], TARGET: [what to interact with], REASON: [brief reason]."
        )
        response = self._call(img_bytes, prompt, max_tokens=128)

        if response.startswith("Vision unavailable"):
            return {"action": "error", "target": "", "reasoning": response}

        # Parse structured response
        result = {"action": "unknown", "target": "", "reasoning": response}
        for line in response.splitlines():
            line_lower = line.lower()
            if line_lower.startswith("action:"):
                result["action"] = line.split(":", 1)[1].strip().lower()
            elif line_lower.startswith("target:"):
                result["target"] = line.split(":", 1)[1].strip()
            elif line_lower.startswith("reason:"):
                result["reasoning"] = line.split(":", 1)[1].strip()

        return result

    def describe_live_frame(self, img_bytes: bytes) -> str:
        """
        Fast single-sentence description for streaming/monitoring.
        Uses minimum tokens for speed.

        Args:
            img_bytes: PNG screenshot bytes

        Returns:
            Single sentence describing the screen.
        """
        prompt = "In one sentence, what is happening on this screen right now?"
        return self._call(img_bytes, prompt, max_tokens=64)
