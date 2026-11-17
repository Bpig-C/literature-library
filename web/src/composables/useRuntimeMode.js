import { computed, ref } from 'vue'

// RWEB-03 / #22: single source of the deployment's read-only state. The flag
// comes from the lightweight /api/mode endpoint so the UI can explain disabled
// write entry points instead of letting users hit a remote 403.
//
// mode: 'unknown' (not confirmed yet), 'writable', 'readonly' (both confirmed
// by the server), or 'error' (mode request failed). Write gating is
// fail-closed: readOnly stays true until the server explicitly reports
// read_only === false. The banner wording, however, must never claim a
// confirmed read-only deployment out of an unconfirmed state, so consumers
// that explain the deployment status read `mode` instead of `readOnly`.
const mode = ref('unknown')
const remoteWritesEnabled = ref(null)
const checking = ref(false)
let inFlight = null
let lastAttemptAt = 0

const MODE_TIMEOUT_MS = 10000
// After a failure, let route switches and remounts retry automatically, but
// not more often than this — a stuck client must not hammer the endpoint.
const RETRY_DEBOUNCE_MS = 3000

function loadMode(force = false) {
  if (inFlight) return inFlight
  if (!force && mode.value === 'error' && Date.now() - lastAttemptAt < RETRY_DEBOUNCE_MS) {
    return Promise.resolve()
  }
  lastAttemptAt = Date.now()
  checking.value = true
  inFlight = (async () => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), MODE_TIMEOUT_MS)
    try {
      const res = await fetch('/api/mode', { signal: controller.signal })
      if (!res.ok) throw new Error('mode-http-' + res.status)
      const data = await res.json()
      if (!data || typeof data.read_only !== 'boolean') throw new Error('mode-field-missing')
      remoteWritesEnabled.value = data.remote_writes_enabled === true
      mode.value = data.read_only ? 'readonly' : 'writable'
    } catch {
      mode.value = 'error'
    } finally {
      clearTimeout(timer)
      checking.value = false
      inFlight = null
    }
  })()
  return inFlight
}

export function useRuntimeMode() {
  if (mode.value === 'unknown' || mode.value === 'error') loadMode()
  const readOnly = computed(() => mode.value !== 'writable')
  return { readOnly, mode, remoteWritesEnabled, checking, retry: () => loadMode(true) }
}
