# Single maintained code line and target operations

发布和 epoch 交接使用 [LitLib Release Operations](../skills/litlib-release-operations/SKILL.md)。它区分产品版本与不可变发布身份，并要求人工授权后才执行推送和线上写者切换。

## Required ingest purpose

Upload, inbox confirmation, selected pipeline files and candidate promotion now
require an explicit purpose. The form applies one purpose to that operation's
files. A Work detail page shows paginated history and permits direct append.
Old Works do not require retroactive placeholder purposes. Older API clients must
send `purpose`; missing fields return 422, blank/overlong text returns 400.

```powershell
python scripts/literature_ingest.py --library-root C:/explicit/library --execute --purpose "用于论文第三章案例分析" --request-id review-chapter3-001
```

Use the existing restored-runtime write wrapper on an immutable production slot.
Retain the request ID and purpose when retrying; change the ID for a new operation.
Dry-run omits `--execute` and needs no purpose. API uploads accept multipart
`purpose` and `request_id`; `/api/ingest/execute` accepts the same JSON fields plus
`leave_inbox` and optional SHA `file_ids`. Upload affects only its submitted files;
execute without selectors scans the entire inbox. UI forms retain the request ID
on failure within the same page session; callers should record it for later retry.

`GET /api/works/{id}/ingest-notes?limit=50&offset=0` reads history.
`POST /api/works/{id}/ingest-notes` accepts `purpose`, `request_id`, and an optional
`source_file_id` owned by the Work. Responses include new/already-existing purpose
counts and target Work IDs. Ingest `ingested`/`summary.ingests` counts source files,
not distinct Works. Pure duplicates return success with zero new source files.

The first authorized write adds both purpose tables; queries/dry-run leave legacy
catalogs untouched. The migration does not backfill historical purposes. Continue
using the current authentication/authority gates for writes and deployment.

## Snapshot and recovery safety

Weekly policy does not install a scheduler. Check the actual host task and its
last successful receipt; an enabled service task is not a backup task. Manual
`storage_backup.py --catalog <absolute-path> tick ... --force` bypasses only the
seven-day interval. It still requires stopped writers, a byte budget, a new
verified snapshot and the scheduler lock. Retention never deletes production blobs.

Production inputs require `source_root`. Regenerate a reviewed file selection
using `scripts/snapshot_inputs.py --template <inputs.json> --source-root <current-slot>
--output <new-inputs.json>`. This refreshes both DB paths and working-file hashes.
The maintenance adapter must compare this slot with the actual authenticated
runtime before stopping writers; offline checks alone cannot establish authority.
Run prepare/stage again inside the maintenance window. Do not reuse old tickets
or substitute raw SQLite files after restore. The source guard checks both DBs,
working-file locations and any applied runtime DB environment before publication.

For immediate incident preservation, `scripts/preserve_databases.py --catalog
<catalog.sqlite> --research <research.sqlite> --destination <new-directory>` uses
SQLite Backup, includes committed WAL data, verifies integrity and writes counts
and hashes. It does not stop writers or produce a coherent application release;
use the release maintenance workflow for that. Preserve the original slot and
WAL until all data and asset dependencies have been reconciled. Equal counts do
not establish equal rows or safe deletion.

Prepare and validate the new slot, including full-table preservation and path
relocation, before writer epoch handover. Never edit sealed runtime code. A
backup alone does not switch code, slots or authority epochs.

MinerU cloud and multipart upload requests now label the pinned PDF bytes with a
`.pdf` filename even when the cache path ends in `.asset`. Cloud result polling
uses the same name. No unmanaged cache sibling copy is needed.

## Read-only lookup and source provenance

`POST /api/duplicates/lookup` remains an authenticated query. Only this exact
path (including its trailing-slash redirect) with method POST bypasses the
remote write gate and authority write guard. Other methods and mutating routes
keep their existing gates. Lookup opens the catalog with SQLite `mode=ro` and
`query_only`; registry validation also uses read-only connections. It does not
change journal mode, create a missing database, or contact object storage.
An unavailable/incompatible SQLite catalog returns 503, never a false no-match.
Results describe the local catalog, not proof of the latest global authority.

`POST /api/provenance` selects either `(work_id, source_file_id)` or a separate
Work-level entry when Source is absent. Source existence/ownership and supplied
SHA/byte counts are checked against the registered Source within the write
transaction. Omitted fields retain their values; explicit empty strings clear
text fields, and `known_bytes: null` clears an unknown size. Metadata edits do
not automatically advance `last_verified_at`. Effective changes append snapshots
to `source_provenance_revisions`; identical replays do not append another revision.
The Source identity cannot be patched onto a different entry.

Queries include `history` and `legacy_review_required`. A pre-history row is
preserved verbatim before its first edit and marked `legacy_unverified`; this
cannot recover already overwritten information or certify mixed historical URLs.
No read endpoint initializes/migrates either table. New history/index setup is
additive on authorized writes; existing duplicate identities fail without merging.
To explicitly preserve all legacy rows, first stop writers through the existing
authorized maintenance procedure and take a catalog backup. Against that offline
catalog, the following command creates another fresh SQLite backup before one
transaction of history backfill (never run it directly against a serving slot):

```powershell
python scripts/preserve_source_provenance.py --database C:/offline/literature.sqlite --backup C:/offline/before-provenance.sqlite --apply
```

Backup destinations are never overwritten. Backfill preserves IDs/current rows,
is idempotent, and rolls back on failure; the pre-change backup remains available.
Duplicate identities require manual review, not automatic merging. Original
PDFs, Parse versions, research records and review decisions are unaffected.

`GET /api/provenance-export` now returns **litlib-source-provenance-v2**.
Both v1 variants (the old subset digest and the later full-row digest) remain
historical formats and must not be verified as v2. The v2 SHA256 covers canonical
UTF-8 JSON (`ensure_ascii=False`, sorted keys, compact separators) of `format`,
`digest_scope`, `entry_count`, `total_count`, `truncated` and complete `entries`,
including their history. It excludes `generated_at` and `integrity_sha256`.
Rows sort by Work, Source (NULL treated as empty), then ID; revisions sort by
revision number. `api.source_provenance.verify_catalog` verifies this scope.
This checksum detects changes; it is not an authenticity signature.

Exports use one read snapshot. `limit` is bounded at 5000; `truncated: true`
explicitly indicates an incomplete export. Such a response is not a complete
recovery catalog. Only a missing provenance table yields an empty result;
database/schema errors remain errors. Publishing this code does not execute
backfill or deploy it to a running service.

## Client version checks

Publishing Git code does not change a running server or a downloaded client.
The authenticated `/api/remote/version` endpoint describes the actual running
commit, whether tracked code is dirty, and its capabilities. This release advertises
`ingest_purpose_v1` with `purpose` required, a 2000-character limit and the purpose
history endpoint. It also returns the thin CLI SHA256 and an immutable download
URL when running tracked code is clean. It describes the deployed server, not a
newer unpublished branch or the repository's latest default commit.

```powershell
python scripts/litlib_remote.py --server https://HOST check-version --require-capability ingest_purpose_v1
python scripts/litlib_remote.py --server https://HOST check-version --expected-commit FULL_SERVER_COMMIT
```

The commands return exit 2 for unknown/incompatible protocol, a missing capability
or a commit mismatch. A legacy server with no version endpoint returns an explicit
upgrade indication. Query `/api/research/schema` for release/manifest/environment
identity; environment ID alone does not identify a code version.

Clients can run this check at start and before writes, display changed commits,
and ask the operator to replace their CLI with an exact version after SHA checking.
No automatic code download, replacement or execution occurs. The separately
delivered `remote_cli.py` business wrapper is not this thin CLI: its upload/onboard
commands must be adapted to supply `purpose` and a stable `request_id` before using
the new server. Preserve DPAPI credentials, CA and local user configuration.

## Integration recommendation

Use one continuing minimal code history rooted at the reviewed `404b3a7` release.
The current local candidate is a descendant; no new root or separate permanent
product fork is needed. Bring generic fixes from the broad research workspace
into this line through reviewed commits. Put changing papers, databases,
scientific display assets and deployment-specific credentials outside Git.
After publication is approved, make this maintained line the repository's
default through the host's reviewed branch/default procedure; preserve the old
master as a historical research-workspace reference instead of merging its
broad ancestry. No push, default change or master merge is performed here.

The main Inbox button selector correction and its two confirmation/cancellation
tests are carried into this candidate. Shared `api/main.py` routing/CORS/SPA
behavior is retained alongside immutable startup validation, storage failures
and remote authentication. Existing export adaptations remain: fixed asset
selectors, durable production, dependency locks and separated runtime assets.
Do not copy main's embedded ontology or fixed-root legacy launchers back in.
Local research governance stays in the research workspace; this generic guide
contains operational governance without publishing dated research reports.

## Install and update templates

`deploy/target-config.example.json` is an intentionally invalid, non-sensitive
example. Fill the HTTPS origin, exact reviewed Git commit/manifest locator, new
absolute destination and durable control paths. Sunday 03:00 Asia/Shanghai is
an example, not an accepted user schedule. The template presently targets
Windows/PowerShell; a different target OS needs its service-manager adapter.

Run `python scripts/target_preflight.py --configuration ABSOLUTE_CONFIG` for an
offline schema/path/locator check. Add `--check-files` on the target to compare
the named manifest and maintenance adapter SHA. It reads no credentials and
makes no network request; it cannot prove live TLS, identity, writer stoppage
or remote availability. Tokens and standard SDK credentials are injected into
the service-account process, never added to configuration or task XML.

From the exact trusted code checkout with locked storage dependencies installed:

```powershell
pwsh -File deploy/install-or-update.ps1 -Configuration C:/litlib/control/target-config.json
# Review-only by default; after actual deployment authorization, append -Execute.
```

Installation and each update restore a new release slot using the existing
exact Git+OSS recovery pipeline. Build/publish code and frontend, then produce
the matching coherent release before installation. It preserves the existing
deployment, checks the new slot and starts no service. For switching writes,
freeze the old owner, take the final verified backup, restore that precise
release and hand over to epoch N+1. Same-machine updates also need this explicit
transition if they change the restored manifest. An old slot may remain a
read-only fallback, but cannot resume writing under an obsolete epoch or wrong
handover manifest. Destructive rollback/deletion is not part of this template.

## Weekly backup and failure behavior

The disabled `deploy/backup-task.example.xml` supplies a weekly Windows trigger,
no overlapping task instances and a two-hour task limit. Review timezone,
account and paths; do not import/enable it as part of this engineering phase.
Default policy is seven days and three verified versions. The account must
receive credentials securely on the host; XML contains no token or password.

Implement and hash-review `deploy/maintenance-adapter.example.ps1` for the actual
service manager. Its Enter function must drain/stop all writers and refresh
hashes for the already reviewed named backup inputs without discovering more
files. Return a lease with `stopped=true` only after that maintenance window
exists. Exit restores that precise prior runtime state, including on failure.
The example throws and cannot pretend to stop writers. The wrapper cannot
independently identify every external writer: this is a host integration duty.

```powershell
pwsh -File deploy/backup-weekly.ps1 -Configuration C:/litlib/control/target-config.json
# No backup by default. Reviewed target task uses -Execute after adapter acceptance.
```

Tick runs the existing prepare/stage/publish/readback pipeline with named inputs
and a byte ceiling. A failure retains staged data and the last verified versions;
retry a specific frozen stage with the existing snapshot-publish command rather
than reinterpreting it as new live input. If a later weekly tick creates another
stage, the earlier failure remains recorded; cleanup is a separate review.
Refresh the slot/config commit after a code update. Daily parse publication runs
independently and must not wait for this timer.

## Three versions versus physical reclamation

Today rotation marks old catalog versions retired and discovery returns the
newest three verified versions. Old manifests, DB blobs and working files still
physically remain in OSS. Thus three selectable successful backups is verified;
a maximum of three physical backups or bounded OSS bytes is not yet achieved.
No real deletion executor or scheduled reclamation has been deployed.

A reviewable physical-reclamation operation must use this exact sequence:

1. Enter a verified single-authority maintenance window. Capture epoch,
   catalog revision/SHA, active registry bindings, pending operations and all
   separately pinned release versions. Cold-verify the three retained manifests
   and the complete reference closure, including ZIP parent SHA for members.
2. Add current runtime/handover release, staged/resume operations, explicit
   restore pins and authorized historical holds as protection roots. If a
   pinned older backup prevents a physical three-version bound, report that
   exception and resolve/transition the pin explicitly; never silently delete it.
3. Restrict candidates to exact SHA objects named by retired manifests and
   absent from the full protected closure. Protect every active daily asset,
   even if it is not in the newest backup. Keep discovery/epoch/audit controls;
   do not bulk-delete a namespace or apply an age-only lifecycle rule.
4. Emit an immutable reviewed plan: bucket/namespace, root fingerprints, each
   exact key/SHA/size, reason, total unique bytes, epoch and expiration. The
   existing policy's `unreferenced_candidates` is only an initial proposal;
   it lacks these extra roots and is insufficient for production deletion.
5. After explicit approval of that concrete plan, recheck unchanged roots and
   object identity under the same maintenance window. On drift, missing proof
   or new pins, abort and regenerate. A future deletion executor removes only
   these keys and journals each outcome; missing keys are idempotent, changed
   objects are preserved. Verify the retained three restores and active assets
   before closing the operation.

The production planner is now `scripts/storage_reclamation.py`, with only
`plan` and `validate` commands. It reads the actual registry bindings, durable
operation/staging/producer states and verified/retired snapshot catalog. It
cold-verifies fixed manifests and protects their full closure (including ZIP
parents), the current epoch release, running release, named pending handovers,
unfinished snapshot stages and explicit pins. Failed backup attempts do not
retire successful versions. Excess still-verified versions remain protected
and are reported as `rotation_pending`, never implicitly treated as retired.

Fill `deploy/gc-roots.example.json` after the actual maintenance adapter has
quiesced all writers. Empty lists are declarations requiring real inventory,
not evidence. `runtime_release` and each handover/pin release require exact
key/SHA/bytes. Each pin has `id`, `reason`, `release`. Every direct child of the
configured `stage_parent` must be listed in `snapshot_stages` with exact
`id`, absolute `path`, and `state` (`staged`, `publishing`, `failed`, `completed`).
The frozen receipt, journal and stage bytes are checked; incomplete/unknown
producer closure or unaccounted stage/partial file blocks the whole plan.
The host adapter must inventory every supported stage location and external
pin; this does not detect deliberately unregistered external writers/direct
database access. Such writers remain prohibited/quiescent during maintenance.

```text
python scripts/storage_reclamation.py --catalog ABSOLUTE_CATALOG --roots ABSOLUTE_ROOTS --max-verify-bytes APPROVED_CEILING plan --output NEW_ABSOLUTE_PLAN
python scripts/storage_reclamation.py --catalog ABSOLUTE_CATALOG --roots ABSOLUTE_ROOTS --max-verify-bytes APPROVED_CEILING validate --plan FROZEN_PLAN
```

Invoke via the restored read-only CLI wrapper for applied target environment.
Production deletion is disabled. Authority, producer and scheduler locks are held
through capture and verification; CLI uses host UTC, and plans expire after
30 minutes. Injected dates in the Python planner API are for deterministic
isolated tests, not a production deletion clock. Cold SHA/size
verification has an explicit ceiling per candidate pass, each manifest capture,
aggregate pending byte capture and each unfinished stage; do not interpret it
as one combined transfer ceiling.
Roots are rechecked before and after verification, including pending local
bytes, epoch, catalog and complete stage inventory. Changed roots, expired plan,
changed bytes or unknown state abort validation. The output includes precise
candidates, source retired version IDs, bytes, reasons and physical-limit pin
blockers. No live database, backup catalog or object is deleted/modified.

Plans cache verified manifest bytes as private local evidence outside Git, so
the isolated local simulation can resume after a manifest deletion. Its durable
intent journal handles interruption between unlink and success logging; exact
retry accepts only journaled deletions, protects changed/reappearing objects
and deletes manifests last. That simulation rejects OSS and non-test namespaces.
The exact execution interface is now `ReclamationExecution`. A separate
`litlib-gc-authorization-v1` approval must explicitly bind execute=true, target,
plan SHA, exact object/byte summary, approver label and approval validity window.
The label/digest does not prove human approval; the actual operator must supply
the authorization. No environment flag enables production. Only explicit
`--simulate-local` with a LocalObjectBackend test namespace is accepted:

```text
python scripts/storage_reclamation.py --catalog ABSOLUTE_CATALOG --roots ABSOLUTE_ROOTS --max-verify-bytes CEILING execute --plan FROZEN_PLAN --authorization REVIEWED_APPROVAL --journal NEW_DURABLE_JOURNAL --receipt NEW_IMMUTABLE_RECEIPT --simulate-local
python scripts/storage_reclamation.py --catalog ABSOLUTE_CATALOG --roots ABSOLUTE_ROOTS --max-verify-bytes CEILING reconcile --receipt COMPLETED_RECEIPT --simulate-local
```

Use the restored wrapper's --authority-control for these administrative test
commands: the executor owns the guard. Each object's intent/result is fsynced
in an atomic journal with a verified event hash chain; manifests are last.
Interruption after unlink is recovered only from the exact durable intent.
An immutable complete receipt contains the frozen plan, explicit approval and
complete event chain. Reconciliation anchors the receipt's file SHA in the
catalog and marks precisely deleted retired manifests `reclaimed`, preserving
their verified archived closure. The next plan recognizes only these anchored
deletions, still protects shared live references, and refuses missing/tampered
receipts or unexplained absence/reappearance. Failed reconciliation before the
atomic catalog commit can be retried without new deletion.

Two consecutive local 4→3 rotations, with a genuinely new fifth snapshot between
them, are validated. This is runnable execution/receipt/reconciliation code,
not a production OSS delete adapter: the production adapter is hard disabled,
and live three-version retention remains unaccepted. Partial work whose plan
or approval has expired is blocked; cross-expiry automatic renewal is not
implemented. Inspect/review the existing journal rather than spoofing old UTC.

## Agent handoff boundary

Physical deployment belongs to the receiving host's agent. This source task
does not wait for a host address or deploy the formal service. The delivered
HANDOFF.md is the single receiving-agent entrypoint and includes the latest
unpublished code bundle/SHA, approved first OSS release, restore commands and
target configuration/acceptance responsibilities. A bundle is not a published
GitHub commit. Do not bind a new production release to an unreachable code
commit, bypass frontend integrity, or confuse first-release recovery with the
new candidate already running. Source originals/formal service remain retained.

## Minimal real acceptance scenario (prepared, not executed)

Choose one explicitly authorized source/work and fixed parse version after
checking all batches, existing results, feedback and active tasks. Reuse existing
parse output unless the agreed scenario specifically requires new production.
Record actual target commit, namespace, authority epoch and binding baseline.

Produce one new approved parse version through the supported API/producer,
verify OSS SHA/size and binding registration immediately, then access that exact
identity/role/version through the authenticated remote CLI from another machine
with a strict byte budget and a new output path. Compare SHA and exercise one
wrong-version read; it must fail without fallback. A bounded test upload failure
may be exercised only in an isolated test namespace, then resumed using the
same operation ID. Never disrupt the real OSS endpoint to manufacture failure.

The bounded request is `POST /api/parse/trigger` with a reviewed JSON body naming
one `work_ids` entry and parser mode; choose a work with exactly one eligible
source for this minimal scenario (the current trigger has no source-ID field).
Only set `force=true`
if that rerun is authorized. The existing trigger contract and cross-batch check
determine the permitted payload. From the remote client:

```text
python scripts/litlib_remote.py --server https://TARGET request /api/parse/trigger --method POST --json-file APPROVED_REQUEST.json --allow-write
python scripts/litlib_remote.py --server https://TARGET asset FIXED_IDENTITY --role md --version EXACT_VERSION --max-bytes APPROVED_LIMIT --output NEW_ABSOLUTE_PATH
```

Store request/response, operation ID, fixed binding, verified SHA/size and client
receipt in a new dated acceptance directory; do not include process tokens.

Take one consistent release backup containing this new version and one explicitly
named draft change, discover it without the source catalog and restore into a
new return directory. Verify those two increments, exact code/runtime checks
and read-only CLI access. A real writer switch requires the explicit epoch
handover above. These are engineering checks; no scientific approval or human
adoption is inferred. Report actual receipts, commands, commit and data versions.
