# BodyParts3D 4.3 downloader

A small, dependency-light Python tool that downloads the **complete, full-resolution
BodyParts3D / Anatomography version 4.3** anatomical mesh set as Wavefront `.obj`
files — every organ, muscle, bone, blood vessel, nerve, etc. (~2,200+ element meshes).

As far as we can tell, **there is no public bulk source for the 4.3 meshes and no
existing tool that retrieves them** — the official downloads only offer the older,
polygon-reduced 4.0 set, and the documented API can't return meshes at all. This
tool gets the 4.3 geometry by driving the Anatomography web viewer's own
(undocumented) download endpoints.

> **Data © Database Center for Life Science (DBCLS).** BodyParts3D is licensed
> **CC-BY-SA 2.1 Japan**. You must attribute DBCLS / BodyParts3D when you
> redistribute the meshes. This repository's *code* is MIT-licensed (see `LICENSE`).

---

## Why the standard routes don't work

BodyParts3D officially exposes two ways to get data. Neither yields the 4.3 meshes:

### 1. The bulk archive — wrong version, reduced geometry
The mirror at `dbarchive.biosciencedbc.jp/data/bodyparts3d/` (HTTP **and** FTP, every
dated release, with `LATEST → 20130619`) contains **only**:

```
isa_BP3D_4.0_obj_99.zip      partof_BP3D_4.0_obj_99.zip
isa_parts_list_e.txt         isa_element_parts.txt        (+ partof_* and relation lists)
```

That is **version 4.0**, and the `_99` means **99% polygon-reduced**. There is no
4.1/4.3/5.0 archive and no full-resolution archive anywhere on the mirror. So the
bulk route can't give you 4.3 at all.

### 2. The documented Web API — renders pictures, not meshes
The official **Anatomography Web API** (`lifesciencedb.jp/bp3d/info_en/webapi/`)
provides exactly these methods:

| Method          | Returns                |
|-----------------|------------------------|
| `API/image`     | a PNG image            |
| `API/animation` | an animated GIF        |
| `API/map`       | coordinate JSON        |
| `API/focus`     | camera-parameter JSON  |
| `API/pick`      | pick-coordinate JSON   |

There is **no method that returns a 3D model / OBJ file** — it is a server-side
*rendering* API. Its `Version` parameter is also documented only up to `"4.1"`.
So the documented API cannot return mesh geometry, in any version.

### The conclusion
The full-resolution **4.3** meshes live only inside the interactive viewer at
`lifesciencedb.jp/bp3d`. The viewer downloads them through two **undocumented** CGI
endpoints (the same ones its "download selected parts" button uses). This tool
reverse-engineers and drives those endpoints to fetch the whole set headlessly.

---

## How it works (the undocumented two-step API)

Identifiers: `FMA…` = Foundational Model of Anatomy concept id · `BP…` = BodyParts3D
representation/concept id · `FJ…` = element-file id (one `.obj` per `FJ`).

**Step 1 — expand a concept into its element files.** POST to
`download-pallet-art_file.cgi`. The `rep_ids` field is a **JSON array of objects**
(sending plain strings fails with `Can't use string as a HASH ref`):

```bash
curl -s 'https://lifesciencedb.jp/bp3d/download-pallet-art_file.cgi' \
  --data-urlencode 'rep_ids=[{"rep_id":"BP22970","opacity":1,"exclude":false}]'
# → {"art_ids":["FJ4039","FJ1381","FJ3981"],"rep_ids":["BP23034","BP23210"],"success":true}
```

**Step 2 — download the paired ids as a ZIP of OBJs.** POST to `download.cgi`:

```bash
curl -s -o out.zip 'https://lifesciencedb.jp/bp3d/download.cgi' \
  --data-urlencode 'rep_id=["BP23034","BP23210"]' \
  --data-urlencode 'ids=["FJ4039","FJ1381","FJ3981"]' \
  --data-urlencode 'filename=out' \
  --data-urlencode 'type=art_file' \
  --data-urlencode 'all_downloads=1'
# → application/zip containing e.g. FJ4039_BP23210_FMA50881_Right trochlear nerve.obj
#   (file timestamps are 2014-03, i.e. the 4.3 build)
```

The complete list of concept ids to feed Step 1 comes from the authoritative
`isa_parts_list_e.txt` (downloaded automatically from the dbarchive mirror — that
metadata *is* published, just not the 4.3 geometry). The script batches concepts,
runs Step 1 → Step 2 per batch, then unzips everything into a flat, de-duplicated
`objs/` folder.

---

## Usage

Requirements: **Python 3.9+** and **`curl`** on your `PATH`. No third-party Python
packages.

```bash
python3 download_bodyparts3d.py                 # full run → ./bodyparts3d_4.3/objs/
python3 download_bodyparts3d.py --limit 80      # smoke test: first 80 concepts
python3 download_bodyparts3d.py --chunk-size 40 # concepts per request batch
python3 download_bodyparts3d.py --no-extract    # download zips only
python3 download_bodyparts3d.py --extract-only  # just (re)unzip existing chunks
```

Output layout:

```
bodyparts3d_4.3/
├── metadata/   isa_parts_list_e.txt, isa_element_parts.txt   (id ↔ FMA ↔ name maps)
├── chunks/     chunk_0000.zip, chunk_0001.zip, …             (raw downloads, resumable)
├── objs/       FJ…_BP…_FMA…_<name>.obj                       (final, deduped, flat)
└── download.log
```

The run is **resumable**: any chunk whose `.zip` already exists and unzips cleanly is
skipped, so an interrupted run costs nothing. Requests are sequential with a small
delay and automatic retries/backoff.

### Filename convention
Each mesh is named `FJ<file>_BP<rep>_FMA<concept>_<human readable name>.obj`, so you
can map any mesh back to its FMA concept and walk the FMA/BodyParts3D hierarchy using
the files in `metadata/` (`isa_element_parts.txt` links `FMA → name → FJ`).

---

## Please be a good citizen

These endpoints are an undocumented part of a public research service run by DBCLS.
Keep the default polite settings (sequential requests, delay, retries), don't
parallelise aggressively, and don't re-hammer the server once you have the data —
the full set is only a few hundred MB and downloads once. Respect the
[BodyParts3D license](https://dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html)
and cite DBCLS.

## Attribution / citation

> BodyParts3D, © The Database Center for Life Science (DBCLS), licensed under
> CC Attribution-Share Alike 2.1 Japan.
> Mitsuhashi N, Fujieda K, Tamura T, Kawamoto S, Takagi T, Okubo K. *BodyParts3D:
> 3D structure database for anatomical concepts.* Nucleic Acids Res. 2009.

## Links
- Viewer: https://lifesciencedb.jp/bp3d/?lng=en
- Documented (image-only) Web API: https://lifesciencedb.jp/bp3d/info_en/webapi/
- Official bulk archive (4.0 only): https://dbarchive.biosciencedbc.jp/en/bodyparts3d/download.html
- License: https://dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html
