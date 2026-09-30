"""docs/PROJECT_STATE.md is the project's front page, and a front page goes
stale quietly. These checks catch the facts that drift when the code
changes: the alembic head it names, the production services it lists, its
"Last updated" line and its links. When one fails, update the document in
the same commit (its first section says which parts to touch)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent.parent
DOC_PATH = ROOT / "docs" / "PROJECT_STATE.md"
DOC = DOC_PATH.read_text(encoding="utf-8")


def _alembic_head() -> str:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in (ROOT / "migrations" / "versions").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision(?::[^=]*)?\s*=\s*"([0-9a-f]+)"', text, re.M)
        if revision is None:
            continue
        revisions.add(revision.group(1))
        down = re.search(r"^down_revision(?::[^=]*)?\s*=\s*(.+)$", text, re.M)
        if down is not None:
            parents.update(re.findall(r'"([0-9a-f]+)"', down.group(1)))
    heads = revisions - parents
    assert len(heads) == 1, f"expected one alembic head, found {sorted(heads)}"
    return heads.pop()


def test_the_alembic_head_it_names_is_the_real_one() -> None:
    named = re.search(r"\*\*Alembic head:\*\* `([0-9a-f]+)`", DOC)
    assert named is not None, "the header line must name the alembic head"
    assert named.group(1) == _alembic_head()


def test_it_lists_every_production_service() -> None:
    compose = yaml.safe_load((ROOT / "deploy" / "docker-compose.prod.yml").read_text(encoding="utf-8"))
    missing = [name for name in compose["services"] if f"`{name}`" not in DOC]
    assert missing == [], f"services missing from the Architecture section: {missing}"


def test_last_updated_matches_the_latest_change_log_entry() -> None:
    last_updated = re.search(r"\*\*Last updated:\*\* (\d{4}-\d{2}-\d{2})", DOC)
    assert last_updated is not None
    change_log = DOC.split("## Change Log", 1)[1]
    latest_entry = re.search(r"^- \*\*(\d{4}-\d{2}-\d{2})", change_log, re.M)
    assert latest_entry is not None, "the Change Log needs a dated entry"
    assert latest_entry.group(1) == last_updated.group(1)


def test_every_relative_link_points_at_a_real_file() -> None:
    broken = []
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", DOC):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (DOC_PATH.parent / target).exists():
            broken.append(target)
    assert broken == [], f"broken links: {broken}"
