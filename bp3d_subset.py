#!/usr/bin/env python3
"""Select a named subset of the BodyParts3D 4.3 mesh set.

``download_bodyparts3d_4.3.py`` answers "give me all of 4.3". This answers the
question you usually have instead — "give me a brain, a gut and a pair of
lungs" — by matching the catalogue's own FMA names and either copying those
meshes out of the set already in this repository or, with ``--download``,
fetching only those from source.

Selection is by regular expression over the ``name`` column of
``MANIFEST.csv``, which holds the FMA name BodyParts3D ships for each element.
That makes a group auditable: ``--list`` prints exactly which meshes a pattern
selects, and how many, before anything is copied or downloaded. Several
ready-made groups covering the major systems are built in (see :data:`GROUPS`);
``--pattern`` takes an ad-hoc one.

Whole organs are often not single meshes in 4.3 — the cerebrum is supplied as
gyri, the lung as bronchopulmonary segments, the heart as chamber walls — so a
group is usually several elements that together make the structure.

Examples::

    python3 bp3d_subset.py --list
    python3 bp3d_subset.py --group heart --group lungs --out subset
    python3 bp3d_subset.py --pattern '^(left|right) .*gyrus$' --name gyri --out subset
    python3 bp3d_subset.py --group gut --download --out subset

Data © Database Center for Life Science (DBCLS); BodyParts3D is licensed
CC-BY-SA 2.1 Japan. This code is MIT-licensed.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import logging
import re
import shutil
import sys
import zipfile
from pathlib import Path
from types import ModuleType

logger = logging.getLogger("bp3d_subset")

#: Ready-made groups, as case-insensitive regexes over the FMA name.
#:
#: Deliberately explicit rather than derived from the FMA IS-A tree: these are
#: cast lists for figures and models, not a classification, and anyone using
#: one should be able to read here exactly what it was taken to mean.
GROUPS: dict[str, list[str]] = {
    # No single whole-brain mesh exists in 4.3: the cerebrum is supplied as
    # gyri. Gyri plus cerebellum and brainstem reconstitute it.
    "brain": [
        r"^(left|right) .*gyrus$",
        r"^(anterior|posterior) part of (left|right) .*gyrus$",
        r"^(left|right) occipital lobe$",
        r"^(left|right) (thalamus|insula|cuneus|precuneus|hippocampus)$",
        r"^cerebellum$",
        r"^(pons|medulla oblongata)$",
    ],
    "spine": [
        r"^(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
        r"eleventh|twelfth) (cervical|thoracic|lumbar) vertebra$",
        r"^(sacrum|coccyx)$",
    ],
    "spinal_cord": [r"^neural tissue of spinal cord$"],
    "vagus_nerve": [r"^trunk of (left|right) vagus nerve$"],
    # The heart is supplied as its chamber walls, which give the outer form.
    "heart": [
        r"^wall of ventricle$",
        r"^wall of (left|right) atrium$",
    ],
    # The lung parenchyma comes one mesh per bronchopulmonary segment.
    "lungs": [r"^parenchyma of .*bronchopulmonary segment$"],
    "gut": [
        r"^stomach$",
        r"^duodenum$",
        r"^(proximal|middle|distal) part of (jejunum|ileum)$",
        r"^(ascending|transverse|descending|sigmoid) colon$",
        r"^rectum$",
    ],
    "blood_vessel": [
        r"^(ascending aorta|arch of aorta|descending aorta)$",
        r"^(superior|inferior) vena cava$",
        r"^trunk of (left|right) common carotid artery$",
        r"^(left|right) internal jugular vein$",
        r"^pulmonary trunk$",
    ],
    "leg_muscle": [
        r"^(left|right) (gluteus maximus|gluteus medius|gluteus minimus)$",
        r"^(left|right) (rectus femoris|vastus lateralis|vastus medialis|vastus intermedius)$",
        r"^(long|short) head of (left|right) biceps femoris$",
        r"^(left|right) (semitendinosus|semimembranosus|sartorius|gracilis)$",
        r"^(lateral|medial) head of (left|right) gastrocnemius$",
        r"^(left|right) (soleus|tibialis anterior|tibialis posterior)$",
    ],
    "skin": [r"^skin$"],
}

#: Columns every row of the repository manifest carries.
MANIFEST_FIELDS = ("fj_id", "bp_id", "fma_id", "name")


# ── catalogue ──────────────────────────────────────────────────────────────


def read_manifest(path: Path) -> list[dict[str, str]]:
    """Rows of the repository manifest, validated.

    A missing column here would otherwise surface much later as an empty
    selection, which looks like a bad pattern rather than a bad file.
    """
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in MANIFEST_FIELDS if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"{path} is missing column(s): {', '.join(missing)}")
        return [dict(row) for row in reader]


def select(rows: list[dict[str, str]], patterns: list[str]) -> list[dict[str, str]]:
    """The rows whose ``name`` matches any pattern, de-duplicated by FJ id.

    Order follows the manifest, not the pattern list, so the same request
    always yields the same subset in the same order.
    """
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        if row["fj_id"] in seen:
            continue
        if any(p.match(row["name"]) for p in compiled):
            seen.add(row["fj_id"])
            out.append(row)
    return out


def index_meshes(mesh_dir: Path) -> dict[str, Path]:
    """FJ id -> its mesh file, keyed off the filename's own ``FJ…_`` prefix.

    The manifest does not carry filenames; the naming convention
    ``FJ…_BP…_FMA…_<name>.obj`` is what ties the two together, and reading it
    from the directory means a renamed or missing file is caught here rather
    than producing a silently smaller subset.
    """
    return {p.name.split("_", 1)[0]: p for p in mesh_dir.glob("*.obj")}


# ── the two sources ────────────────────────────────────────────────────────


def copy_from_local(
    picked: list[dict[str, str]],
    index: dict[str, Path],
    dest: Path,
    *,
    link: bool,
) -> list[tuple[dict[str, str], Path]]:
    """Copy (or hard-link) the selected meshes out of the committed set."""
    dest.mkdir(parents=True, exist_ok=True)
    out: list[tuple[dict[str, str], Path]] = []
    for row in picked:
        src = index.get(row["fj_id"])
        if src is None:
            logger.warning("  %s %s: no mesh file in the set", row["fj_id"], row["name"])
            continue
        if src.stat().st_size < 200 and src.read_bytes().startswith(b"version https://git-lfs"):
            # A pointer file, not geometry: the clone has not run `git lfs
            # pull`. Copying it would produce a subset of unusable stubs.
            raise SystemExit(
                f"{src} is a Git LFS pointer, not a mesh — run `git lfs pull` "
                "before selecting from the local set, or pass --download"
            )
        dst = dest / src.name
        if not dst.exists():
            if link:
                dst.hardlink_to(src)
            else:
                shutil.copy2(src, dst)
        out.append((row, dst))
    return out


def _load_downloader(root: Path) -> ModuleType:
    """Import the full-set downloader for its session and endpoint code.

    Its filename carries a dot ("...4.3.py") so it is not importable by name;
    this is the way in, and keeps one implementation of the endpoint protocol
    rather than a second copy that can drift from it.
    """
    path = root / "download_bodyparts3d_4.3.py"
    spec = importlib.util.spec_from_file_location("bp3d_download", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def download_picked(
    root: Path,
    picked: list[dict[str, str]],
    dest: Path,
    work: Path,
    *,
    chunk_size: int,
) -> list[tuple[dict[str, str], Path]]:
    """Fetch only the selected meshes from source, resumably."""
    dl = _load_downloader(root)
    dest.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    cookies = work / "_session_cookies.txt"
    dl.get_session(cookies)

    for i in range(0, len(picked), chunk_size):
        batch = picked[i : i + chunk_size]
        zpath = work / f"chunk_{i // chunk_size:03d}.zip"
        if not dl._zip_ok(zpath):
            dl.download_zip(
                [r["fj_id"] for r in batch],
                sorted({r["bp_id"] for r in batch}),
                zpath,
                cookies,
            )
            if not dl._zip_ok(zpath):
                raise SystemExit(f"{zpath} is not a readable zip")
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                if not name.lower().endswith(".obj"):
                    continue
                target = dest / Path(name).name
                if not target.exists():
                    target.write_bytes(z.read(name))
        logger.info("  chunk %d: %d ids", i // chunk_size, len(batch))

    index = index_meshes(dest)
    out: list[tuple[dict[str, str], Path]] = []
    for row in picked:
        obj = index.get(row["fj_id"])
        if obj is None:
            # Some catalogue concepts are grouping nodes with no geometry of
            # their own; the endpoint returns nothing for them, silently.
            logger.warning("  %s %s: not served", row["fj_id"], row["name"])
            continue
        out.append((row, obj))
    return out


# ── cli ────────────────────────────────────────────────────────────────────


def resolve_groups(args: argparse.Namespace) -> dict[str, list[str]]:
    """The groups this invocation asks for, built-in or ad-hoc."""
    if args.pattern:
        return {args.name: list(args.pattern)}
    if args.group:
        return {g: GROUPS[g] for g in args.group}
    return dict(GROUPS)


def write_manifest(path: Path, rows: list[tuple[str, dict[str, str], Path]], base: Path) -> None:
    """Record what the subset actually contains, not what was asked for."""
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, ["group", *MANIFEST_FIELDS, "obj", "bytes"])
        writer.writeheader()
        for group, row, obj in rows:
            writer.writerow(
                {
                    "group": group,
                    **{k: row[k] for k in MANIFEST_FIELDS},
                    "obj": obj.relative_to(base).as_posix(),
                    "bytes": obj.stat().st_size,
                }
            )


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--manifest", type=Path, default=root / "MANIFEST.csv")
    ap.add_argument("--meshes", type=Path, default=root / "meshes")
    ap.add_argument("--out", type=Path, default=Path("subset"))
    ap.add_argument(
        "--group",
        action="append",
        default=[],
        choices=sorted(GROUPS),
        help="A built-in group (repeatable). Default: all of them.",
    )
    ap.add_argument(
        "--pattern",
        action="append",
        default=[],
        help="An ad-hoc regex over the FMA name (repeatable). Overrides --group.",
    )
    ap.add_argument(
        "--name",
        default="custom",
        help="Group name for --pattern selections (default: custom).",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="Print what each group selects and exit, writing nothing.",
    )
    ap.add_argument(
        "--download",
        action="store_true",
        help="Fetch the selection from source instead of copying it out of meshes/.",
    )
    ap.add_argument(
        "--link",
        action="store_true",
        help="Hard-link instead of copying, when selecting from the local set.",
    )
    ap.add_argument("--chunk-size", type=int, default=50, help="FJ ids per download request.")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    rows = read_manifest(args.manifest)
    wanted = resolve_groups(args)
    chosen = {group: select(rows, patterns) for group, patterns in wanted.items()}

    for group, picked in chosen.items():
        logger.info("%s: %d meshes", group, len(picked))
        if args.list:
            for row in picked:
                logger.info("    %-10s %-12s %s", row["fj_id"], row["fma_id"], row["name"])
    if args.list:
        return 0

    empty = [g for g, p in chosen.items() if not p]
    if empty:
        # A pattern that matches nothing is a silent hole in the result, not a
        # smaller one: say so rather than write an incomplete subset.
        raise SystemExit(f"no meshes matched for: {', '.join(empty)}")

    if not args.download and not args.meshes.is_dir():
        raise SystemExit(f"{args.meshes} not found — clone with Git LFS, or pass --download")

    index = {} if args.download else index_meshes(args.meshes)
    written: list[tuple[str, dict[str, str], Path]] = []
    for group, picked in chosen.items():
        dest = args.out / group
        logger.info("%s %s (%d)", "downloading" if args.download else "copying", group, len(picked))
        if args.download:
            pairs = download_picked(
                root, picked, dest, args.out / "_chunks" / group, chunk_size=args.chunk_size
            )
        else:
            pairs = copy_from_local(picked, index, dest, link=args.link)
        written += [(group, row, obj) for row, obj in pairs]

    short = sorted(set(chosen) - {g for g, _, _ in written})
    if short:
        raise SystemExit(f"no geometry obtained for: {', '.join(short)}")

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = args.out / "MANIFEST.csv"
    write_manifest(manifest, written, args.out)
    logger.info("wrote %s (%d meshes)", manifest, len(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
