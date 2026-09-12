# BodyParts3D 4.3 — complete, verified mesh set, downloader and subset selector

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22727173.svg)](https://doi.org/10.5281/zenodo.22727173)
[![CI](https://github.com/olivercase/body_parts_3d_api/actions/workflows/ci.yml/badge.svg)](https://github.com/olivercase/body_parts_3d_api/actions/workflows/ci.yml)
[![Code licence: MIT](https://img.shields.io/badge/code%20licence-MIT-blue.svg)](LICENSE)
[![Data licence: CC BY-SA 2.1 JP](https://img.shields.io/badge/data%20licence-CC%20BY--SA%202.1%20JP-lightgrey.svg)](https://creativecommons.org/licenses/by-sa/2.1/jp/)

The **complete, full-resolution BodyParts3D / Anatomography version 4.3** anatomical
mesh set as Wavefront `.obj` files — **3,210 element meshes** (every FMA-mapped
organ, muscle, bone, blood vessel, nerve, cartilage, etc.), plus the small,
dependency-light Python tool that downloads and verifies them.

The meshes themselves are committed here via **Git LFS** (`meshes/*.obj`), so you can
clone the data directly — or re-fetch from source with the script. A second tool,
`bp3d_subset.py`, pulls out just the structures you actually want (a brain, a gut, a
pair of lungs) instead of all 3,210.

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
bp3d_subset.py                select a named subset (see below)
tests/                        unit tests for the selector (no network, no meshes)
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

## Selecting a subset

Most of the time you do not want 3,210 meshes — you want a brain, a gut and a pair of
lungs. `bp3d_subset.py` selects by regular expression over the FMA name each element
carries in `MANIFEST.csv`, and either copies those meshes out of the set in this
repository or fetches only those from source.

```bash
python3 bp3d_subset.py --list                         # what each group selects
python3 bp3d_subset.py --group heart --group lungs --out subset
python3 bp3d_subset.py --out subset                   # every built-in group
python3 bp3d_subset.py --group gut --download --out subset   # fetch, don't copy
python3 bp3d_subset.py --pattern '^(left|right) .*gyrus$' --name gyri --out subset
```

Output is `subset/<group>/*.obj` plus a `subset/MANIFEST.csv` recording group, FJ/BP/FMA
ids, name, path and size — written from what actually landed on disk, so it cannot
claim geometry that was never obtained.

### Built-in groups

| group | meshes | what it means |
|---|---:|---|
| `brain` | 64 | cerebral gyri + occipital lobes, thalamus, insula, hippocampus, cerebellum, pons, medulla |
| `spine` | 24 | cervical, thoracic and lumbar vertebrae, sacrum, coccyx |
| `spinal_cord` | 1 | neural tissue of the spinal cord |
| `vagus_nerve` | 2 | trunk of the left and right vagus |
| `heart` | 3 | ventricular wall, left and right atrial walls |
| `lungs` | 18 | parenchyma, one mesh per bronchopulmonary segment |
| `gut` | 61 | stomach, duodenum, jejunum, ileum, colon, rectum |
| `blood_vessel` | 12 | aorta, venae cavae, pulmonary trunk, carotids, jugulars |
| `leg_muscle` | 36 | gluteal, quadriceps, hamstring, calf and shin muscles |
| `skin` | 1 | whole-body skin surface |

A group is usually several elements, because 4.3 often has no single mesh for a whole
organ: the cerebrum is supplied as gyri, the lung per bronchopulmonary segment, the
heart as chamber walls. `--list` prints exactly which elements a group resolves to
before anything is written, and the patterns themselves are in `GROUPS` at the top of
the script — a group is meant to be auditable, not magic.

> Two catalogue concepts (`FJ1791`/`FJ1792`, left and right occipital lobe) are
> grouping nodes with no geometry of their own and are not in the 4.3 object set; the
> `brain` group covers that territory through the lateral occipital and lingual gyri.

---

## Development

```bash
pip install -e ".[dev]"
make lint    # ruff check + ruff format --check
make test    # pytest
make ci      # both
```

The tests cover the selector's decision-making — pattern matching, de-duplication,
manifest validation, and a guard that every built-in group still resolves to the
number of meshes documented above. They need neither the network nor the meshes, so
they run on a `GIT_LFS_SKIP_SMUDGE=1` clone, which is what CI does.

---

## Citation

If you use this, cite the software **and** BodyParts3D/DBCLS for the anatomical data.
The two are separate: the code here is MIT, the meshes are CC BY-SA 2.1 Japan.

The software has a DOI that always resolves to the latest release:

> Case, O. *BodyParts3D 4.3: complete verified mesh set, downloader and subset
> selector*. Zenodo. https://doi.org/10.5281/zenodo.22727173

`CITATION.cff` carries the same in machine-readable form — GitHub's "Cite this
repository" button reads it. To cite one specific version, use that release's own DOI
from the [Zenodo record](https://doi.org/10.5281/zenodo.22727173) rather than the one above.

---

## Attribution

BodyParts3D, © Database Center for Life Science (DBCLS), licensed CC-BY-SA 2.1 Japan.
If you use or redistribute the meshes, cite BodyParts3D / DBCLS and preserve the
share-alike license. Repository code is MIT-licensed.
