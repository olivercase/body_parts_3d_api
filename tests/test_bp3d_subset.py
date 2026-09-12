"""Tests for the subset selector.

No network and no meshes: what is tested is the part that decides *which*
meshes a request means, because a pattern that quietly matches nothing yields
a smaller subset rather than an error, and that is the failure a user would
not notice until a figure came out missing an organ.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

import bp3d_subset as sub

ROOT = Path(__file__).resolve().parents[1]


def _rows(*names: str) -> list[dict[str, str]]:
    return [
        {"fj_id": f"FJ{i}", "bp_id": f"BP{i}", "fma_id": f"FMA{i}", "name": n}
        for i, n in enumerate(names, start=1)
    ]


def test_select_matches_on_the_whole_name_not_a_substring() -> None:
    rows = _rows("Stomach", "Wall of stomach bed", "Duodenum")
    picked = sub.select(rows, [r"^stomach$"])
    assert [r["name"] for r in picked] == ["Stomach"]


def test_select_is_case_insensitive_and_deduplicates_by_fj_id() -> None:
    rows = _rows("Cerebellum", "Pons")
    rows.append(dict(rows[0]))  # the catalogue lists some FJ ids twice
    picked = sub.select(rows, [r"^CEREBELLUM$", r"^cerebellum$"])
    assert len(picked) == 1


def test_select_keeps_manifest_order_regardless_of_pattern_order() -> None:
    rows = _rows("Stomach", "Duodenum", "Rectum")
    a = sub.select(rows, [r"^rectum$", r"^stomach$"])
    b = sub.select(rows, [r"^stomach$", r"^rectum$"])
    assert [r["name"] for r in a] == [r["name"] for r in b] == ["Stomach", "Rectum"]


def test_read_manifest_names_the_column_it_is_missing(tmp_path: Path) -> None:
    bad = tmp_path / "MANIFEST.csv"
    bad.write_text("fj_id,name\nFJ1,Stomach\n")
    with pytest.raises(SystemExit, match="bp_id"):
        sub.read_manifest(bad)


def test_index_meshes_keys_on_the_filename_prefix(tmp_path: Path) -> None:
    (tmp_path / "FJ2428_BP1_FMA13884_Wall of ventricle.obj").write_text("o\n")
    (tmp_path / "notes.txt").write_text("ignored")
    index = sub.index_meshes(tmp_path)
    assert set(index) == {"FJ2428"}


def test_copy_from_local_refuses_to_copy_lfs_pointers(tmp_path: Path) -> None:
    src = tmp_path / "FJ1_BP1_FMA1_Stomach.obj"
    src.write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\n")
    with pytest.raises(SystemExit, match="git lfs pull"):
        sub.copy_from_local(
            _rows("Stomach"), sub.index_meshes(tmp_path), tmp_path / "o", link=False
        )


def test_every_builtin_group_selects_something_from_the_shipped_manifest() -> None:
    """The guard that matters: a typo in a pattern is otherwise invisible."""
    rows = sub.read_manifest(ROOT / "MANIFEST.csv")
    empty = [g for g, patterns in sub.GROUPS.items() if not sub.select(rows, patterns)]
    assert not empty, f"groups matching no mesh in the 4.3 set: {empty}"


def test_builtin_groups_are_the_sizes_the_readme_claims() -> None:
    """Catches a pattern that silently widens, e.g. losing an anchor."""
    rows = sub.read_manifest(ROOT / "MANIFEST.csv")
    counts = {g: len(sub.select(rows, p)) for g, p in sub.GROUPS.items()}
    assert counts["heart"] == 3
    assert counts["lungs"] == 18
    assert counts["spinal_cord"] == 1
    assert counts["vagus_nerve"] == 2
    assert counts["skin"] == 1
    # The composite systems are large but bounded; a runaway pattern would
    # pull in hundreds of vessels and nerves named after the same structures.
    assert 50 <= counts["brain"] <= 90
    assert 40 <= counts["gut"] <= 80
    assert 20 <= counts["leg_muscle"] <= 45
    assert 8 <= counts["blood_vessel"] <= 20
    assert 20 <= counts["spine"] <= 30


def test_write_manifest_records_what_is_on_disk(tmp_path: Path) -> None:
    obj = tmp_path / "g" / "FJ1_BP1_FMA1_Stomach.obj"
    obj.parent.mkdir()
    obj.write_text("o\n")
    out = tmp_path / "MANIFEST.csv"
    sub.write_manifest(out, [("gut", _rows("Stomach")[0], obj)], tmp_path)
    row = next(iter(csv.DictReader(out.open())))
    assert row["group"] == "gut"
    assert row["obj"] == "g/FJ1_BP1_FMA1_Stomach.obj"
    assert int(row["bytes"]) == obj.stat().st_size
