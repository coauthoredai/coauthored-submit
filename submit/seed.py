"""Schema creation and the seed rows that the classic tables' foreign keys need.

`seed_reference_rows` inserts, if missing: arXiv_licenses rows for the offered licences,
and arXiv_groups / arXiv_archives / arXiv_categories / arXiv_category_def rows for every
offered category (from arxiv.taxonomy.definitions). It is idempotent and runs at
`flask init-db` and at the start of every announce.
"""
from arxiv.db import Base as ClassicBase
from arxiv.db import models as classic  # noqa: F401  (registers the classic tables)
from arxiv.db.models import Archive, Category, CategoryDef, Group, License
from arxiv.taxonomy.definitions import ARCHIVES, CATEGORIES, GROUPS
from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .licenses import offered_licenses
from .models import CoauthoredBase
from .taxonomy import offered_categories, split_category

CLASSIC_TABLES_USED = ["arXiv_documents", "arXiv_metadata", "arXiv_document_category",
                       "arXiv_in_category", "arXiv_updates", "arXiv_licenses", "arXiv_groups",
                       "arXiv_archives", "arXiv_categories", "arXiv_category_def"]


def create_schema(engine: Engine) -> list[str]:
    """Create the coauthored tables, and on SQLite the classic tables too.

    On MySQL the classic schema comes from arxiv-base's arxiv/db/arxiv_db_schema.sql
    (see scripts/load_classic_schema.sh); returns the classic tables still missing.
    """
    if engine.dialect.name == "sqlite":
        ClassicBase.metadata.create_all(engine)
    CoauthoredBase.metadata.create_all(engine)
    existing = set(inspect(engine).get_table_names())
    return [t for t in CLASSIC_TABLES_USED if t not in existing]


def _group_id(taxonomy_group_id: str) -> str:
    # The taxonomy calls groups grp_physics; the classic tables call them physics.
    return taxonomy_group_id.removeprefix("grp_")


def seed_reference_rows(session: Session, license_host: str) -> int:
    """Insert missing licence and category rows. Returns the number of rows added."""
    added = 0
    have = set(session.scalars(select(License.name)))
    for opt in offered_licenses(license_host):
        if opt.uri not in have:
            session.add(License(name=opt.uri, label=opt.label, active=1, note=opt.note,
                                sequence=opt.sequence))
            added += 1

    cats = offered_categories()
    archives = {split_category(c)[0] for c in cats}
    groups = {_group_id(ARCHIVES[a].in_group): GROUPS[ARCHIVES[a].in_group] for a in archives}

    have = set(session.scalars(select(Group.group_id)))
    for gid, grp in sorted(groups.items()):
        if gid not in have:
            session.add(Group(group_id=gid, group_name=grp.full_name, start_year=str(grp.start_year)))
            added += 1
    session.flush()

    have = set(session.scalars(select(Archive.archive_id)))
    for arch_id in sorted(archives):
        if arch_id in have:
            continue
        arch = ARCHIVES[arch_id]
        session.add(Archive(
            archive_id=arch_id, in_group=_group_id(arch.in_group), archive_name=arch.full_name,
            start_date=arch.start_date.strftime("%y%m"),
            end_date=arch.end_date.strftime("%y%m") if arch.end_date else "",
            subdivided=int(any(c.startswith(arch_id + ".") for c in CATEGORIES))))
        added += 1
    session.flush()

    have = set(session.execute(select(Category.archive, Category.subject_class)).tuples())
    have_def = set(session.scalars(select(CategoryDef.category)))
    for cat_id, cat in cats.items():
        key = split_category(cat_id)
        if key not in have:
            session.add(Category(archive=key[0], subject_class=key[1], definitive=1, active=1,
                                 category_name=cat.full_name, endorse_all="d",
                                 endorse_email="d", papers_to_endorse=0))
            added += 1
        if cat_id not in have_def:
            session.add(CategoryDef(category=cat_id, name=cat.full_name, active=1))
            added += 1
    session.flush()
    return added
