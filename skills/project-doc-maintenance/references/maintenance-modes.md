# Maintenance modes

Use the smallest mode that answers the request. Local project instructions and user scope take precedence over this generic guide.

## Bootstrap and Adopt handoffs

For a human-facing Bootstrap or Adopt handoff, briefly connect intended outcomes with the authoritative sources or evidence that show current support and dates, then point out the open gaps. Use prose or a small linked map when useful; do not duplicate a live status source or require a fixed table.

When consolidating in-scope confirmed needs or decisions, preserve them in attributable form with source pointers and do a lightweight check against the relevant source passages to catch omissions. Keep unresolved or unreviewed portions visible, and note material impacts when source inputs change. This does not call for copying full project histories or every file.

## Bootstrap

For a project without a usable documentation map:

1. Identify intended users, the outcomes they need, important workflows, and the project’s main implementation boundaries from available sources.
2. Inventory existing notes, instructions, code entrypoints, and dated operational evidence before proposing new documents.
3. Draft a small map of authoritative sources and unresolved questions. Use only the document roles the project needs; do not impose a fixed count, hierarchy, technology stack, or maturity process.
4. Separate confirmed needs from proposals and unknowns. Link needs to relevant workflows and implementation evidence where useful.
5. Add a short agent entrypoint only when it helps future work find those sources.

## Adopt

For an existing project:

1. Read local instructions and the entrypoints relevant to the requested area.
2. Map which documents own requirements, workflows, architecture, live status, decisions, and historical evidence. These roles may be combined or named differently.
3. Check dates, sources, and supersession. Preserve useful material and review history; do not rewrite an old report as though it knew later facts.
4. Record gaps and conflicts without promoting an assistant proposal or implementation detail into a user decision.
5. Prefer updating the existing authoritative source over copying it into a new index.

## Sync

For a real change to a need, workflow, system boundary, implementation, or operating state:

1. Trace the change to the source decision or evidence and identify affected documents.
2. Update only the authoritative documents whose claims or links changed. Keep dynamic state in the project’s designated state source rather than repeating it across guides.
3. Preserve the evidence date and scope. For runtime changes, require runtime evidence; static code changes alone do not establish deployment.
4. Check dependent documents and links. If no documentation claim changes, report a no-op and explain why.
5. Summarize the change, evidence, validation, remaining uncertainty, and documents not changed.

## Review

For a requested drift or quality review:

1. Keep the review read-only unless editing is separately requested.
2. Look for conflicting authority, stale “current” claims, broken paths or anchors, semantic links whose target content moved, duplicated status facts, and claims that exceed their evidence.
3. Cite the file or section, the evidence, the impact, and a concrete correction.
4. Separate confirmed defects from possible drift and from items requiring an owner’s decision.
5. If no actionable issue is found, report that result and the inspection boundary without changing files.
