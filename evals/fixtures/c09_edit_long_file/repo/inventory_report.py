"""Inventory report helpers.

Each item is a dict with keys such as name, price, qty, weight and category.
"""

def max_price(items):
    """Largest price among the items, or 0 for an empty list."""
    return max((i.get("price", 0) for i in items), default=0)


def min_price(items):
    """Smallest price among the items, or 0 for an empty list."""
    return min((i.get("price", 0) for i in items), default=0)


def avg_price(items):
    """Average price of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("price", 0) for i in items) / len(items)


def max_qty(items):
    """Largest qty among the items, or 0 for an empty list."""
    return max((i.get("qty", 0) for i in items), default=0)


def min_qty(items):
    """Smallest qty among the items, or 0 for an empty list."""
    return min((i.get("qty", 0) for i in items), default=0)


def avg_qty(items):
    """Average qty of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("qty", 0) for i in items) / len(items)


def max_weight(items):
    """Largest weight among the items, or 0 for an empty list."""
    return max((i.get("weight", 0) for i in items), default=0)


def min_weight(items):
    """Smallest weight among the items, or 0 for an empty list."""
    return min((i.get("weight", 0) for i in items), default=0)


def avg_weight(items):
    """Average weight of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("weight", 0) for i in items) / len(items)


def max_cost(items):
    """Largest cost among the items, or 0 for an empty list."""
    return max((i.get("cost", 0) for i in items), default=0)


def min_cost(items):
    """Smallest cost among the items, or 0 for an empty list."""
    return min((i.get("cost", 0) for i in items), default=0)


def avg_cost(items):
    """Average cost of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("cost", 0) for i in items) / len(items)


def max_discount(items):
    """Largest discount among the items, or 0 for an empty list."""
    return max((i.get("discount", 0) for i in items), default=0)


def min_discount(items):
    """Smallest discount among the items, or 0 for an empty list."""
    return min((i.get("discount", 0) for i in items), default=0)


def avg_discount(items):
    """Average discount of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("discount", 0) for i in items) / len(items)


def max_tax(items):
    """Largest tax among the items, or 0 for an empty list."""
    return max((i.get("tax", 0) for i in items), default=0)


def min_tax(items):
    """Smallest tax among the items, or 0 for an empty list."""
    return min((i.get("tax", 0) for i in items), default=0)


def avg_tax(items):
    """Average tax of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("tax", 0) for i in items) / len(items)


def max_margin(items):
    """Largest margin among the items, or 0 for an empty list."""
    return max((i.get("margin", 0) for i in items), default=0)


def min_margin(items):
    """Smallest margin among the items, or 0 for an empty list."""
    return min((i.get("margin", 0) for i in items), default=0)


def avg_margin(items):
    """Average margin of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("margin", 0) for i in items) / len(items)


def max_rating(items):
    """Largest rating among the items, or 0 for an empty list."""
    return max((i.get("rating", 0) for i in items), default=0)


def min_rating(items):
    """Smallest rating among the items, or 0 for an empty list."""
    return min((i.get("rating", 0) for i in items), default=0)


def avg_rating(items):
    """Average rating of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("rating", 0) for i in items) / len(items)


def total_value(items):
    """Total stock value: the sum of price times qty over all items."""
    return sum(i["price"] for i in items)


def max_stock(items):
    """Largest stock among the items, or 0 for an empty list."""
    return max((i.get("stock", 0) for i in items), default=0)


def min_stock(items):
    """Smallest stock among the items, or 0 for an empty list."""
    return min((i.get("stock", 0) for i in items), default=0)


def avg_stock(items):
    """Average stock of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("stock", 0) for i in items) / len(items)


def max_reorder(items):
    """Largest reorder among the items, or 0 for an empty list."""
    return max((i.get("reorder", 0) for i in items), default=0)


def min_reorder(items):
    """Smallest reorder among the items, or 0 for an empty list."""
    return min((i.get("reorder", 0) for i in items), default=0)


def avg_reorder(items):
    """Average reorder of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("reorder", 0) for i in items) / len(items)


def max_shelf(items):
    """Largest shelf among the items, or 0 for an empty list."""
    return max((i.get("shelf", 0) for i in items), default=0)


def min_shelf(items):
    """Smallest shelf among the items, or 0 for an empty list."""
    return min((i.get("shelf", 0) for i in items), default=0)


def avg_shelf(items):
    """Average shelf of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("shelf", 0) for i in items) / len(items)


def max_age(items):
    """Largest age among the items, or 0 for an empty list."""
    return max((i.get("age", 0) for i in items), default=0)


def min_age(items):
    """Smallest age among the items, or 0 for an empty list."""
    return min((i.get("age", 0) for i in items), default=0)


def avg_age(items):
    """Average age of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("age", 0) for i in items) / len(items)


def max_returns(items):
    """Largest returns among the items, or 0 for an empty list."""
    return max((i.get("returns", 0) for i in items), default=0)


def min_returns(items):
    """Smallest returns among the items, or 0 for an empty list."""
    return min((i.get("returns", 0) for i in items), default=0)


def avg_returns(items):
    """Average returns of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("returns", 0) for i in items) / len(items)


def max_views(items):
    """Largest views among the items, or 0 for an empty list."""
    return max((i.get("views", 0) for i in items), default=0)


def min_views(items):
    """Smallest views among the items, or 0 for an empty list."""
    return min((i.get("views", 0) for i in items), default=0)


def avg_views(items):
    """Average views of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("views", 0) for i in items) / len(items)


def max_clicks(items):
    """Largest clicks among the items, or 0 for an empty list."""
    return max((i.get("clicks", 0) for i in items), default=0)


def min_clicks(items):
    """Smallest clicks among the items, or 0 for an empty list."""
    return min((i.get("clicks", 0) for i in items), default=0)


def avg_clicks(items):
    """Average clicks of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("clicks", 0) for i in items) / len(items)


def max_score(items):
    """Largest score among the items, or 0 for an empty list."""
    return max((i.get("score", 0) for i in items), default=0)


def min_score(items):
    """Smallest score among the items, or 0 for an empty list."""
    return min((i.get("score", 0) for i in items), default=0)


def avg_score(items):
    """Average score of the items, or 0.0 for an empty list."""
    if not items:
        return 0.0
    return sum(i.get("score", 0) for i in items) / len(items)


def by_category(items):
    """Group item names by category."""
    groups = {}
    for item in items:
        groups.setdefault(item.get("category", "other"), []).append(item["name"])
    return groups
