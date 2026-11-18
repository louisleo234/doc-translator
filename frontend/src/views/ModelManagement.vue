<template>
  <div class="model-management">
    <div class="page-header">
      <div>
        <h2>{{ t('modelManagement.title') }}</h2>
        <p>{{ t('modelManagement.description') }}</p>
      </div>
      <a-space wrap>
        <a-button :loading="loading" @click="loadModels">{{ t('modelManagement.refresh') }}</a-button>
        <a-button type="primary" @click="openCreate">
          <template #icon><PlusOutlined /></template>
          {{ t('modelManagement.add') }}
        </a-button>
      </a-space>
    </div>

    <a-alert v-if="listError" type="error" show-icon :message="listError" class="error-alert" />

    <a-table :columns="columns" :data-source="models" row-key="modelId" :loading="loading"
      :pagination="false" :scroll="{ x: 800 }">
      <template #emptyText>{{ t('modelManagement.empty') }}</template>
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'displayName'">
          {{ record.displayName }}
          <a-tag v-if="record.isDefault" color="blue" class="default-tag">{{ t('modelManagement.default') }}</a-tag>
        </template>
        <template v-else-if="column.key === 'modelId'"><code>{{ record.modelId }}</code></template>
        <template v-else-if="column.key === 'actions'">
          <a-space>
            <a-button size="small" :disabled="record.isDefault || !!busy[record.modelId]"
              :loading="busy[record.modelId] === 'default'"
              @click="setDefault(record)">
              {{ t('modelManagement.setDefault') }}
            </a-button>
            <a-button size="small" @click="openEdit(record)">{{ t('common.edit') }}</a-button>
            <a-popconfirm :title="t('modelManagement.confirmDelete', { name: record.displayName })"
              :ok-text="t('common.yes')" :cancel-text="t('common.no')"
              :disabled="record.isDefault || !!busy[record.modelId]"
              @confirm="deleteModel(record)">
              <a-tooltip :title="record.isDefault ? t('modelManagement.cannotDeleteDefault') : ''">
                <a-button size="small" danger
                  :disabled="record.isDefault || busy[record.modelId] === 'default'"
                  :loading="busy[record.modelId] === 'delete'">
                  {{ t('common.delete') }}
                </a-button>
              </a-tooltip>
            </a-popconfirm>
          </a-space>
        </template>
      </template>
    </a-table>

    <a-modal :open="formOpen" :title="editing ? t('modelManagement.edit') : t('modelManagement.add')"
      :confirm-loading="saving" :ok-text="t('common.save')" :cancel-text="t('common.cancel')"
      :cancel-button-props="{ disabled: saving }" :closable="!saving" :mask-closable="false"
      @ok="saveModel" @cancel="formOpen = false">
      <a-form layout="vertical">
        <a-form-item :label="t('modelManagement.modelId')" html-for="model-id" required
          :extra="editing ? t('modelManagement.modelIdImmutable') : t('modelManagement.modelIdHint')">
          <a-input id="model-id" v-model:value="form.modelId" :disabled="!!editing || saving"
            :maxlength="256" placeholder="global.xai.grok-4.7" />
        </a-form-item>
        <a-form-item :label="t('modelManagement.displayName')" html-for="model-name" required>
          <a-input id="model-name" v-model:value="form.displayName" :disabled="saving"
            :maxlength="100" placeholder="Grok 4.7" />
        </a-form-item>
        <a-form-item :label="t('modelManagement.provider')" html-for="model-provider"
          :extra="t('modelManagement.providerHint')">
          <a-input id="model-provider" v-model:value="form.provider" :disabled="saving"
            :maxlength="50" placeholder="xai" />
        </a-form-item>
        <a-form-item v-if="!editing?.isDefault">
          <a-checkbox v-model:checked="form.isDefault" :disabled="saving">
            {{ t('modelManagement.makeDefault') }}
          </a-checkbox>
        </a-form-item>
      </a-form>
      <a-alert v-if="formError" type="error" show-icon :message="formError" />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { useLanguage } from '@/composables/useLanguage'
import { apolloClient } from '@/services/apollo'
import {
  CONFIG_MODELS_QUERY,
  CREATE_CONFIG_MODEL_MUTATION,
  UPDATE_CONFIG_MODEL_MUTATION,
  DELETE_CONFIG_MODEL_MUTATION,
  type ManagedModel,
} from '@/graphql/models'

const emit = defineEmits<{ (e: 'changed'): void }>()
const { t } = useLanguage()

const models = ref<ManagedModel[]>([])
const loading = ref(false)
const listError = ref('')
const formOpen = ref(false)
const editing = ref<ManagedModel | null>(null)
const saving = ref(false)
const formError = ref('')
// In-flight row action per model ID, so actions on different rows don't clobber each other.
const busy = reactive<Record<string, 'default' | 'delete'>>({})
const form = reactive({ modelId: '', displayName: '', provider: '', isDefault: false })

const columns = computed(() => [
  { title: t('modelManagement.displayName'), key: 'displayName', dataIndex: 'displayName' },
  { title: t('modelManagement.modelId'), key: 'modelId', dataIndex: 'modelId' },
  { title: t('modelManagement.provider'), key: 'provider', dataIndex: 'provider', width: 140 },
  { title: t('common.actions'), key: 'actions', width: 260 },
])

function errorText(error: unknown, fallbackKey: string): string {
  return error instanceof Error && error.message ? error.message : t(`modelManagement.${fallbackKey}`)
}

async function loadModels() {
  loading.value = true
  listError.value = ''
  try {
    const result = await apolloClient.query<{ configAvailableModels: ManagedModel[] }>({
      query: CONFIG_MODELS_QUERY, fetchPolicy: 'no-cache', errorPolicy: 'none',
    })
    models.value = result.data?.configAvailableModels ?? []
  } catch (error) {
    listError.value = errorText(error, 'loadError')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { modelId: '', displayName: '', provider: '', isDefault: false })
  formError.value = ''
  formOpen.value = true
}

function openEdit(model: ManagedModel) {
  editing.value = model
  Object.assign(form, { ...model })
  formError.value = ''
  formOpen.value = true
}

async function saveModel() {
  if (saving.value) return
  formError.value = ''
  const modelId = form.modelId.trim()
  const displayName = form.displayName.trim()
  if (!modelId) { formError.value = t('modelManagement.modelIdRequired'); return }
  if (!/^[A-Za-z0-9._:/-]+$/.test(modelId)) { formError.value = t('modelManagement.modelIdFormat'); return }
  if (!displayName) { formError.value = t('modelManagement.displayNameRequired'); return }
  // On edit, an empty string asks the backend to re-infer the provider
  // (null would mean "keep the current value").
  const provider = form.provider.trim() || (editing.value ? '' : null)

  saving.value = true
  try {
    if (editing.value) {
      const result = await apolloClient.mutate<{ updateConfigModel: ManagedModel | null }>({
        mutation: UPDATE_CONFIG_MODEL_MUTATION,
        variables: {
          modelId,
          displayName,
          provider,
          isDefault: form.isDefault && !editing.value.isDefault ? true : null,
        },
        fetchPolicy: 'no-cache', errorPolicy: 'none',
      })
      if (!result.data?.updateConfigModel) throw new Error(t('modelManagement.notFound'))
    } else {
      const result = await apolloClient.mutate<{ createConfigModel: ManagedModel }>({
        mutation: CREATE_CONFIG_MODEL_MUTATION,
        variables: { modelId, displayName, provider, isDefault: form.isDefault },
        fetchPolicy: 'no-cache', errorPolicy: 'none',
      })
      if (!result.data?.createConfigModel) throw new Error(t('modelManagement.saveError'))
    }
    formOpen.value = false
    message.success(t('modelManagement.saved'))
    await loadModels()
    emit('changed')
  } catch (error) {
    formError.value = errorText(error, 'saveError')
  } finally {
    saving.value = false
  }
}

async function setDefault(model: ManagedModel) {
  if (busy[model.modelId]) return
  busy[model.modelId] = 'default'
  try {
    await apolloClient.mutate({
      mutation: UPDATE_CONFIG_MODEL_MUTATION,
      variables: { modelId: model.modelId, isDefault: true },
      fetchPolicy: 'no-cache', errorPolicy: 'none',
    })
    message.success(t('modelManagement.defaultSet', { name: model.displayName }))
    await loadModels()
    emit('changed')
  } catch (error) {
    message.error(errorText(error, 'saveError'))
  } finally {
    delete busy[model.modelId]
  }
}

async function deleteModel(model: ManagedModel) {
  if (busy[model.modelId]) return
  busy[model.modelId] = 'delete'
  try {
    const result = await apolloClient.mutate<{ deleteConfigModel: boolean }>({
      mutation: DELETE_CONFIG_MODEL_MUTATION,
      variables: { modelId: model.modelId },
      fetchPolicy: 'no-cache', errorPolicy: 'none',
    })
    if (!result.data?.deleteConfigModel) throw new Error(t('modelManagement.notFound'))
    message.success(t('modelManagement.deleted'))
    await loadModels()
    emit('changed')
  } catch (error) {
    message.error(errorText(error, 'deleteError'))
  } finally {
    delete busy[model.modelId]
  }
}

onMounted(loadModels)
</script>

<style scoped>
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
h2 { font-size: 20px; color: var(--text-main); margin: 0 0 4px; }
.page-header p { color: var(--text-secondary); margin: 0; }
.error-alert { margin-bottom: 16px; }
.default-tag { margin-left: 8px; }
code { font-size: 12px; }
</style>
