# Implement and review for the actual target's service manager and all writers.
# Never return stopped=true unless API, workers and other supported writers are
# quiescent. Refresh hashes for the exact named backup inputs, without scanning
# for additional files. This adapter contains no credentials.
function Enter-LitlibMaintenance($Config) {
  throw 'Target service manager not configured; no backup attempted.'
}
function Exit-LitlibMaintenance($Config, $Lease) {
  throw 'Target service manager not configured; no service restarted.'
}
