param(
  [Parameter(Mandatory=$true)][string]$CodeUrl,
  [Parameter(Mandatory=$true)][string]$CodeCommit,
  [Parameter(Mandatory=$true)][string]$ManifestKey,
  [Parameter(Mandatory=$true)][string]$ManifestSha256,
  [Parameter(Mandatory=$true)][string]$Namespace,
  [Parameter(Mandatory=$true)][string]$Destination,
  [string]$LocalTestObjects,
  [switch]$OfflineTest,
  [long]$QuotaBytes = 536870912
)
$ErrorActionPreference='Stop'
if ($CodeCommit -notmatch '^[0-9a-f]{40}$' -or $ManifestSha256 -notmatch '^[0-9a-f]{64}$') { throw 'Exact reviewed code commit and manifest SHA required.' }
if (![IO.Path]::IsPathRooted($Destination) -or (Test-Path -LiteralPath $Destination)) { throw 'New absolute destination required; existing files preserved.' }
if ($LocalTestObjects -and ($Namespace -notmatch '/test/' -or ![IO.Path]::IsPathRooted($LocalTestObjects))) { throw 'Local object root only allowed for isolated test namespace.' }
if (!$LocalTestObjects -and $CodeUrl -notmatch '^https://github\.com/') { throw 'Production bootstrap requires the reviewed GitHub URL.' }
if ($OfflineTest -and !$LocalTestObjects) { throw 'Offline mode requires isolated local test objects.' }
foreach ($tool in @('git','uv')) { if (!(Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Install $tool before recovery. No restore started." } }
if (!$LocalTestObjects -and (!$env:LITLIB_OSS_BUCKET -or !$env:LITLIB_OSS_REGION)) { throw 'Set explicit OSS bucket/region and standard SDK credential environment before recovery.' }
# The standalone script is obtained from its reviewed immutable Git revision
# and checked against its release SHA before execution; never use irm | iex.
$bootstrapRoot = Join-Path ([IO.Path]::GetTempPath()) ('litlib-bootstrap-'+[guid]::NewGuid().ToString('N'))
$bootstrapApp = Join-Path $bootstrapRoot 'app'
New-Item -ItemType Directory -Path $bootstrapRoot | Out-Null
& git init --quiet $bootstrapApp
if ($LASTEXITCODE -ne 0) { throw 'Bootstrap Git initialization failed.' }
& git -C $bootstrapApp fetch --quiet --depth=1 --no-tags $CodeUrl $CodeCommit
if ($LASTEXITCODE -ne 0) { throw 'Exact bootstrap revision unavailable; existing destination preserved.' }
& git -C $bootstrapApp -c core.autocrlf=false checkout --quiet --detach $CodeCommit
if ($LASTEXITCODE -ne 0) { throw 'Bootstrap checkout failed.' }
$syncArgs = @('sync','--frozen','--extra','storage','--no-dev','--project',$bootstrapApp)
if ($OfflineTest) { $syncArgs += '--offline' }
& uv @syncArgs
if ($LASTEXITCODE -ne 0) { throw "Locked bootstrap environment failed. Retained: $bootstrapRoot" }
$bootstrapPython = if ($IsWindows -or $env:OS -eq 'Windows_NT') { Join-Path $bootstrapApp '.venv/Scripts/python.exe' } else { Join-Path $bootstrapApp '.venv/bin/python' }
$restoreArgs = @((Join-Path $bootstrapApp 'scripts/storage_release.py'),'restore','--manifest-key',$ManifestKey,'--manifest-sha256',$ManifestSha256,'--namespace',$Namespace,'--destination',$Destination,'--expected-git-url',$CodeUrl,'--quota-bytes',$QuotaBytes)
if ($LocalTestObjects) { $restoreArgs += @('--local-objects',$LocalTestObjects) }
& $bootstrapPython @restoreArgs
if ($LASTEXITCODE -ne 0) { throw "Restore failed; bootstrap retained: $bootstrapRoot" }
$restoredApp = Join-Path $Destination 'app'
$runtimeSync = @('sync','--frozen','--extra','storage','--no-dev','--project',$restoredApp)
if ($OfflineTest) { $runtimeSync += '--offline' }
& uv @runtimeSync
if ($LASTEXITCODE -ne 0) { throw "Files restored but locked dependency installation failed. Rerun uv sync with the same locked app. No service started: $Destination" }
$runtimePython = if ($IsWindows -or $env:OS -eq 'Windows_NT') { Join-Path $restoredApp '.venv/Scripts/python.exe' } else { Join-Path $restoredApp '.venv/bin/python' }
& $runtimePython (Join-Path $restoredApp 'scripts/restored_runtime.py') check --root $Destination
if ($LASTEXITCODE -ne 0) { throw 'Restored runtime check failed; no service started or old machine fallback.' }
[ordered]@{restored_root=$Destination;bootstrap_retained=$bootstrapRoot;locked_dependencies_installed=$true;environment_applied_by_runtime_wrapper=$true;service_started=$false} | ConvertTo-Json
