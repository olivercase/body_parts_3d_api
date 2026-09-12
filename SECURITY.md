# Security policy

## Scope

This repository holds anatomical mesh data and two command-line tools that fetch
and select it. It has no server, no authentication and no user accounts, so the
plausible security concerns are narrow but real:

* **The downloader executes `curl` and unpacks archives from a remote service.**
  A flaw in how a response is handled — path traversal when extracting a ZIP, an
  unvalidated redirect, a command injection through an argument — would matter.
* **The mesh files themselves** are parsed by whatever downstream tool you point
  at them (`trimesh` here). A malformed mesh that crashes or exploits a parser is
  in scope to the extent that this repository is the thing distributing it.
* **Dependency vulnerabilities** in the small dependency set.

Out of scope: the availability, correctness or licensing of the upstream
BodyParts3D service, which this project does not control.

## Supported versions

The latest release and the `main` branch receive fixes. Older tags do not.

| Version | Supported |
| --- | --- |
| latest release / `main` | ✅ |
| earlier tags | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through GitHub:
[open a security advisory](https://github.com/olivercase/body_parts_3d_api/security/advisories/new).
That channel is private to you and the maintainer.

Please include:

* what the problem is and what an attacker could achieve with it,
* the steps or input that reproduce it,
* the version or commit you tested, and your Python and OS versions.

You can expect an acknowledgement within **7 days** and an assessment within
**30 days**. If a fix is warranted it will be released and the advisory published,
crediting you unless you would rather not be named. This is a single-maintainer
research project, not a funded programme: there is no bounty, and timelines are
best-effort.

Please give a reasonable period for a fix before disclosing publicly.
