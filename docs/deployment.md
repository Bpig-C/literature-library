# Controlled backup and complete recovery

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
