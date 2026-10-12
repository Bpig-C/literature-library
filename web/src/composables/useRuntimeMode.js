import { ref } from 'vue'

// RWEB-03: single source of the deployment's read-only state. The flag comes
// from /api/overview (read_only) so the UI can explain disabled write entry
// points instead of letting users hit a remote 403.
const readOnly = ref(false)
let loaded = false

export function useRuntimeMode() {
  if (!loaded) {
    loaded = true
    fetch('/api/overview')
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (data && typeof data.read_only === 'boolean') readOnly.value = data.read_only
      })
      .catch(() => {})
  }
  return { readOnly }
}
