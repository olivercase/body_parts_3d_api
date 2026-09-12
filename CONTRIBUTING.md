# Contributing

Thanks for considering it. This is a small, single-maintainer project, so the
bar is simple: changes should be easy to check and hard to misread.

## Before you start

For anything beyond a typo, **open an issue first**. Two categories in particular
are worth discussing before you write code:

* **Anything touching the download protocol.** The endpoints this tool drives are
  undocumented, and the correctness argument for "these meshes are version 4.3" is
  subtle — see the README section on why the standard routes don't give you 4.3.
  A change that seems harmless can quietly make the set version-ambiguous.
* **New or changed selection groups.** A group in `bp3d_subset.py` is a claim
  about what an anatomical structure consists of. Say which BodyParts3D elements
  you are adding and why they make up that structure.

## Development setup

```bash
git clone https://github.com/olivercase/body_parts_3d_api.git
cd body_parts_3d_api
pip install -e ".[dev]"
```

The meshes live in Git LFS. For code work you do not need them — clone with
`GIT_LFS_SKIP_SMUDGE=1` and the tests will still run, because they read
`MANIFEST.csv` rather than geometry. Run `git lfs pull` when you actually want
the meshes.

## Before you open a pull request

```bash
make ci     # ruff check, ruff format --check, pytest
```

CI runs exactly this, so a green `make ci` locally means a green CI.

* **Every behaviour change gets a test.** The tests deliberately need neither the
  network nor the meshes; keep it that way, so they stay fast and deterministic.
* **Don't loosen a selection pattern without saying so.** `tests/` pins the size
  of each built-in group precisely because a pattern that silently widens or
  narrows is invisible otherwise. If a count changes, change the assertion in the
  same commit and explain why in the message.
* **Comments say why, not what.** The code says what.
* **Commit messages**: a short imperative subject, then prose explaining the
  reasoning — what was wrong, what you did about it, and what you decided not to
  do. Rationale in the message beats rationale nowhere.

## Licensing

Code contributions are accepted under the **MIT** licence of this repository.

The anatomical meshes are **not** yours or ours to relicense: BodyParts3D is
© Database Center for Life Science (DBCLS), licensed **CC BY-SA 2.1 Japan**. Do
not add mesh data from another source unless you can state its provenance and
licence, and do not remove the attribution.

## Code of conduct

Participation is covered by the [Code of Conduct](CODE_OF_CONDUCT.md).
