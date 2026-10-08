# Single maintained code line and target operations

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

The current test-only local purge demonstrates shared-object protection, not
that this production executor exists. Its OSS equivalent remains work to do.

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
