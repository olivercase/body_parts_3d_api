## What this changes

<!-- What was wrong or missing, and what you did about it. -->

## Why this way

<!-- The reasoning, and anything you considered and rejected. -->

## How it was checked

<!-- Paste the `make ci` tail. Say what you could NOT run and why -- an
     unrun check stated is fine, an unrun check implied is not. -->

```
```

## Checklist

- [ ] `make ci` is green (ruff check, ruff format --check, pytest)
- [ ] Behaviour changes have a test; the tests still need neither network nor meshes
- [ ] If a selection group changed size, the pinned count in `tests/` changed with it, and the commit says why
- [ ] Nothing about the download protocol changed without saying so — the 4.3 version argument is in the README and is easy to break quietly
- [ ] No mesh data added whose provenance and licence I cannot state
- [ ] Comments explain *why*, not *what*
