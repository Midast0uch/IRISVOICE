"""View-agent injection for the in-app browser surface (REQ-4, T9).

The parent never reaches into the frame; the child only speaks out. Visibility
is bought with a narrow, validated postMessage protocol — never with origin
access. This module owns the injected script that gives the sandboxed frame a
voice (scroll position, ready signal) and accepts only two commands
(scrollTo / highlight) with fixed shapes.

Protocol (design.md "The view protocol"):
    frame → parent   { __iris: "view", v: 1, kind: "scroll",  top, height, viewport }
    frame → parent   { __iris: "view", v: 1, kind: "ready",   height }
    parent → frame   { __iris: "cmd",  v: 1, kind: "scrollTo",  top, smooth }
    parent → frame   { __iris: "cmd",  v: 1, kind: "highlight", rects: [{x,y,w,h}] }

The frame is sandboxed to an opaque origin, so its postMessage arrives with
origin === "null". The PARENT must validate event.source === contentWindow AND
the shape (REQ-4 AC4) — handled by hooks/useViewProtocol.ts on the frontend.

This script is the DEGRADATION point (REQ-4 AC5): a page that strips scripts or
blocks the injection simply never posts — the parent falls back to the coarse
overlay states. The script itself is written to never throw and to post with
"*" target (the only target an opaque-origin frame may use).
"""

from __future__ import annotations

import html as _html
import re as _re

# A single <script> string, injected before </body> (or appended). Never
# raises: every interaction is wrapped in try/catch and the payload is fixed
# shape, version 1. Commands from the parent are validated by shape only — an
# opaque-origin frame cannot authenticate the sender, and accepting only two
# fixed shapes is the entire blast radius.
_MARKER = "__iris_view_agent_v1__"
VIEW_AGENT_SCRIPT = (
    "<!-- " + _MARKER + " -->\n"
    "(function () {\n"
    '  "use strict";\n'
    "  function post(kind, extra) {\n"
    "    try {\n"
    '      var msg = { __iris: "view", v: 1, kind: kind };\n'
    "      if (extra) { for (var k in extra) { msg[k] = extra[k]; } }\n"
    '      window.parent.postMessage(msg, "*");\n'
    "    } catch (e) { /* never raise */ }\n"
    "  }\n"
    "  function dims() {\n"
    "    var de = document.documentElement;\n"
    "    return {\n"
    "      top: (window.pageYOffset || de.scrollTop || 0),\n"
    "      height: Math.max(de.scrollHeight, document.body ? document.body.scrollHeight : 0),\n"
    "      viewport: window.innerHeight || de.clientHeight || 0\n"
    "    };\n"
    "  }\n"
    "  function ready() {\n"
    "    var d = dims();\n"
    '    post("ready", { height: d.height });\n'
    "  }\n"
    "  function onScroll() {\n"
    "    var d = dims();\n"
    '    post("scroll", d);\n'
    "  }\n"
    "  try {\n"
    '    if (document.readyState === "loading") {\n'
    '      document.addEventListener("DOMContentLoaded", ready, { once: true });\n'
    "    } else {\n"
    "      ready();\n"
    "    }\n"
    '    window.addEventListener("scroll", onScroll, { passive: true });\n'
    '    window.addEventListener("message", function (ev) {\n'
    "      var m = ev.data;\n"
    '      if (!m || m.__iris !== "cmd" || m.v !== 1) { return; }\n'
    '      if (m.kind === "scrollTo" && typeof m.top === "number") {\n'
    '        window.scrollTo({ top: m.top, behavior: m.smooth ? "smooth" : "auto" });\n'
    '      } else if (m.kind === "highlight" && Array.isArray(m.rects)) {\n'
    "        // Fixed shape; a future visual highlight may consume rects.\n"
    "      }\n"
    "    });\n"
    "  } catch (e) { /* never raise */ }\n"
    "})();\n"
)


def inject_view_agent(html_str: str, nonce: str | None = None) -> str:
    """Inject the view-agent script into served HTML (REQ-4 AC1/AC2).

    Idempotent: refuses to double-inject if the marker comment is already
    present (e.g. a page fetched, rewritten, and served twice). Called AFTER
    content-encoding decode and <base> anchoring — it must not corrupt either.

    ``nonce`` MUST match the ``script-src 'nonce-…'`` in the response CSP
    (browser_surface._csp). Without it the script is inert: the served page's
    CSP permits no other script source, which is deliberate — page JavaScript
    never executes, only this agent does.
    """
    if not isinstance(html_str, str) or not html_str:
        return html_str
    if _MARKER in html_str:
        return html_str
    attr = f' nonce="{nonce}"' if nonce else ""
    script = f"<script{attr}>{VIEW_AGENT_SCRIPT}</script>"
    # </body> lives at the END of the document. Scanning the first 8 KB found
    # it only on tiny pages; every real page fell through to the append branch
    # and landed the script after </html>. Scan the TAIL instead.
    tail_start = max(0, len(html_str) - 8192)
    body_idx = html_str[tail_start:].lower().rfind("</body>")
    if body_idx != -1:
        cut = tail_start + body_idx
        return html_str[:cut] + script + html_str[cut:]
    return html_str + script
