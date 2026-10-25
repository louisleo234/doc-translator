<template>
  <div class="mcp-token-page">
    <div class="page-header">
      <div>
        <h1>{{ t('mcpTokens.title') }}</h1>
        <p>{{ t('mcpTokens.scope') }}</p>
      </div>
      <a-space wrap>
        <a-button :loading="loading" @click="loadPage()">{{ t('mcpTokens.refresh') }}</a-button>
        <a-button type="primary" @click="openCreate">{{ t('mcpTokens.create') }}</a-button>
      </a-space>
    </div>
    <a-alert v-if="listError" type="error" show-icon :message="listError" class="error-alert" />
    <a-table :columns="columns" :data-source="tokens" row-key="id" :loading="loading"
      :pagination="false" :scroll="{ x: 1050 }">
      <template #emptyText>{{ t('mcpTokens.empty') }}</template>
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'id'"><code>{{ record.id }}</code></template>
        <template v-else-if="column.key === 'createdAt' || column.key === 'expiresAt'">
          {{ formatDate(record[column.key]) }}
        </template>
        <template v-else-if="column.key === 'status'">
          <a-tag :color="status(record) === 'active' ? 'green' : status(record) === 'revoked' ? 'red' : 'default'">
            {{ t(`mcpTokens.${status(record)}`) }}
          </a-tag>
        </template>
        <template v-else-if="column.key === 'actions'">
          <a-button danger size="small" :disabled="!!record.revokedAt" @click="revokeTarget = record">
            {{ t('mcpTokens.revoke') }}
          </a-button>
        </template>
      </template>
    </a-table>
    <div class="pagination">
      <a-button :disabled="loading || pageIndex === 0" @click="changePage(-1)">{{ t('mcpTokens.previous') }}</a-button>
      <span>{{ t('mcpTokens.page', { page: pageIndex + 1 }) }}</span>
      <a-button :disabled="loading || !nextCursor" @click="changePage(1)">{{ t('mcpTokens.next') }}</a-button>
    </div>

    <a-modal :open="createOpen" :title="t('mcpTokens.create')" :confirm-loading="creating"
      :ok-text="t('mcpTokens.create')" :cancel-text="t('common.cancel')"
      :cancel-button-props="{ disabled: creating }" :closable="!creating" :mask-closable="false"
      :keyboard="!creating" @ok="createToken" @cancel="createOpen = false">
      <p>{{ t('mcpTokens.scope') }}</p>
      <a-form layout="vertical">
        <a-form-item :label="t('mcpTokens.name')" html-for="mcp-token-name" required>
          <a-input id="mcp-token-name" v-model:value="name" :maxlength="100" :disabled="creating" />
        </a-form-item>
        <a-form-item :label="t('mcpTokens.validity')" html-for="mcp-token-validity" required>
          <a-select id="mcp-token-validity" v-model:value="validity" :disabled="creating" :options="validityOptions" />
        </a-form-item>
        <a-form-item v-if="validity === 'custom'" :label="t('mcpTokens.expiresAt')" html-for="mcp-token-expiry" required>
          <input id="mcp-token-expiry" v-model="customExpiry" class="custom-expiry" type="datetime-local" :disabled="creating" />
        </a-form-item>
      </a-form>
      <a-alert v-if="createError" type="error" show-icon :message="createError" />
    </a-modal>

    <a-modal :open="!!secret" :title="t('mcpTokens.secretTitle')" :footer="null"
      :mask-closable="false" destroy-on-close @cancel="clearSecret">
      <a-alert type="warning" show-icon :message="t('mcpTokens.secretWarning')" />
      <pre class="secret" data-testid="mcp-secret">{{ secret }}</pre>
      <p>{{ t('mcpTokens.endpoint') }}: <code>{{ mcpEndpoint }}</code></p>
      <p><code>Authorization: Bearer &lt;token&gt;</code></p>
      <a-space wrap>
        <a-button type="primary" @click="copySecret">{{ t('mcpTokens.copy') }}</a-button>
        <a-button @click="clearSecret">{{ t('mcpTokens.close') }}</a-button>
      </a-space>
      <a-alert v-if="copyError" class="error-alert" type="error" :message="copyError" />
    </a-modal>

    <a-modal :open="!!revokeTarget" :title="t('mcpTokens.revoke')" :confirm-loading="revoking"
      :ok-text="t('mcpTokens.revoke')" :cancel-text="t('common.cancel')" :ok-button-props="{ danger: true }"
      :cancel-button-props="{ disabled: revoking }" :closable="!revoking" :mask-closable="false"
      :keyboard="!revoking" @ok="revokeToken" @cancel="closeRevoke">
      <p>{{ t('mcpTokens.revokeWarning') }}</p>
      <p>{{ revokeTarget?.name }} — <code>{{ revokeTarget?.id }}</code></p>
      <a-alert v-if="revokeError" type="error" show-icon :message="revokeError" />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { useLanguage } from '@/composables/useLanguage'
import { apolloClient } from '@/services/apollo'
import { MCP_TOKENS_QUERY, CREATE_MCP_TOKEN_MUTATION, REVOKE_MCP_TOKEN_MUTATION, type McpToken } from '@/graphql/mcpTokens'

const { t, currentLanguage } = useLanguage()
const tokens = ref<McpToken[]>([])
const loading = ref(false)
const listError = ref('')
const pageIndex = ref(0)
const cursors = ref<(string | null)[]>([null])
const nextCursor = ref<string | null>(null)
const createOpen = ref(false)
const creating = ref(false)
const createError = ref('')
const name = ref('')
const validity = ref<number | 'custom'>(90)
const customExpiry = ref('')
const secret = ref('')
const copyError = ref('')
const revokeTarget = ref<McpToken | null>(null)
const revoking = ref(false)
const revokeError = ref('')
let mounted = true
let latestLoad = 0
const mcpEndpoint = new URL('/api/mcp', new URL(import.meta.env.VITE_API_URL || 'http://localhost:8000/api/graphql', window.location.origin)).href
const columns = computed(() => [
  ...['name', 'id', 'createdBy', 'createdAt', 'expiresAt', 'status'].map(key => ({ title: t(`mcpTokens.${key}`), key, dataIndex: key })),
  { title: t('mcpTokens.actions'), key: 'actions', width: 100 },
])
const validityOptions = computed(() => [
  ...[30, 90, 365].map(days => ({ value: days, label: t('mcpTokens.days', { days }) })),
  { value: 'custom', label: t('mcpTokens.custom') },
])
function formatDate(value: string) {
  return new Date(value).toLocaleString(currentLanguage.value)
}
function status(token: McpToken) {
  return token.revokedAt ? 'revoked' : new Date(token.expiresAt).getTime() <= Date.now() ? 'expired' : 'active'
}
function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : t(`mcpTokens.${fallback}`)
}
async function loadPage(index = pageIndex.value, cursor = cursors.value[index] ?? null) {
  const request = ++latestLoad
  loading.value = true
  listError.value = ''
  try {
    const result = await apolloClient.query<{ mcpTokens: { items: McpToken[]; nextCursor: string | null } }>({
      query: MCP_TOKENS_QUERY, variables: { first: 20, after: cursor }, fetchPolicy: 'no-cache', errorPolicy: 'none',
    })
    if (request !== latestLoad || !mounted) return
    if (!result.data?.mcpTokens) throw new Error(t('mcpTokens.loadError'))
    tokens.value = result.data.mcpTokens.items
    nextCursor.value = result.data.mcpTokens.nextCursor
    pageIndex.value = index
  } catch (error) {
    if (request === latestLoad && mounted) listError.value = errorText(error, 'loadError')
  } finally {
    if (request === latestLoad && mounted) loading.value = false
  }
}
async function changePage(direction: number) {
  const index = pageIndex.value + direction
  if (direction > 0) cursors.value[index] = nextCursor.value
  await loadPage(index)
}
function openCreate() {
  name.value = ''
  validity.value = 90
  customExpiry.value = ''
  createError.value = ''
  createOpen.value = true
}
async function createToken() {
  if (creating.value) return
  createError.value = ''
  if (!name.value.trim()) { createError.value = t('mcpTokens.nameRequired'); return }
  const expiresAt = validity.value === 'custom'
    ? new Date(customExpiry.value)
    : new Date(Date.now() + validity.value * 86400000)
  if (!Number.isFinite(expiresAt.getTime()) || expiresAt.getTime() <= Date.now()) {
    createError.value = t('mcpTokens.expiryRequired'); return
  }
  creating.value = true
  try {
    const result = await apolloClient.mutate<{ createMcpToken: { token: McpToken; secret: string } }>({
      mutation: CREATE_MCP_TOKEN_MUTATION,
      variables: { input: { name: name.value.trim(), expiresAt: expiresAt.toISOString() } },
      fetchPolicy: 'no-cache', errorPolicy: 'none', context: { fetchOptions: { cache: 'no-store' } },
    })
    if (!mounted) return
    if (!result.data?.createMcpToken.secret) throw new Error(t('mcpTokens.createError'))
    secret.value = result.data.createMcpToken.secret
    createOpen.value = false
    copyError.value = ''
    cursors.value = [null]
    await loadPage(0, null)
  } catch (error) {
    if (mounted) createError.value = errorText(error, 'createError')
  } finally { creating.value = false }
}
function clearSecret() { secret.value = ''; copyError.value = '' }
async function copySecret() {
  copyError.value = ''
  try {
    await navigator.clipboard.writeText(secret.value)
    if (mounted && secret.value) message.success(t('mcpTokens.copied'))
  } catch { if (mounted && secret.value) copyError.value = t('mcpTokens.copyError') }
}
function closeRevoke() { revokeTarget.value = null; revokeError.value = '' }
async function revokeToken() {
  if (!revokeTarget.value || revoking.value) return
  revoking.value = true
  revokeError.value = ''
  try {
    const result = await apolloClient.mutate<{ revokeMcpToken: boolean }>({
      mutation: REVOKE_MCP_TOKEN_MUTATION, variables: { id: revokeTarget.value.id },
      fetchPolicy: 'no-cache', errorPolicy: 'none',
    })
    if (!mounted) return
    if (!result.data?.revokeMcpToken) throw new Error(t('mcpTokens.revokeError'))
    closeRevoke()
    message.success(t('mcpTokens.revokedSuccess'))
    await loadPage()
  } catch (error) { if (mounted) revokeError.value = errorText(error, 'revokeError') }
  finally { revoking.value = false }
}
onMounted(() => loadPage())
onUnmounted(() => { mounted = false; clearSecret() })
</script>

<style scoped>
.mcp-token-page { padding: 24px; max-width: 1400px; margin: 0 auto; }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
h1 { font-size: 24px; color: var(--text-main); margin: 0 0 4px; }
p { color: var(--text-secondary); }
.page-header p { margin: 0; }
.pagination { display: flex; justify-content: flex-end; align-items: center; gap: 12px; margin-top: 16px; }
.error-alert { margin: 16px 0; }
.secret { padding: 16px; background: var(--item-hover-bg); white-space: pre-wrap; overflow-wrap: anywhere; user-select: all; }
.custom-expiry { width: 100%; padding: 6px 11px; border: 1px solid var(--border-color); border-radius: 6px; color: var(--text-main); background: var(--bg-color); }
code { overflow-wrap: anywhere; }
@media (max-width: 576px) { .mcp-token-page { padding: 16px; } }
</style>
