# Literature Library deployment code

This repository contains the application, dependency locks, machine contracts,
and a small deployment guide. Research assets and mutable runtime state are
restored from private OSS snapshots; they do not belong in this Git tree.

Use the [unified recovery entry](docs/deployment.md). The [architecture](docs/architecture.md)
describes the code/data boundary. `python scripts/check_release.py` checks this
publication scope. The full research workspace's `check_docs.py` checks its
research governance links; it is a separate check and is not claimed to pass
on this intentionally smaller deployment repository.
