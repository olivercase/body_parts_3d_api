# BodyParts3D 4.3 — complete, verified mesh set + downloader

The **complete, full-resolution BodyParts3D / Anatomography version 4.3** anatomical
mesh set as Wavefront `.obj` files — **3,210 element meshes** (every FMA-mapped
organ, muscle, bone, blood vessel, nerve, cartilage, etc.), plus the small,
dependency-light Python tool that downloads and verifies them.

The meshes themselves are committed here via **Git LFS** (`meshes/*.obj`), so you can
clone the data directly — or re-fetch from source with the script.

> **Data © Database Center for Life Science (DBCLS).** BodyParts3D is licensed
> **CC-BY-SA 2.1 Japan**. You must attribute DBCLS / BodyParts3D when you
> redistribute the meshes. This repository's *code* is MIT-licensed (see `LICENSE`).

---

## What's in here

```
meshes/        3,210 × FJ…_BP…_FMA…_<name>.obj   (full-res 4.3 geometry, via Git LFS)
metadata/
  FMA2Obj.txt  the authoritative, version-stamped 4.3 manifest (FMA → FJ components)
  obj2FMA.html the FJ ↔ BP (rep_id) lookup used to drive the download endpoint
MANIFEST.csv   one row per mesh: fj_id, bp_id, fma_id, name, faces, verts, bytes, mtime
download_bodyparts3d_4.3.py   the downloader + verifier
```

Every mesh in `meshes/` is a member of the 4.3 object set as declared by
`FMA2Obj.txt` (`# Data Version 4.3 / # Objects set 4.3`), and every one has been
loaded and validated (non-empty geometry) — see `MANIFEST.csv`.

### Getting the meshes

```bash
git lfs install
git clone git@github.com:olivercase/body_parts_3d_api.git
# meshes/ now contains all 3,210 .obj files
```

(Without Git LFS the `.obj` files clone as small pointer text files; run
`git lfs pull` after installing LFS.)

---

## Why the standard routes don't give you 4.3

BodyParts3D officially exposes two ways to get data; neither yields the 4.3 meshes:

1. **The bulk archive** at `dbarchive.biosciencedbc.jp/data/bodyparts3d/` ships only
   `isa_BP3D_4.0_obj_99.zip` — i.e. version **4.0**, **99% polygon-reduced**. No
   4.1/4.3/5.0 archive, no full-resolution archive.
2. **The documented Web API** (`lifesciencedb.jp/bp3d/info_en/webapi/`) renders
   *images*, not meshes.

So the 4.3 geometry is only obtainable by driving the Anatomography viewer's own
(undocumented) endpoints, which is what this tool does.

---

## How it works (the correctness-critical part: getting the version right)

The hard problem is not downloading a mesh — it's knowing the download is **4.3** and
nothing else. Three facts make that subtle:

- **`obj2FMA` (`upload-all-list`) ignores its `version` parameter.** Requesting it for
  `version=4.0` vs `version=4.3` returns byte-identical output — a 13,312-row master
  *superset* spanning all versions (it also includes non-canonical `MM`/`CX` series).
  It is **not** a version-specific list; use it only for the FJ→BP lookup.
- **The `download.cgi` endpoint ignores `mv_id`/`version` too.** A given `FJ…`
  element id deterministically maps to exactly one full-resolution geometry file.
  The version is therefore fixed by **which FJ ids you ask for**, not by any flag.
- **File modification dates are not version markers.** Many 4.3 meshes carry
  2011–2013 modeling timestamps; 4.3 simply reuses unchanged geometry for parts that
  weren't re-modeled. Membership in the 4.3 manifest — not the date — is what makes a
  mesh "4.3".

**The authoritative 4.3 manifest** is therefore the linchpin:

```
GET get-info.cgi?version=4.3&cmd=concept-objfiles-list   →  ZIP containing FMA2Obj.txt
```

whose header is explicitly version-stamped:

```
# Data Version  4.3
# Objects set   4.3
# Tree version  FMA3.0
# FMA ID   is_a/part_of   model component
FMA10014   is_a   FJ3175
FMA10446   is_a   FJ3202+FJ3203+…
```

The set of `FJ…` "model component" ids in that file **is** the version-4.3 object set
(3,210 unique FJ). The tool:

1. Fetches `FMA2Obj.txt` (the 4.3 FJ universe) and `obj2FMA` (FJ → BP `rep_id`).
2. Batches the FJ ids to `download.cgi`
   (`ids=[FJ…]&rep_id=[BP…]&type=art_file&all_downloads=1`), which returns a ZIP of
   `FJ…_BP…_FMA…_<name>.obj`.
3. Extracts **only** in-manifest FJ (a batch can return sibling elements), deduped.
4. **Verifies**: confirms all 3,210 manifest FJ are present, loads each in `trimesh`,
   and writes `MANIFEST.csv`.

> An earlier approach seeded concept ids from the dbarchive `isa_parts_list_e.txt` —
> that's the **4.0** parts list, which is both incomplete for 4.3 and
> version-ambiguous. This tool does not use it.

---

## Usage

```bash
pip install trimesh                # only needed for the verify step
python3 download_bodyparts3d_4.3.py                 # full fresh run + verify
python3 download_bodyparts3d_4.3.py --limit 80      # smoke test (first N FJ)
python3 download_bodyparts3d_4.3.py --chunk-size 50 # tune batch size
python3 download_bodyparts3d_4.3.py --verify-only   # re-verify an existing meshes set
```

Output goes under `data/bodyparts3d/raw_4.3/` by default (`--out` to change):
`metadata/`, `chunks/` (raw zips, resumable), `objs/` (flat deduped meshes),
`MANIFEST.csv`, `download.log`. The run is resumable (a valid chunk zip is skipped)
and polite (sequential requests, small delay, retries with backoff).

---

## Attribution

BodyParts3D, © Database Center for Life Science (DBCLS), licensed CC-BY-SA 2.1 Japan.
If you use or redistribute the meshes, cite BodyParts3D / DBCLS and preserve the
share-alike license. Repository code is MIT-licensed.
