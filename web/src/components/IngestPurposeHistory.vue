<template>
  <section class="section">
    <h3>入库用途</h3>
    <p v-if="error" role="alert">{{ error }} <button @click="load">重试读取</button></p>
    <p v-else-if="!notes.length">{{ loading ? '读取中…' : '尚未记录用途' }}</p>
    <ul><li v-for="note in notes" :key="note.id"><p style="white-space:pre-wrap">{{ note.purpose }}</p><small>{{ note.created_at }} {{ note.actor }}</small></li></ul>
    <button v-if="hasMore" :disabled="loading" @click="loadMore">更多历史用途</button>
    <label>追加用途（必填）<textarea v-model="purpose" maxlength="2000" rows="3" :disabled="readOnly || saving" /></label>
    <button :disabled="readOnly || saving || !purpose.trim()" @click="save">{{ saving ? '保存中…' : '追加用途' }}</button>
  </section>
</template>
<script setup>
import { ref, watch } from 'vue'
import { getIngestNotes, appendIngestNote } from '../api'
import { useRuntimeMode } from '../composables/useRuntimeMode'
import { showError } from '../error-handler'
const props = defineProps({ workId: { type: String, required: true } })
const { readOnly } = useRuntimeMode()
const notes = ref([]), purpose = ref(''), error = ref(''), loading = ref(false), saving = ref(false), hasMore = ref(false)
let operation = null, generation = 0
async function loadMore() {
  const workId = props.workId, current = generation
  loading.value = true
  try {
    const result = await getIngestNotes(workId, notes.value.length)
    if (current !== generation) return
    notes.value.push(...result.notes); hasMore.value = result.notes.length === 50; error.value = ''
  } catch (e) { if (current === generation) error.value = e.message }
  finally { if (current === generation) loading.value = false }
}
async function load() { generation++; notes.value = []; await loadMore() }
async function save() {
  if (readOnly.value || saving.value || !purpose.value.trim()) return
  const workId = props.workId, text = purpose.value.trim()
  if (operation?.workId !== workId || operation?.text !== text) operation = { workId, text, id: crypto.randomUUID() }
  saving.value = true
  try {
    await appendIngestNote(workId, { purpose: text, request_id: operation.id })
    operation = null
    if (props.workId === workId) { purpose.value = ''; await load() }
  } catch (e) { showError(e) }
  finally { saving.value = false }
}
watch(() => props.workId, () => { purpose.value = ''; operation = null; load() }, { immediate: true })
</script>
