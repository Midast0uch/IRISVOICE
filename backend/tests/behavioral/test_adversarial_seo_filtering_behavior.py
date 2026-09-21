"""BT-9 (vision-goal-directed-search T28, REQ-9): hybrid adversarial SEO and
affiliate filtering — Tier A heuristics drop known-bad URL shape
(affiliate params, redirect paths, spam TLDs) before any fetch spend, Tier B
rejects doorway/parasite pages by content signal, and surviving candidates
are re-ranked toward authoritative sources (manufacturer, docs, primary).

Drives the REAL filter functions in backend/vision/search_discovery.py —
pure modules, no network.
"""
from __future__ import annotations

from backend.vision.search_discovery import (
    filter_adversarial_candidates,
    filter_adversarial_urls,
)


def test_tier_a_rejects_affiliate_params_and_redirect_paths():
    out = filter_adversarial_urls([
        "https://shop.example/p?aff_id=abc12",
        "https://deals.example/go/?target=merchant",
        "https://link.example/out.php?id=42",
        "https://shop.example/p?tag=ref-20",            # ?tag affiliate param
        "https://good.example/product/rtx5090",          # clean — must survive
    ])
    assert "https://good.example/product/rtx5090" in out
    assert not any(u for u in out if "aff_id=" in u or "/go/" in u or "out.php" in u or "tag=" in u), (
        f"affiliate/redirect shapes survived Tier A: {out}"
    )


def test_tier_b_rejects_parasite_seo_and_keyword_stuffed_doorways():
    """Parasite economics: a coupon aggregator hosting a product 'review' with
    keyword stuffing is exactly the doorway the spec rejects; a stack of
    normal-looking snippets mentioning the keywords passes."""
    out = filter_adversarial_candidates([
        (
            "https://coupons-dairy.example/rtx-5090-review",
            "RTX 5090 review RTX 5090 review RTX 5090 review best RTX 5090",
            "RTX 5090 review RTX 5090 review RTX 5090 review RTX 5090 review RTX 5090 review coupon codes",
        ),
        (
            "https://nvidia.com/products/rtx-5090",
            "GeForce RTX 5090 — NVIDIA",
            "Official product page for the RTX 5090 graphics card.",
        ),
    ])
    assert "https://nvidia.com/products/rtx-5090" in out
    assert "https://coupons-dairy.example/rtx-5090-review" not in out, (
        "coupon-host parasite SEO review survived the Tier B filter"
    )


def test_authority_rerank_prefers_manufacturers_and_primary_sources():
    """AC9.2: the docs.* prefix and the trusted TLDs outrank an ordinary
    storefront; an SEO farm always sorts last."""
    out = filter_adversarial_candidates([
        ("https://scrapedb.example/listing/rtx5090", "RTX 5090", "buy cheap"),
        ("https://techpowerup.com/review/rtx-5090", "RTX 5090 Review", "bench"),
        ("https://docs.nvidia.com/rtx-5090/specs", "RTX 5090 Specs", "official specs"),
    ])
    assert out[0] == "https://docs.nvidia.com/rtx-5090/specs", (
        f"authority re-rank did not put the docs host first: {out}"
    )


def test_legit_content_with_keywords_is_not_falsely_rejected():
    """Regression on the false-positive fix recorded in pin (session 299):
    a technical doc page that natively dominates the query vocabulary must
    survive (keyword density over a LONG text ≠ stuffing)."""
    out = filter_adversarial_candidates([
        (
            "https://docs.python.org/3/whatsnew/3.13.html",
            "What's New in Python 3.13 — release notes",
            ("Python 3.13 removes the GIL, adds a JIT, improves the REPL. "
             "This release of Python changes many internals of the Python "
             "interpreter; the Python steering council documented every "
             "change to the Python language. " * 3),
        ),
        (
            "https://low-quality.example/keyword-farm",
            "python python python python python python",
            "python " * 60,
        ),
    ])
    assert "https://docs.python.org/3/whatsnew/3.13.html" in out, (
        "a real documentation page was false-positive rejected"
    )
    assert "https://low-quality.example/keyword-farm" not in out
