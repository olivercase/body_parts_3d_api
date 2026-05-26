#!/usr/bin/env python3
"""Download the COMPLETE BodyParts3D / Anatomography **version 4.3** OBJ mesh set.

Neither of the two *documented* ways of getting BodyParts3D data can give you the
full-resolution 4.3 meshes (see README.md for the full explanation):

  * The official **bulk archive** (dbarchive.biosciencedbc.jp) only ships version
    **4.0**, and only the 99%-polygon-**reduced** OBJ set.
  * The official **Anatomography Web API** (lifesciencedb.jp/bp3d/info_en/webapi/)
    only *renders* images (PNG/GIF) and returns coordinate JSON — it has **no**
    endpoint that returns a 3D mesh/OBJ file, and its version selector stops at 4.1.

The full-resolution **4.3** meshes exist only inside the Anatomography web viewer,
served by two **undocumented** CGI endpoints that this script drives:

  1. ``download-pallet-art_file.cgi``  POST ``rep_ids=[{rep_id,opacity,exclude},…]``
        → ``{"art_ids":[FJ…], "rep_ids":[BP…], "success":true}``
        (expands a concept id into its constituent element-file ids)
  2. ``download.cgi``  POST ``rep_id=[BP…]&ids=[FJ…]&type=art_file&all_downloads=1``
        → a ZIP of ``FJ…_BP…_FMA…_<name>.obj`` files (dated 2014-03 == the 4.3 build)

The list of every concept id comes from the authoritative parts-list metadata
(``isa_parts_list_e.txt``, hosted on the dbarchive mirror); the pallet step then
expands those concepts into the full element (FJ) set, deduplicated at extraction.

Identifier scheme: ``FMA…`` = Foundational Model of Anatomy concept id;
``BP…`` = BodyParts3D representation/concept id; ``FJ…`` = element-file id (one OBJ each).

Output layout (under ``--out``, default ``./bodyparts3d_4.3``)::

    metadata/   isa_parts_list_e.txt, isa_element_parts.txt   (id↔FMA↔name maps)
    chunks/     chunk_0000.zip …                              (raw downloads, resumable)
    objs/       FJ…_BP…_FMA…_<name>.obj                       (unzipped, deduped, flat)
    download.log

Resumable: a chunk whose ``.zip`` already exists and unzips cleanly is skipped.
Polite: sequential requests with a small delay + retries/backoff.

DATA LICENSE: the downloaded meshes are BodyParts3D, © The Database Center for Life
Science (DBCLS), licensed CC-BY-SA 2.1 Japan. Attribute DBCLS / BodyParts3D when you
redistribute the meshes. This script (the code) is MIT-licensed — see LICENSE.

Requirements: Python 3.9+ and ``curl`` on PATH (curl is what reliably negotiates the
viewer's cookies/compression with these CGIs). No third-party Python packages.

Usage::

    python3 download_bodyparts3d.py                 # full run → ./bodyparts3d_4.3/objs
    python3 download_bodyparts3d.py --limit 80      # smoke test (first N concepts)
    python3 download_bodyparts3d.py --chunk-size 40 # tune batch size
    python3 download_bodyparts3d.py --no-extract    # download zips only, skip unzip
    python3 download_bodyparts3d.py --extract-only  # just (re)unzip existing chunks
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# ── endpoints / constants ─────────────────────────────────────────────────────
BASE = "https://lifesciencedb.jp/bp3d"
VIEWER = f"{BASE}/?lng=en"
PALLET_CGI = f"{BASE}/download-pallet-art_file.cgi"
DOWNLOAD_CGI = f"{BASE}/download.cgi"
DBARCHIVE = "https://dbarchive.biosciencedbc.jp/data/bodyparts3d/LATEST"
METADATA_FILES = ("isa_parts_list_e.txt", "isa_element_parts.txt")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

logger = logging.getLogger("bp3d_dl")


# ── low-level HTTP via curl (curl reliably handles these CGIs + cookies) ───────
def _curl(args: list[str], *, retries: int = 4, timeout: int = 180) -> bytes:
    """Run curl, returning stdout bytes. Retries with exponential backoff."""
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            p = subprocess.run(args, capture_output=True, timeout=timeout)
            if p.returncode == 0:
                return p.stdout
            last_err = RuntimeError(
                f"curl rc={p.returncode}: {p.stderr.decode(errors='replace')[:200]}")
        except subprocess.TimeoutExpired as e:
            last_err = e
        wait = 2 ** attempt
        logger.warning("  request failed (attempt %d/%d): %s — retrying in %ds",
                       attempt, retries, last_err, wait)
        time.sleep(wait)
    raise RuntimeError(f"curl failed after {retries} attempts: {last_err}")


def _base_curl(cookies: Path) -> list[str]:
    return ["curl", "-A", UA, "-e", VIEWER, "-b", str(cookies), "-c", str(cookies),
            "-s", "--compressed"]


def get_session(cookies: Path) -> None:
    """Prime a session cookie from the viewer page."""
    _curl(["curl", "-A", UA, "-c", str(cookies), "-s", "-o", "/dev/null", VIEWER])
    logger.info("session cookie established → %s", cookies)


def fetch_metadata(meta_dir: Path) -> None:
    meta_dir.mkdir(parents=True, exist_ok=True)
    for f in METADATA_FILES:
        dst = meta_dir / f
        if dst.exists() and dst.stat().st_size > 0:
            continue
        logger.info("fetching metadata %s", f)
        data = _curl(["curl", "-A", UA, "-fsSL", f"{DBARCHIVE}/{f}"], timeout=300)
        dst.write_bytes(data)


def load_concept_ids(meta_dir: Path) -> list[str]:
    """All representation (BP) ids from isa_parts_list_e.txt (cols: FMA, BP, name)."""
    path = meta_dir / "isa_parts_list_e.txt"
    bp_ids: list[str] = []
    seen: set[str] = set()
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        if i == 0:
            continue  # header
        cols = line.split("\t")
        if len(cols) >= 2 and cols[1].startswith("BP") and cols[1] not in seen:
            seen.add(cols[1])
            bp_ids.append(cols[1])
    return bp_ids


# ── the two-step download ──────────────────────────────────────────────────────
def resolve_pallet(bp_ids: list[str], cookies: Path) -> tuple[list[str], list[str]]:
    """Concept ids → (art_ids[FJ], rep_ids[BP]) via download-pallet-art_file.cgi."""
    payload = json.dumps([{"rep_id": b, "opacity": 1, "exclude": False} for b in bp_ids])
    out = _curl(_base_curl(cookies) + ["--data-urlencode", f"rep_ids={payload}", PALLET_CGI])
    try:
        r = json.loads(out.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"pallet returned non-JSON: {out[:200]!r}") from e
    if not r.get("success"):
        raise RuntimeError(f"pallet failed: {r.get('msg')}")
    return r.get("art_ids", []), r.get("rep_ids", [])


def download_zip(art_ids: list[str], rep_ids: list[str], dst: Path, cookies: Path) -> None:
    """download.cgi → ZIP of OBJs for the paired (FJ, BP) id lists."""
    args = _base_curl(cookies) + [
        "-o", str(dst),
        "--data-urlencode", f"ids={json.dumps(art_ids)}",
        "--data-urlencode", f"rep_id={json.dumps(rep_ids)}",
        "--data-urlencode", f"filename={dst.stem}",
        "--data-urlencode", "type=art_file",
        "--data-urlencode", "all_downloads=1",
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


# ── orchestration ──────────────────────────────────────────────────────────────
def run(out: Path, *, chunk_size: int, limit: int | None, delay: float, extract: bool) -> None:
    meta_dir, chunks_dir, objs_dir = out / "metadata", out / "chunks", out / "objs"
    for d in (out, meta_dir, chunks_dir):
        d.mkdir(parents=True, exist_ok=True)

    cookies = out / "_session_cookies.txt"
    get_session(cookies)
    fetch_metadata(meta_dir)

    bp_ids = load_concept_ids(meta_dir)
    if limit:
        bp_ids = bp_ids[:limit]
    chunks = [bp_ids[i:i + chunk_size] for i in range(0, len(bp_ids), chunk_size)]
    logger.info("%d concept ids → %d chunks of %d", len(bp_ids), len(chunks), chunk_size)

    n_skipped = n_done = n_fail = 0
    for ci, chunk in enumerate(chunks):
        zpath = chunks_dir / f"chunk_{ci:04d}.zip"
        if _zip_ok(zpath):
            n_skipped += 1
            continue
        try:
            art_ids, rep_ids = resolve_pallet(chunk, cookies)
            if not art_ids:
                logger.warning("chunk %04d: pallet returned 0 art_ids (container-only concepts)", ci)
                zpath.with_suffix(".empty").write_text("no art_ids\n")
                continue
            download_zip(art_ids, rep_ids, zpath, cookies)
            if not _zip_ok(zpath):
                raise RuntimeError("downloaded file is not a valid non-empty zip")
            with zipfile.ZipFile(zpath) as z:
                n_obj = sum(1 for n in z.namelist() if n.lower().endswith(".obj"))
            n_done += 1
            logger.info("chunk %04d/%d: %d concepts → %d FJ → %d OBJ (%.1f MB)",
                        ci, len(chunks), len(chunk), len(art_ids), n_obj,
                        zpath.stat().st_size / 1e6)
        except Exception as e:
            n_fail += 1
            logger.error("chunk %04d FAILED: %s", ci, e)
            zpath.unlink(missing_ok=True)
        time.sleep(delay)

    logger.info("download phase done: %d new, %d skipped, %d failed", n_done, n_skipped, n_fail)
    if extract:
        extract_all(chunks_dir, objs_dir)


def extract_all(chunks_dir: Path, objs_dir: Path) -> int:
    """Unzip every chunk into a flat, FJ-deduplicated objs/ folder."""
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
                name = Path(member).name           # strip the per-zip subfolder
                fj = name.split("_", 1)[0]         # FJxxxx — the unique element id
                if fj in seen:
                    continue
                seen.add(fj)
                (objs_dir / name).write_bytes(z.read(member))
                n += 1
    logger.info("extracted %d unique OBJ meshes → %s", n, objs_dir)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("bodyparts3d_4.3"))
    ap.add_argument("--chunk-size", type=int, default=40, help="concept ids per request batch")
    ap.add_argument("--limit", type=int, default=None, help="only the first N concepts (smoke test)")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests (be polite)")
    ap.add_argument("--no-extract", action="store_true", help="download chunks only; skip unzip")
    ap.add_argument("--extract-only", action="store_true", help="skip download; (re)extract existing chunks")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    fh = logging.FileHandler(args.out / "download.log")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    logging.getLogger().addHandler(fh)

    if args.extract_only:
        extract_all(args.out / "chunks", args.out / "objs")
        return 0
    run(args.out, chunk_size=args.chunk_size, limit=args.limit,
        delay=args.delay, extract=not args.no_extract)
    return 0


if __name__ == "__main__":
    sys.exit(main())
