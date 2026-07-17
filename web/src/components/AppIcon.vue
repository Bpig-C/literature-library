<template>
  <svg class="app-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <template v-if="name === 'home'">
      <path d="M3.5 10.7 12 3.8l8.5 6.9v8.1a1.7 1.7 0 0 1-1.7 1.7H5.2a1.7 1.7 0 0 1-1.7-1.7v-8.1Z" />
      <path d="M9 20.5v-6.2h6v6.2" />
    </template>
    <template v-else-if="name === 'library'">
      <path d="M5 4.5h11.5A2.5 2.5 0 0 1 19 7v12.5H7.5A2.5 2.5 0 0 1 5 17V4.5Z" />
      <path d="M5 17a2.5 2.5 0 0 1 2.5-2.5H19M9 8h6" />
    </template>
    <template v-else-if="name === 'pipeline'">
      <circle cx="6" cy="6" r="2.2" /><circle cx="18" cy="18" r="2.2" />
      <path d="M8.2 6h4.3A3.5 3.5 0 0 1 16 9.5v4.3M13 11l3 3 3-3" />
    </template>
    <template v-else-if="name === 'topics'">
      <path d="M4 5.5h6l2 2h8v11H4v-13Z" /><path d="M8 12h8M8 15.5h5" />
    </template>
    <template v-else-if="name === 'discovery'">
      <circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.2 4.2M11 8v6M8 11h6" />
    </template>
    <template v-else-if="name === 'ingest'">
      <path d="M4 15.5v3.2A1.8 1.8 0 0 0 5.8 20.5h12.4a1.8 1.8 0 0 0 1.8-1.8v-3.2" />
      <path d="M12 3.5v11m-4-4 4 4 4-4" />
    </template>
    <template v-else-if="name === 'review'">
      <path d="M5 4h14v16H5z" /><path d="m8 11 2.2 2.2L16 8M8 17h8" />
    </template>
    <template v-else-if="name === 'metadata'">
      <path d="M4 7.5V4h3.5M16.5 4H20v3.5M20 16.5V20h-3.5M7.5 20H4v-3.5" />
      <path d="M8 9h8M8 12h8M8 15h5" />
    </template>
    <template v-else-if="name === 'classify'">
      <rect x="4" y="4" width="6" height="6" rx="1.2" /><rect x="14" y="4" width="6" height="6" rx="1.2" />
      <rect x="4" y="14" width="6" height="6" rx="1.2" /><rect x="14" y="14" width="6" height="6" rx="1.2" />
    </template>
    <template v-else-if="name === 'duplicates'">
      <rect x="7" y="7" width="12" height="12" rx="2" /><path d="M16 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h2" />
    </template>
    <template v-else-if="name === 'relations'">
      <circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="6" r="2.5" /><circle cx="18" cy="18" r="2.5" />
      <path d="m8.4 11 7.2-3.8M8.4 13l7.2 3.8" />
    </template>
    <template v-else-if="name === 'templates'">
      <path d="M6 3.5h9l3 3v14H6v-17Z" /><path d="M14 3.5v4h4M9 12h6M9 16h6" />
    </template>
    <template v-else-if="name === 'menu'">
      <path d="M4 7h16M4 12h16M4 17h16" />
    </template>
    <template v-else>
      <path d="M12 3.5 14 9l5.5 2-5.5 2-2 5.5-2-5.5-5.5-2L10 9l2-5.5Z" />
    </template>
  </svg>
</template>

<script setup>
defineProps({ name: { type: String, default: 'spark' } })
</script>

<style scoped>
.app-icon {
  display: block;
  width: 1.2em;
  height: 1.2em;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}
</style>
