import { ref } from 'vue'

// RWEB-03: single source of the deployment's read-only state. The flag comes
// from /api/overview (read_only) so the UI can explain disabled write entry
// points instead of letting users hit a remote 403.
// Fail-closed: the unknown/failure state keeps the UI read-only. A writable
// deployment only unlocks the UI after the overview explicitly reports
// read_only === false.
const readOnly = ref(true)
let loaded = false

export function useRuntimeMode() {
  if (!loaded) {
    loaded = true
    fetch('/api/overview')
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (data && data.read_only === false) readOnly.value = false
      })
      .catch(() => {})
  }
  return { readOnly }
}
