#!/usr/bin/env python3
"""Download the COMPLETE, VERIFIED BodyParts3D / Anatomography **version 4.3** OBJ set.

The public dbarchive mirror only ships the 99%-polygon-reduced **4.0** set. The
full-resolution **4.3** meshes are served by the Anatomography viewer backend at
``lifesciencedb.jp/bp3d``. This script downloads the authoritative 4.3 element set
and verifies it, so there is no ambiguity about which version we hold.

Authoritative manifest (the key correctness fix)
------------------------------------------------
``get-info.cgi?version=4.3&cmd=concept-objfiles-list`` returns a ZIP containing
``FMA2Obj.txt`` whose header is explicitly version-stamped::

    # Data Version  4.3
    # Objects set   4.3
    # Tree version  FMA3.0
    # FMA ID  is_a/part_of  model component
    FMA10014  is_a  FJ3175
    FMA10446  is_a  FJ3202+FJ3203+...

The set of FJ "model component" ids in that file IS the version-4.3 object set
(3210 unique FJ). An earlier approach instead seeded concept ids from the
dbarchive ``isa_parts_list_e.txt`` (the **4.0** parts list) -> incomplete and
version-ambiguous. We no longer use that source.

FJ -> BP (rep_id) map needed for the download endpoint comes from
``get-info.cgi?version=4.3&cmd=upload-all-list&title=obj2FMA&tree=isa`` (HTML
table with FJID/BPID columns).

Download endpoint
-----------------
``download.cgi`` POST ``ids=[FJ...]&rep_id=[BP...]&type=art_file&all_downloads=1``
returns a ZIP of ``FJ..._BP..._FMA..._<name>.obj``. The FJ id deterministically
selects one geometry file (full resolution); ``mv_id``/``version`` on this call
is ignored -- the version is fixed by *which FJ ids* you request, which is why
sourcing them from the 4.3 manifest is what makes the result 4.3.

Output layout (under ``--out``, default ``data/bodyparts3d/raw_4.3``)::

    metadata/   FMA2Obj.txt (4.3 manifest), obj2FMA.html (FJ<->BP)
    chunks/     chunk_0000.zip ...            (raw downloads, resumable)
    objs/       FJ..._BP..._FMA..._<name>.obj (unzipped, deduped, flat)
    MANIFEST.csv  one row per FJ: fj_id, bp_id, fma_id, name, faces, verts, bytes, mtime
    download.log

Resumable: a chunk whose ``.zip`` exists and unzips cleanly is skipped.
Polite: sequential requests with a small delay + retries/backoff.

License of the data: CC-BY-SA 2.1 Japan, (c) Database Center for Life Science
(DBCLS). Attribute DBCLS / BodyParts3D when redistributing.

Usage::

    python3 scripts/download_bodyparts3d_4.3.py                 # full fresh run + verify
    python3 scripts/download_bodyparts3d_4.3.py --limit 80      # smoke test (first N FJ)
    python3 scripts/download_bodyparts3d_4.3.py --chunk-size 50 # tune batch size
    python3 scripts/download_bodyparts3d_4.3.py --verify-only    # re-verify existing objs/
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# -- endpoints / constants ----------------------------------------------------
BASE = "https://lifesciencedb.jp/bp3d"
VIEWER = f"{BASE}/?lng=en"
INFO_CGI = f"{BASE}/get-info.cgi"
DOWNLOAD_CGI = f"{BASE}/download.cgi"
VERSION = "4.3"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

logger = logging.getLogger("bp3d_dl")


# -- low-level HTTP via curl (proven to work with these CGIs + cookies) -------
def _curl(args: list[str], *, retries: int = 4, timeout: int = 300) -> bytes:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            p = subprocess.run(args, capture_output=True, timeout=timeout)
            if p.returncode == 0:
                return p.stdout
            last_err = RuntimeError(
                f"curl rc={p.returncode}: {p.stderr.decode(errors='replace')[:200]}"
            )
        except subprocess.TimeoutExpired as e:
            last_err = e
        wait = 2**attempt
        logger.warning(
            "  request failed (attempt %d/%d): %s -- retrying in %ds",
            attempt,
            retries,
            last_err,
            wait,
        )
        time.sleep(wait)
    raise RuntimeError(f"curl failed after {retries} attempts: {last_err}")


def _base_curl(cookies: Path) -> list[str]:
    return [
        "curl",
        "-A",
        UA,
        "-e",
        VIEWER,
        "-b",
        str(cookies),
        "-c",
        str(cookies),
        "-s",
        "--compressed",
    ]


def get_session(cookies: Path) -> None:
    _curl(["curl", "-A", UA, "-c", str(cookies), "-s", "-o", "/dev/null", VIEWER])
    logger.info("session cookie established -> %s", cookies)


# -- authoritative 4.3 manifests ----------------------------------------------
def fetch_fma2obj(meta_dir: Path, cookies: Path) -> Path:
    """Download + extract the version-stamped 4.3 manifest (FMA2Obj.txt)."""
    dst = meta_dir / "FMA2Obj.txt"
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    logger.info("fetching 4.3 manifest (concept-objfiles-list)")
    blob = _curl([*_base_curl(cookies), f"{INFO_CGI}?version={VERSION}&cmd=concept-objfiles-list"])
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.endswith(".txt"))
        dst.write_bytes(z.read(name))
    return dst


def fetch_obj2fma(meta_dir: Path, cookies: Path) -> Path:
    dst = meta_dir / "obj2FMA.html"
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    logger.info("fetching FJ<->BP map (obj2FMA upload-all-list)")
    blob = _curl(
        [
            *_base_curl(cookies),
            "-X",
            "POST",
            "--data-urlencode",
            "cmd=upload-all-list",
            "--data-urlencode",
            "load=1",
            "--data-urlencode",
            "md_abbr=bp3d",
            "--data-urlencode",
            "title=obj2FMA",
            "--data-urlencode",
            "tree=isa",
            "--data-urlencode",
            f"version={VERSION}",
            INFO_CGI,
        ]
    )
    dst.write_bytes(blob)
    return dst


def parse_manifest(fma2obj: Path) -> dict[str, str]:
    """Return {FJ id -> FMA id}. The FJ set is the authoritative 4.3 object set."""
    fj2fma: dict[str, str] = {}
    for line in fma2obj.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        fma = cols[0].strip()
        for comp in cols[2].split("+"):
            comp = comp.strip()
            if comp.startswith("FJ"):
                fj2fma.setdefault(comp, fma)
    return fj2fma


def parse_fj2bp(obj2fma_html: Path) -> dict[str, str]:
    html = obj2fma_html.read_text(encoding="utf-8", errors="replace")
    fj2bp: dict[str, str] = {}
    for row in re.findall(r"<tr>\s*(.*?)\s*</tr>", html, re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        if len(cells) >= 7:
            fj, bp = cells[1].strip(), cells[2].strip()
            if fj and bp:
                fj2bp[fj] = bp
    return fj2bp


# -- download -----------------------------------------------------------------
def download_zip(fj_ids: list[str], bp_ids: list[str], dst: Path, cookies: Path) -> None:
    args = [
        *_base_curl(cookies),
        "-o",
        str(dst),
        "--data-urlencode",
        f"ids={json.dumps(fj_ids)}",
        "--data-urlencode",
        f"rep_id={json.dumps(bp_ids)}",
        "--data-urlencode",
        f"filename={dst.stem}",
        "--data-urlencode",
        "type=art_file",
        "--data-urlencode",
        "all_downloads=1",
        DOWNLOAD_CGI,
    ]
    _curl(args, timeout=600)


def _zip_ok(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with zipfile.ZipFile(path) as z:
            return z.testzip() is None and len(z.namelist()) > 0
    except zipfile.BadZipFile:
        return False


def run(out: Path, *, chunk_size: int, limit: int | None, delay: float) -> None:
    meta_dir, chunks_dir, objs_dir = out / "metadata", out / "chunks", out / "objs"
    for d in (out, meta_dir, chunks_dir, objs_dir):
        d.mkdir(parents=True, exist_ok=True)

    cookies = out / "_session_cookies.txt"
    get_session(cookies)

    fj2fma = parse_manifest(fetch_fma2obj(meta_dir, cookies))
    fj2bp = parse_fj2bp(fetch_obj2fma(meta_dir, cookies))
    target = sorted(fj2fma)
    if limit:
        target = target[:limit]

    missing_bp = [fj for fj in target if fj not in fj2bp]
    if missing_bp:
        logger.warning(
            "%d/%d target FJ have no BP id in obj2FMA (cannot download): %s",
            len(missing_bp),
            len(target),
            missing_bp[:10],
        )
    target = [fj for fj in target if fj in fj2bp]
    logger.info("authoritative 4.3 object set: %d FJ (downloadable: %d)", len(fj2fma), len(target))

    chunks = [target[i : i + chunk_size] for i in range(0, len(target), chunk_size)]
    logger.info("%d FJ -> %d chunks of %d", len(target), len(chunks), chunk_size)

    n_skip = n_done = n_fail = 0
    for ci, chunk in enumerate(chunks):
        zpath = chunks_dir / f"chunk_{ci:04d}.zip"
        if _zip_ok(zpath):
            n_skip += 1
            continue
        bps = sorted({fj2bp[fj] for fj in chunk})
        try:
            download_zip(chunk, bps, zpath, cookies)
            if not _zip_ok(zpath):
                raise RuntimeError("downloaded file is not a valid non-empty zip")
            with zipfile.ZipFile(zpath) as z:
                n_obj = sum(1 for n in z.namelist() if n.lower().endswith(".obj"))
            n_done += 1
            logger.info(
                "chunk %04d/%d: %d FJ -> %d OBJ (%.1f MB)",
                ci,
                len(chunks),
                len(chunk),
                n_obj,
                zpath.stat().st_size / 1e6,
            )
        except Exception as e:
            n_fail += 1
            logger.error("chunk %04d FAILED: %s", ci, e)
            zpath.unlink(missing_ok=True)
        time.sleep(delay)

    logger.info("download phase done: %d new, %d skipped, %d failed", n_done, n_skip, n_fail)
    extract_all(chunks_dir, objs_dir, set(fj2fma))


def extract_all(chunks_dir: Path, objs_dir: Path, target_fj: set[str]) -> int:
    """Unzip every chunk into a flat, FJ-deduplicated objs/ folder.

    Only FJ ids in the 4.3 manifest are extracted (a download batch can return
    sibling elements that are not part of the canonical set)."""
    objs_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    n = 0
    for zpath in sorted(chunks_dir.glob("chunk_*.zip")):
        if not _zip_ok(zpath):
            continue
        with zipfile.ZipFile(zpath) as z:
            for member in z.namelist():
                if not member.lower().endswith(".obj"):
                    continue
                name = Path(member).name
                fj = name.split("_", 1)[0]
                if fj in seen or fj not in target_fj:
                    continue
                seen.add(fj)
                (objs_dir / name).write_bytes(z.read(member))
                n += 1
    logger.info("extracted %d unique in-manifest OBJ meshes -> %s", n, objs_dir)
    return n


# -- verification -------------------------------------------------------------
def verify(out: Path) -> int:
    """Confirm every manifest FJ is present + loads; write MANIFEST.csv. Returns missing count."""
    try:
        import trimesh
    except ImportError:
        logger.error("trimesh not installed -- cannot verify geometry")
        return -1

    meta_dir, objs_dir = out / "metadata", out / "objs"
    fj2fma = parse_manifest(meta_dir / "FMA2Obj.txt")
    fj2bp = parse_fj2bp(meta_dir / "obj2FMA.html")

    have: dict[str, Path] = {}
    for f in objs_dir.glob("*.obj"):
        have[f.name.split("_", 1)[0]] = f

    rows = []
    bad = []
    for fj in sorted(fj2fma):
        path = have.get(fj)
        if path is None:
            continue
        try:
            m = trimesh.load(path, process=False)
            faces, verts = len(m.faces), len(m.vertices)
            if faces == 0:
                bad.append((fj, "0 faces"))
        except Exception as e:
            bad.append((fj, str(e)[:80]))
            faces = verts = -1
        name = (
            path.name.split("_", 3)[-1].rsplit(".obj", 1)[0]
            if path.name.count("_") >= 3
            else path.stem
        )
        rows.append(
            {
                "fj_id": fj,
                "bp_id": fj2bp.get(fj, ""),
                "fma_id": fj2fma[fj],
                "name": name,
                "faces": faces,
                "verts": verts,
                "bytes": path.stat().st_size,
                "mtime": int(path.stat().st_mtime),
            }
        )

    missing = sorted(set(fj2fma) - set(have))
    extras = sorted(set(have) - set(fj2fma))

    csv_path = out / "MANIFEST.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["fj_id", "bp_id", "fma_id", "name", "faces", "verts", "bytes", "mtime"]
        )
        w.writeheader()
        w.writerows(rows)

    logger.info(
        "VERIFY: manifest=%d  present=%d  missing=%d  extras(not in 4.3)=%d  bad=%d",
        len(fj2fma),
        len(rows),
        len(missing),
        len(extras),
        len(bad),
    )
    if missing:
        logger.warning(
            "  missing FJ (%d): %s%s",
            len(missing),
            missing[:15],
            " ..." if len(missing) > 15 else "",
        )
    if bad:
        logger.warning("  unloadable/empty OBJ (%d): %s", len(bad), bad[:10])
    logger.info("  wrote %s (%d rows)", csv_path, len(rows))
    return len(missing)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=Path("data/bodyparts3d/raw_4.3"))
    ap.add_argument("--chunk-size", type=int, default=50, help="FJ ids per request batch")
    ap.add_argument("--limit", type=int, default=None, help="only the first N FJ (smoke test)")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests (be polite)")
    ap.add_argument(
        "--verify-only", action="store_true", help="skip download; just verify existing objs/"
    )
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(args.out / "download.log"),
        ],
    )

    if args.verify_only:
        return 1 if verify(args.out) else 0
    run(args.out, chunk_size=args.chunk_size, limit=args.limit, delay=args.delay)
    return 1 if verify(args.out) else 0


if __name__ == "__main__":
    sys.exit(main())
