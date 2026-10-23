# Controlled backup and complete recovery

The #7/#14 async/native-batch candidate additionally needs the `parsing` extra,
an independent `scripts/parse_worker.py` at the exact live commit, explicit
capability activation, and an independently preserved upload encryption key.
The [client/host operations](foundation-client.md#8-异步解析与原生多文件批次issue-714)
cover migration, limits, maintenance barriers and cold restore. Code push does
not install or activate either worker.

The [foundation client and host guide](foundation-client.md) describes the
additive backup queue, independent worker configuration, parse plan tables and
client capabilities. The worker must survive API maintenance and use a clean,
full-history code checkout at the live commit. Its scheduler is not installed
by publishing code. Validate the host adapter and cold recovery before enabling
remote backup requests in production.

## Continuous operation candidate

New-machine examples use the restored wrapper so roots are applied only within the subprocess: `restored_runtime.py run-cli --root <B> --authority-control storage_authority.py initialize`, then `freeze` before the final migration backup. Backup scheduling uses `run-cli --root <B> --authority-control storage_backup.py --catalog <absolute-catalog> tick ... --writers-stopped`. Administrative control is separate from business write permissions. Inject authority and transport tokens in the process environment; do not place them in environment.json. Without the authority's local catalog, `storage_backup.py discover-remote --namespace <exact-namespace>` uses standard OSS process credentials to fetch the retained verified choices; an authenticated running authority also exposes `/api/remote/backups`. Discovery indexes are small immutable objects published before local registration, and each returned manifest SHA/identity/code commit is verified. Neither a failed index publication nor an old snapshot replay completes a due backup.

Before development or publishing a new code descendant from a shallow restored checkout, fetch full ancestry from its approved code source with `git fetch --unshallow --no-tags <approved-source>`, then run `check_release.py`. The publication gate refuses a shallow history that could conceal forbidden data ancestors. Normal exact-commit restore checks remain valid without downloading unrelated branches.

Explicit authority transition: initialize epoch 0 once with a process-only `LITLIB_AUTHORITY_TOKEN` and `LITLIB_AUTHORITY_EPOCH`; freeze the source before its final backup; complete and register a new verified backup after freeze; select that precise version when handing over to the target owner's SHA. Immutable epoch records fence old owners, including restored old owner copies. Handover upload failure leaves the source frozen and supports an exact retry. The supported API and write-enabled restored CLI hold the owner guard through each operation. Direct unsupervised database/script access remains outside this entrypoint guarantee and must be stopped during handover. This is cooperative single-owner fencing, not automatic failover or a distributed multi-writer database. No authority control objects have been created in real OSS by this candidate.

Parse production persists immutable assets immediately through the existing producer/storage service, independently of backup cadence. Failed uploads retain pending bytes and operation status; resume uses the same operation identity. Remote transport uses `scripts/litlib_remote.py --server https://HOST asset ID --role md --version VERSION --max-bytes BUDGET --output PATH`, with `LITLIB_REMOTE_TOKEN` injected into the process environment. Set server `LITLIB_REMOTE_ENABLED=1`; writes remain disabled unless `LITLIB_REMOTE_WRITE_ENABLED=1`. HTTPS termination is required for non-loopback clients. No credential belongs in command arguments, Git, backups or receipts. Write-enabled operations also require the configured authority epoch gate; the write flag alone does not authorize a writer. After handover, the restored manifest SHA must match the precise release selected by the source.

`storage_backup.py --catalog ABSOLUTE_PATH versions|select|plan|tick` provides authority-side discovery, explicit version selection and scheduled due execution. Tick requires reviewed inputs, an actual stopped-writer window and explicit payload budget. Run it from the authority host scheduler; default policy is 7 days and 3 successful versions. A failed backup preserves prior successful versions. Catalog rotation keeps three verified versions and records older versions as retired, protecting active and retained snapshot assets. Physical deletion is implemented only for isolated local test objects; no cloud deletion is executed. The due runner does not upload daily parse assets.

Normal restored runtime checks still require exact published code. `--development` explicitly permits clean generic-code descendants of the restored commit for isolated development. Submit and test code changes before preparing the next snapshot; publish the code commit before a real remote restore. `check_release.py` scans every reachable ancestor for forbidden data paths, allowing continuous code history without importing broad research history. Default branch selection and production machine cutover require separate user decisions.

Code is a clean minimal Git revision. Private DBs, drafts, runtime scientific assets and selected execution materials are versioned OSS snapshots. Long-term objects are SHA addressed and read through bounded lazy cache. No credential values enter backups.

## Exact reviewed inputs and one backup command

`litlib-snapshot-input-v1` names absolute catalog/research DB paths, namespace, files mapping runtime relative names to source/SHA/bytes, non-sensitive configuration, code_url, and frontend source/SHA/bytes. Nothing is discovered by uploading a directory. `snapshot-prepare --inputs <json> --ticket <new-json> --max-snapshot-bytes <limit>` is read-only and offline. The returned ticket fixes code, binding index, file hashes and DB endpoints. `snapshot-stage` requires its reviewed SHA, a new absolute destination and `--writers-stopped`; it acquires both SQLite writer locks and freezes backups/files. `snapshot-publish` uses the exact staged manifest SHA/budget and preserves a retry journal.

After direct operator authorization of named inputs, budget and maintenance window, a single backup command runs the same pipeline:

```
python scripts/storage_release.py backup --inputs <exact-input.json> --approved-input-sha256 <canonical-json-sha256> --destination <new-absolute-stage> --writers-stopped --max-upload-bytes <approved-byte-limit>
```

The flag records operator confirmation; it does not establish that external writers are stopped or prove human approval. Existing corpus objects must already exist with the expected sizes. They are never uploaded again by backup. Every snapshot object is immutable and SHA verified by cold read; release manifest publishes last. Rerun the same completed frozen stage/input/budget after upload failure. A corrupt or incomplete stage requires a new ticket and directory; no cleanup or overwrite occurs automatically. Changed live inputs are never silently recaptured on retry. Exact unique upload byte ceiling including manifest is emitted at staging; actual new bytes depend on remote SHA reuse.

## First client bootstrap and one recovery command

Install Git and uv on the new client. Obtain the standalone scripts/recover_release.ps1 from the reviewed immutable GitHub commit (raw URL) and compare its SHA256 with the release descriptor before executing it; never execute unverified fetched text. Set explicit LITLIB_OSS_BUCKET/LITLIB_OSS_REGION and standard SDK credential environment (OSS_ACCESS_KEY_ID/SECRET, optional SESSION_TOKEN).

```
pwsh -File recover_release.ps1 -CodeUrl <reviewed-GitHub-url> -CodeCommit <40-character-SHA> -ManifestKey <key> -ManifestSha256 <SHA256> -Namespace <namespace> -Destination <new-absolute-directory>
```

That script fetches only the exact code commit into a unique bootstrap directory, performs `uv sync --frozen --extra storage --no-dev`, obtains the restore client/locked SDK, restores code/frontend/DB pair/selected drafts/assets/config/index, installs the recovered app dependencies with the same frozen lock, and runs an explicit-root check. It does not start a service. The bootstrap directory is retained for diagnosis. Failed dependency installation leaves recovered files intact and is explicitly reported. Local-object/offline flags are accepted only for isolated test namespaces.

A lower-level installed client may use `python scripts/storage_release.py restore --manifest-key <key> --manifest-sha256 <sha> --namespace <ns> --expected-git-url <url> --destination <absolute-new-root>`. A new directory is published only after all integrity/schema/contract/index checks. Existing destinations are refused.

## Applied environment and deliberate runtime

```
<restored>/app/.venv/Scripts/python.exe <restored>/app/scripts/restored_runtime.py check --root <restored>
<restored>/app/.venv/Scripts/python.exe <restored>/app/scripts/restored_runtime.py serve --root <restored> --port <explicit-free-port>
```

The wrapper applies environment.json in its own process before importing app modules, clears inherited LITLIB roots, verifies all paths against this restored root, code/frontend hashes, schema6/contract5, runtime assets and OSS SDK1.4.0. Missing/mismatched paths fail explicitly with no original-machine fallback. Serve uses the requested free loopback port in the foreground; it neither kills nor restarts another service. `--read-only` keeps research DB writes disabled. SDK credentials remain in the environment. To run supported business CLIs, use `restored_runtime.py run-cli --root <restored> <litlib.py|storage_assets.py|healthcheck_library.py|literature_ingest.py> <arguments>` and their explicit library/db arguments; research writes additionally require `--allow-writes` and normal task authorization.

Code root is app; runtime materials root is data/library/docs and is reported by /api/research/schema. Contracts are fetched from Git, with a verified reference copy for material-relative links. Essential runtime assets are local; PDF/ZIP/images remain remote except for bounded cache.

## Old entrypoint boundary

start_v5_trial.ps1 and fixed-root legacy batch-parse/metadata/classification/judge/sync CLIs now refuse execution in this publication tree. Their importable functions remain for compatibility. They are not migration or recovery entrypoints. No collector expansion is included. The full research workspace continues to use check_docs.py; this reduced code publication uses check_release.py, with different scope. Dated source manuals preserve original evidence dates. Candidate engineering is not formal deployment or scientific/human acceptance.

## Project documentation maintenance

The complete generic skill is versioned in `skills/project-doc-maintenance/`.
Read its `SKILL.md` and referenced files for Bootstrap, Adopt, Sync and Review.
Install the complete directory in the host Agent's skill location and give the
project AGENTS entry a resolvable reference. Use an exact approved code commit.

Installing this skill does not require modifying or restarting a sealed running
release. Do not pull new code into that slot solely to install a host Agent skill.
The skill does not grant business writes, authority takeover, or scientific
approval. Preserve the distinction between code, runtime evidence, research
review and human adoption; report a documented no-op when sources need no change.

Verify the complete package with:

```console
python skills/project-doc-maintenance/scripts/package_hash.py
```

The package contains SKILL.md, agents/openai.yaml, three referenced documents
and the package hash script; copy all six files together.
