# Code and runtime boundaries

Git holds application code, reproducible Python/Node locks, machine contracts,
necessary tests, and these deployment/architecture notes. OSS holds long-term
PDF/parse/JSON/image objects plus versioned coherent DB snapshots, required drafts,
scientific presentation/configuration and non-sensitive runtime configuration.
AccessKey/session/API token values remain in environment or a credential manager.

The unified release manifest connects all sources through one exact release:
Git commit/tree fingerprints, frontend object, runtime essentials and fixed asset
index. Snapshot SQLite backups use both DB write locks. Restoration checks all
essential SHA/size and the fixed registry index, relocates transport paths only,
preserves scientific payload/text/review/adoption, and publishes a new target
after validation. Cold asset consumption uses the unchanged immutable registry
and bounded cache; it does not download every asset permanently by default.

Reading and ontology display records are business data. Generic frontend modules
load their verified JSON from restored local runtime assets before Vue mounts.
Machine ontology/proposal/review-card data and original digest source bytes are
also runtime assets, maintaining existing draft binding without changing the
science. Missing essential assets produce an explicit restore/application error.

Publication checks verify the small Git scope and clean root history. Research
governance checks and historical evidence remain in the complete research
workspace; copying scientific reports into Git to satisfy those links would
violate this publication boundary. Neither check establishes scientific approval.

## Ingest purpose history

Every executed PDF ingest requires a nonblank purpose (maximum 2000 characters).
The shared ingestion core enforces the rule for upload, inbox execution, the
local CLI and collector promotion. Scanning remains read-only and needs no purpose.
One batch purpose applies only to the submitted or selected files. Exact SHA
duplicates reuse their Work/source identity and append a purpose without creating
another parse task. Ambiguous matches retain the existing review rules; purposes
do not restore quarantined Works.

`api/ingest_notes.py` owns the catalog's `ingest_notes` and
`ingest_purpose_requests` additive tables. A write operation initializes them
inside the existing authorized write path; reads never migrate the catalog.
New Work/source/parse rows and their purpose records commit in the same catalog
transaction. File copies and immutable asset publication remain separate steps;
failures return an error and retain staged inputs for recovery. Failed publication
may leave committed catalog rows and purposes, so retry must retain its request ID.

The stable request ID binds the normalized purpose and the exact SHA set (or Work
and optional source selector for direct append). Reusing the ID with different content returns a conflict.
The unique `(request_id, work_id)` constraint prevents repeated notes in a batch
or retry. Separate operations may use the same text. Historical notes without a
request receipt retain their original IDs; full input binding starts with new
receipts. Actor remains empty when the transport supplies no trusted human identity.

These tables travel with the catalog SQLite backup; no separate asset binding is
needed. Existing PDF storage, research schema and A/R records are unaffected.
