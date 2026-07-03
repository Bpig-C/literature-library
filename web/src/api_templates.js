/**
 * Template management API functions.
 *
 * Covers 3 template types: metadata (editable), classification (reserved), discovery (reserved).
 */

import { request } from './api'

const BASE = '/templates'

// ===== Read =====

/** Fetch all three templates merged (custom + built-in defaults) */
export function getTemplates() {
  return request(BASE)
}

/** Fetch pure built-in metadata schema (no user customizations) */
export function getMetadataSchema() {
  return request(`${BASE}/metadata/schema`)
}

/** Fetch raw classification vocab dictionary */
export function getClassificationRaw() {
  return request(`${BASE}/classification/raw`)
}

// ===== Write — Metadata (active) =====

/** Save modified metadata field definitions */
export function saveMetadataTemplate(data) {
  return request(`${BASE}/metadata`, { method: 'POST', body: JSON.stringify(data) })
}

/** Reset metadata to built-in defaults */
export function resetMetadataTemplate() {
  return request(`${BASE}/metadata/reset`, { method: 'POST' })
}

// ===== Write — Classification (reserved, implemented on backend) =====

/** Save modified classification vocabulary — 🔒 reserved for future use */
export function saveClassification(data) {
  return request(`${BASE}/classification`, { method: 'POST', body: JSON.stringify(data) })
}

// ===== Write — Discovery (reserved, implemented on backend) =====

/** Save modified discovery protocol overrides — 🔒 reserved for future use */
export function saveDiscoveryProtocol(data) {
  return request(`${BASE}/discovery`, { method: 'POST', body: JSON.stringify(data) })
}
