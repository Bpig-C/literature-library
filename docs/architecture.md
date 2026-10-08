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
