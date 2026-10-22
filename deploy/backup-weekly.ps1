param([Parameter(Mandatory=$true)][string]$Configuration,[switch]$Execute,[switch]$Force)
$ErrorActionPreference='Stop'
$cfg=Get-Content -LiteralPath $Configuration -Raw | ConvertFrom-Json
$app=Join-Path $cfg.restored_root 'app'
$python=Join-Path $app '.venv/Scripts/python.exe'
& $python (Join-Path $app 'scripts/target_preflight.py') --configuration $Configuration --check-files
if ($LASTEXITCODE -ne 0) { throw 'Target preflight failed; no maintenance or backup.' }
if (!$Execute) {
  [ordered]@{mode='review_only';interval_days=$cfg.interval_days;retain_successful=$cfg.retain_successful;timer_installed=$false;backup_started=$false} | ConvertTo-Json
  exit 0
}
if ((Get-TimeZone).Id -ne 'China Standard Time') { throw 'Reviewed Asia/Shanghai schedule requires target Windows time zone China Standard Time.' }
# Credentials must be injected into this process by the target service account.
if (!$env:OSS_ACCESS_KEY_ID -or !$env:OSS_ACCESS_KEY_SECRET) { throw 'Standard SDK credentials missing.' }
$adapterHash=(Get-FileHash -LiteralPath $cfg.maintenance_adapter -Algorithm SHA256).Hash.ToLowerInvariant()
if ($adapterHash -ne $cfg.maintenance_adapter_sha256) { throw 'Maintenance adapter changed; no execution.' }
. $cfg.maintenance_adapter
$lease=$null
try {
  $lease=Enter-LitlibMaintenance $cfg
  if (!$lease -or !$lease.stopped) { throw 'Actual writer maintenance window not established.' }
  $now=[datetime]::UtcNow.ToString('o')
  $manualArgs=@()
  if ($Force) { $manualArgs=@('--force') }
  & $python (Join-Path $app 'scripts/restored_runtime.py') run-cli --root $cfg.restored_root --authority-control storage_backup.py --catalog $cfg.backup_catalog tick --inputs $cfg.backup_inputs --now $now --interval-days $cfg.interval_days --retain $cfg.retain_successful --stage-parent $cfg.stage_parent --max-snapshot-bytes $cfg.max_snapshot_bytes --writers-stopped @manualArgs
  if ($LASTEXITCODE -ne 0) { throw 'Backup failed; previous successful versions remain. Stage retained for diagnosis/retry.' }
} finally {
  if ($lease) { Exit-LitlibMaintenance $cfg $lease }
}
