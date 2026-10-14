# Literature Library deployment code

Target installation, updates, weekly backup templates, retention limits and
the maintained-code recommendation are in [operations](docs/operations.md).

This repository contains the application, dependency locks, machine contracts,
and a small deployment guide. Research assets and mutable runtime state are
restored from private OSS snapshots; they do not belong in this Git tree.

PDF ingestion requires an explicit purpose through the UI, API or CLI. Exact
duplicates append purpose history to the existing Work. See the
[operation and retry rules](docs/operations.md#required-ingest-purpose).

Use the [unified recovery entry](docs/deployment.md). The [architecture](docs/architecture.md)
describes the code/data boundary. `python scripts/check_release.py` checks this
publication scope. The full research workspace's `check_docs.py` checks its
research governance links; it is a separate check and is not claimed to pass
on this intentionally smaller deployment repository.

Host Agent documentation workflow: [Project Doc Maintenance](skills/project-doc-maintenance/SKILL.md). Installation and scope: [deployment guide](docs/deployment.md#project-documentation-maintenance).
