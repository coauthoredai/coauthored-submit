"""Categories offered for submission, from arxiv-base's taxonomy.

Offered: active categories under their canonical name (an alias such as math.IT is offered
as cs.IT only), outside the test group.
"""
from functools import lru_cache
from typing import NamedTuple

from arxiv.taxonomy.category import Category
from arxiv.taxonomy.definitions import ARCHIVES, CATEGORIES_ACTIVE, GROUPS


class CategoryOption(NamedTuple):
    id: str
    label: str


@lru_cache(maxsize=1)
def offered_categories() -> dict[str, Category]:
    out = {}
    for cat_id, cat in CATEGORIES_ACTIVE.items():
        if cat.canonical_id != cat_id:
            continue
        group = GROUPS[ARCHIVES[cat.in_archive].in_group]
        if group.is_test:
            continue
        out[cat_id] = cat
    return dict(sorted(out.items()))


def is_offered(cat_id: str) -> bool:
    return cat_id in offered_categories()


def grouped_options() -> list[tuple[str, list[CategoryOption]]]:
    """(group name, options) pairs for <optgroup>s, in group order."""
    groups: dict[str, list[CategoryOption]] = {}
    for cat_id, cat in offered_categories().items():
        group = GROUPS[ARCHIVES[cat.in_archive].in_group]
        groups.setdefault(group.full_name, []).append(
            CategoryOption(cat_id, f"{cat.full_name} ({cat_id})"))
    return sorted(groups.items())


def split_category(cat_id: str) -> tuple[str, str]:
    """`cs.GT` -> (`cs`, `GT`); a category with no dot, `hep-th` -> (`hep-th`, ``)."""
    archive, _, subject = cat_id.partition(".")
    return archive, subject


def category_label(cat_id: str) -> str:
    cat = offered_categories().get(cat_id) or CATEGORIES_ACTIVE.get(cat_id)
    return f"{cat.full_name} ({cat_id})" if cat else cat_id
