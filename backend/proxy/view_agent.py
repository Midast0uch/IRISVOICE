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

# Thin glass scrollbar injected into EVERY served page (capture + proxy) so
# the iframe's internal scrollbar matches the dashboard wing's summary-tab
# scrollbar (dark-glass-dashboard.tsx .browser-summary-scroll: 4px, 2px
# radius, white/5 track, white/20 thumb, white/30 hover). Without this the
# iframe showed the native Windows scrollbar (~17px) — thick and inconsistent
# with the 4px bars everywhere else (2026-08-12). `::-webkit-scrollbar` on
# :root styles the DOCUMENT scrollbar, which is the one the iframe shows for
# its own page; Firefox picks up scrollbar-color. The response CSP allows
# style-src 'unsafe-inline', so this inline <style> is permitted.
_VIEW_SCROLLBAR_STYLE = (
    "<!-- " + _MARKER + ":scrollbar -->\n"
    "<style>\n"
    "html::-webkit-scrollbar, body::-webkit-scrollbar { width: 4px; height: 4px; }\n"
    "html::-webkit-scrollbar-track, body::-webkit-scrollbar-track {\n"
    "  background: rgba(255,255,255,0.05); border-radius: 2px;\n"
    "}\n"
    "html::-webkit-scrollbar-thumb, body::-webkit-scrollbar-thumb {\n"
    "  background: rgba(255,255,255,0.2); border-radius: 2px;\n"
    "}\n"
    "html::-webkit-scrollbar-thumb:hover, body::-webkit-scrollbar-thumb:hover {\n"
    "  background: rgba(255,255,255,0.3);\n"
    "}\n"
    "html { scrollbar-color: rgba(255,255,255,0.2) rgba(255,255,255,0.05); }\n"
    "</style>\n"
)

# Fit the served page to the iframe's width instead of letting it lay out at a
# desktop width and hide most of itself behind a horizontal scrollbar. The
# browser panel is a narrow column, and pages built for ~1280px rendered at
# their own scale showed a sliver of content (2026-08-12 user report: "the page
# should shrink down to fit so more is visible").
#
# Two mechanisms, because one alone is not enough:
#   * a viewport meta so responsive pages pick their MOBILE layout — this is what
#     makes a modern page genuinely readable in a narrow frame, rather than a
#     shrunken desktop layout with 6px text;
#   * defensive max-width caps so a fixed-width page (a wide table, an oversized
#     image) is bounded by the frame instead of forcing a horizontal scroll.
# `zoom` deliberately is NOT used: it breaks the coordinate frame the vision
# cursor and the view-agent's scroll reports share, so a shrunken page would be
# clicked in the wrong place.
_VIEW_FIT_STYLE = (
    "<!-- " + _MARKER + ":fit -->\n"
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<style>\n"
    "html, body { max-width: 100% !important; overflow-x: hidden !important; }\n"
    "img, video, canvas, svg, iframe, embed, object {\n"
    "  max-width: 100% !important; height: auto;\n"
    "}\n"
    "table, pre { max-width: 100% !important; }\n"
    "pre { white-space: pre-wrap; word-break: break-word; }\n"
    "table { display: block; overflow-x: auto; }\n"
    "</style>\n"
)

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
    # Thin scrollbar style rides with the agent so every served page (capture
    # and proxy alike) gets the SAME 4px glass scrollbar as the dashboard
    # summary tab — consistency across both iframe surfaces (2026-08-12).
    # Fit rules come FIRST so a page carrying its own viewport meta is
    # overridden by ours (the last viewport meta in the document wins) and so
    # the !important caps sit after the page's own stylesheets.
    injected = _VIEW_FIT_STYLE + _VIEW_SCROLLBAR_STYLE + script
    # </body> lives at the END of the document. Scanning the first 8 KB found
    # it only on tiny pages; every real page fell through to the append branch
    # and landed the script after </html>. Scan the TAIL instead.
    tail_start = max(0, len(html_str) - 8192)
    body_idx = html_str[tail_start:].lower().rfind("</body>")
    if body_idx != -1:
        cut = tail_start + body_idx
        return html_str[:cut] + injected + html_str[cut:]
    return html_str + injected
