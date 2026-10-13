---
name: project-doc-maintenance
description: Build, adopt, review, or sync concise project documentation when people and agents need a shared map of requirements, business workflows, design/architecture, and dated state. Also use for the documentation impact of authorized changes to those sources; skip unrelated tasks.
metadata:
  version: "0.1.3"
  short-description: Maintain traceable project documentation
---

# Project document maintenance

Help people and agents understand what a project is for, how work flows, how it is structured, and what evidence says about its current state. Keep one authoritative source for each kind of fact, and adapt to the project’s vocabulary and existing entrypoints.

## Choose the mode

Read only the relevant mode in [maintenance modes](references/maintenance-modes.md):

- **Bootstrap** when a project lacks a usable documentation map.
- **Adopt** when taking over documentation created by people or tools.
- **Sync** for the documentation-maintenance part of an authorized project task when a real change may affect documented needs, workflows, structure, entrypoints, or dated state. Check affected authoritative sources; update them or report an evidence-based no-op.
- **Review** when asked to inspect drift. Review is read-only unless the user separately asks for edits.

Read [evidence and links](references/evidence-and-links.md) when sources conflict, status claims cross dates or environments, or links point to historical objects. Use the [AGENTS entry template](references/agents-entry-template.md) only when a project needs a small maintenance entrypoint.

## Shared maintenance loop

1. Read the project’s local instructions and task-relevant entrypoints. Do not make the entire documentation set mandatory for every task.
2. Identify the requested scope, the source evidence, and which authoritative documents the change can affect. Reuse existing documents and live state sources; do not create a parallel status ledger by default.
3. Preserve the distinction between a user decision, an unresolved question, a proposal, static code evidence, runtime evidence, review evidence, and a scientific or human judgment. A code defect alone does not establish a new user requirement.
4. Update each affected authoritative document, or state why it is unaffected. If the evidence and documentation already agree, make no changes and report a no-op.
5. Before delivery, inspect the focused diff, check cross-document consistency, and verify both that each link resolves and that its target still contains the meaning the link claims. Run the project’s documentation checker when one exists; do not substitute it for semantic review.

## Operating boundaries

- Keep dates and provenance with claims. Separate active facts from dated snapshots and historical decisions.
- Distinguish candidate code from the main project, static inspection from runtime behavior, and software state from research validity or human adoption.
- When sources conflict, inspect the most direct available evidence and preserve uncertainty if it cannot be resolved. Do not silently choose the newest text or infer a decision.
- Prefer stable IDs, real section anchors, and reproducible versioned locations over line numbers. A commit-and-path reference should include a way to read the object.
- Respect project permissions and existing review history. A read-only audit writes nothing; a no-op sync does not create churn.
- This skill applies to relevant documentation tasks and to the documentation-maintenance portion of authorized project tasks when real changes may affect authoritative documents. Unrelated project tasks do not trigger a repository-wide documentation rewrite. It is not a background watcher and does not authorize code, data, or external-system changes.

## Delivery

State the mode, scope, source dates, documents updated or left unchanged, validation performed, unresolved conflicts, and any approval still needed. Do not describe static checks as runtime, product, scientific, or user-acceptance tests.
