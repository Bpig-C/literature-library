param([Parameter(Mandatory=$true)][string]$Configuration,[switch]$Execute)
$ErrorActionPreference='Stop'
$cfg=Get-Content -LiteralPath $Configuration -Raw | ConvertFrom-Json
$app=Split-Path -Parent $PSScriptRoot
$python=Join-Path $app '.venv/Scripts/python.exe'
& $python (Join-Path $app 'scripts/target_preflight.py') --configuration $Configuration
if ($LASTEXITCODE -ne 0) { throw 'Preflight failed; restore not attempted.' }
if (Test-Path -LiteralPath $cfg.restored_root) { throw 'Install/update requires a new release directory; current deployment preserved.' }
$commit=(& git -C $app rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -ne $cfg.code_commit) { throw 'Run this installer from the exact reviewed code commit.' }
if (!$Execute) {
  [ordered]@{mode='review_only';destination=$cfg.restored_root;code_commit=$commit;service_started=$false;timer_installed=$false} | ConvertTo-Json
  exit 0
}
$env:LITLIB_OSS_BUCKET=$cfg.oss_bucket
$env:LITLIB_OSS_REGION=$cfg.oss_region
& (Join-Path $app 'scripts/recover_release.ps1') -CodeUrl $cfg.code_url -CodeCommit $cfg.code_commit -ManifestKey $cfg.manifest_key -ManifestSha256 $cfg.manifest_sha256 -Namespace $cfg.namespace -Destination $cfg.restored_root -QuotaBytes $cfg.max_snapshot_bytes
if (!$?) { throw 'Recovery failed; no service or timer started.' }
# A separate reviewed authority transition and service-manager action enables
# this new slot. This script never stops the existing deployment or deletes it.
