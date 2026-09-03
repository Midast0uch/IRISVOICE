"""Contract test CT-I1: exactly one TaskListCard render site (REQ-1 AC2).

Decision Locked #1 (Phase 2): one task card, always — no fallback card type,
no second component. If a second `<TaskListCard` render site appears anywhere
under components/, a competing card can exist and REQ-1 AC2 ("no second card
component and no fallback card SHALL exist") is broken structurally, not just
behaviorally.

Asserts the EFFECT (how many places in the real source tree instantiate the
component), not the computation — this is a source-tree pin, not a render
snapshot, because the whole point is that there is nowhere else to build a
second card.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
COMPONENTS_DIR = ROOT / "components"


def _render_sites() -> list[str]:
    sites = []
    for f in COMPONENTS_DIR.rglob("*.tsx"):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if "<TaskListCard" in text:
            sites.append(str(f.relative_to(ROOT)))
    return sites


class TestOneTaskCardRenderSite:
    def test_exactly_one_render_site_exists(self):
        sites = _render_sites()
        assert len(sites) == 1, (
            f"expected exactly one <TaskListCard render site, found {len(sites)}: "
            f"{sites} — a second site means a competing/fallback card exists (REQ-1 AC2)"
        )

    def test_the_one_render_site_is_chat_view(self):
        """Pins WHERE the single site lives, so a future refactor that silently
        moves it to a new fallback component is caught, not just the count."""
        sites = _render_sites()
        assert len(sites) == 1
        assert Path(sites[0]) == Path("components/chat-view.tsx"), (
            f"unexpected render site location: {sites}"
        )
