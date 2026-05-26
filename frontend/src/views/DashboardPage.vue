<template>
  <div class="dashboard-page">
    <!-- Decorative Ambient Glows in Background -->
    <div class="ambient-glow glow-1"></div>
    <div class="ambient-glow glow-2"></div>
    
    <div class="content">
      <!-- Premium Header Section -->
      <div class="page-header">
        <div class="header-text">
          <h1>{{ t('dashboard.title', 'Dashboard') }}</h1>
          <p class="subtitle">{{ t('dashboard.subtitle', 'View your translation statistics and thesaurus overview.') }}</p>
        </div>
        <a-button
          type="primary"
          size="large"
          class="workspace-btn glass-btn"
          @click="router.push('/main')"
        >
          <template #icon>
            <TranslationOutlined />
          </template>
          {{ t('nav.main', 'Translation') }}
        </a-button>
      </div>

      <!-- Loading State -->
      <div v-if="loading" class="loader-container glass-card">
        <a-spin size="large">
          <template #indicator>
            <LoadingOutlined class="spin-indicator" spin />
          </template>
        </a-spin>
        <span class="loading-text">{{ t('progress.loading', 'Loading statistics...') }}</span>
      </div>

      <!-- Error State -->
      <div v-else-if="error" class="error-container glass-card">
        <CloseCircleOutlined class="error-icon" />
        <h3>{{ t('error.unexpectedError', 'An unexpected error occurred') }}</h3>
        <p class="error-desc">{{ error.message || t('error.unknown', 'Failed to retrieve stats') }}</p>
        <a-button type="primary" class="retry-btn" @click="fetchStats">
          <template #icon>
            <ReloadOutlined />
          </template>
          {{ t('error.retry', 'Retry') }}
        </a-button>
      </div>

      <!-- Statistics Dashboard Content -->
      <div v-else class="dashboard-grid">
        <a-row :gutter="[24, 24]">
          <!-- Card 1: Translated Documents -->
          <a-col :xs="24" :sm="12" :md="6">
            <div class="stat-card glass-card card-emerald">
              <div class="card-bg-gradient"></div>
              <div class="card-inner">
                <div class="icon-wrapper">
                  <FileDoneOutlined class="stat-icon" />
                </div>
                <div class="stat-content">
                  <span class="stat-label">{{ t('dashboard.translatedDocs', 'Translated Documents') }}</span>
                  <h2 class="stat-value Outfit">
                    {{ formattedDocsCount }}
                  </h2>
                  <p class="stat-desc">{{ t('dashboard.translatedDocsDesc', 'Successfully completed files') }}</p>
                </div>
              </div>
            </div>
          </a-col>

          <!-- Card 2: Translated Paragraphs -->
          <a-col :xs="24" :sm="12" :md="6">
            <div class="stat-card glass-card card-sapphire">
              <div class="card-bg-gradient"></div>
              <div class="card-inner">
                <div class="icon-wrapper">
                  <FieldBinaryOutlined class="stat-icon" />
                </div>
                <div class="stat-content">
                  <span class="stat-label">{{ t('dashboard.translatedItems', 'Translated Paragraphs/Cells') }}</span>
                  <h2 class="stat-value Outfit">
                    {{ formattedItemsCount }}
                  </h2>
                  <p class="stat-desc">{{ t('dashboard.translatedItemsDesc', 'Total translated text items') }}</p>
                </div>
              </div>
            </div>
          </a-col>

          <!-- Card 3: Term Catalogs -->
          <a-col :xs="24" :sm="12" :md="6">
            <div class="stat-card glass-card card-amber">
              <div class="card-bg-gradient"></div>
              <div class="card-inner">
                <div class="icon-wrapper">
                  <FolderOpenOutlined class="stat-icon" />
                </div>
                <div class="stat-content">
                  <span class="stat-label">{{ t('dashboard.termCatalogs', 'Term Catalogs') }}</span>
                  <h2 class="stat-value Outfit">
                    {{ formattedCatalogsCount }}
                  </h2>
                  <p class="stat-desc">{{ t('dashboard.termCatalogsDesc', 'Number of catalogs organizing term pairs') }}</p>
                </div>
              </div>
            </div>
          </a-col>

          <!-- Card 4: Total Term Pairs -->
          <a-col :xs="24" :sm="12" :md="6">
            <div class="stat-card glass-card card-violet">
              <div class="card-bg-gradient"></div>
              <div class="card-inner">
                <div class="icon-wrapper">
                  <BookOutlined class="stat-icon" />
                </div>
                <div class="stat-content">
                  <span class="stat-label">{{ t('dashboard.termPairs', 'Total Term Pairs') }}</span>
                  <h2 class="stat-value Outfit">
                    {{ formattedTermPairsCount }}
                  </h2>
                  <p class="stat-desc">{{ t('dashboard.termPairsDesc', 'Configured translation dictionary terms') }}</p>
                </div>
              </div>
            </div>
          </a-col>
        </a-row>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useQuery } from '@/composables/useGraphQL'
import { useLanguage } from '@/composables/useLanguage'
import { DASHBOARD_STATS_QUERY } from '@/graphql/queries'
import {
  FileDoneOutlined,
  BookOutlined,
  FieldBinaryOutlined,
  FolderOpenOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  TranslationOutlined
} from '@ant-design/icons-vue'

const router = useRouter()
const { t } = useLanguage()

// GraphQL Query Integration
const { data, loading, error, execute } = useQuery<{
  dashboardStats: {
    translatedDocuments: number
    termPairs: number
    translatedItems: number
    termCatalogs: number
  }
}>(DASHBOARD_STATS_QUERY)

// Fetch helper
async function fetchStats() {
  try {
    await execute()
  } catch (err) {
    console.error('Failed to load dashboard statistics:', err)
  }
}

// Lifecycle Hook
onMounted(() => {
  fetchStats()
})

// Number Format Helpers scoped to selected language
const localeFormatter = computed(() => {
  const code = localStorage.getItem('ui_lang') || 'zh'
  const locale = code === 'zh' ? 'zh-CN' : code === 'vi' ? 'vi-VN' : 'en-US'
  return new Intl.NumberFormat(locale)
})

const formattedDocsCount = computed(() => {
  const val = data.value?.dashboardStats?.translatedDocuments ?? 0
  return localeFormatter.value.format(val)
})

const formattedItemsCount = computed(() => {
  const val = data.value?.dashboardStats?.translatedItems ?? 0
  return localeFormatter.value.format(val)
})

const formattedCatalogsCount = computed(() => {
  const val = data.value?.dashboardStats?.termCatalogs ?? 0
  return localeFormatter.value.format(val)
})

const formattedTermPairsCount = computed(() => {
  const val = data.value?.dashboardStats?.termPairs ?? 0
  return localeFormatter.value.format(val)
})
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&display=swap');

.dashboard-page {
  min-height: calc(100vh - 64px);
  background: transparent;
  position: relative;
  overflow: hidden;
}

.content {
  padding: 40px 24px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
  position: relative;
  z-index: 10;
}

/* Ambient glow backgrounds */
.ambient-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(120px);
  opacity: 0.15;
  z-index: 1;
  pointer-events: none;
}

.glow-1 {
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, var(--primary-color) 0%, transparent 70%);
  top: -100px;
  right: -50px;
}

.glow-2 {
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, #818cf8 0%, transparent 70%);
  bottom: -150px;
  left: -100px;
}

/* Header design */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 40px;
  flex-wrap: wrap;
  gap: 20px;
}

.header-text h1 {
  font-family: 'Outfit', sans-serif;
  font-size: 32px;
  font-weight: 700;
  color: var(--text-main);
  margin-bottom: 8px;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, var(--text-main) 0%, rgba(var(--text-main-rgb), 0.7) 100%);
  -webkit-background-clip: text;
  background-clip: text;
}

.subtitle {
  color: var(--text-secondary);
  font-size: 16px;
  margin-bottom: 0;
}

.workspace-btn {
  height: 48px;
  padding: 0 24px;
  font-size: 15px;
  font-weight: 600;
  border-radius: 24px;
  border: none;
  background: linear-gradient(135deg, var(--primary-color) 0%, var(--primary-hover) 100%);
  box-shadow: 0 4px 16px rgba(126, 197, 0, 0.25);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  gap: 8px;
}

.workspace-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(126, 197, 0, 0.35);
}

.workspace-btn:active {
  transform: translateY(0);
}

/* Loading & Error States */
.loader-container, .error-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 24px;
  text-align: center;
  min-height: 350px;
}

.spin-indicator {
  font-size: 38px;
  color: var(--primary-color);
}

.loading-text {
  margin-top: 20px;
  font-size: 15px;
  color: var(--text-secondary);
  font-weight: 500;
}

.error-icon {
  font-size: 48px;
  color: var(--error-color);
  margin-bottom: 20px;
}

.error-container h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-main);
  margin-bottom: 8px;
}

.error-desc {
  color: var(--text-secondary);
  max-width: 400px;
  margin-bottom: 24px;
}

.retry-btn {
  height: 40px;
  border-radius: 20px;
  padding: 0 20px;
  font-weight: 500;
}

/* Premium Statistics Cards */
.dashboard-grid {
  width: 100%;
}

.stat-card {
  position: relative;
  border: 1px solid var(--border-color);
  border-radius: 24px;
  padding: 28px 20px;
  overflow: hidden;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  height: 100%;
  cursor: default;
}

.stat-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.08);
  border-color: rgba(var(--card-accent-rgb), 0.4);
}

.card-bg-gradient {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 0.03;
  z-index: 1;
  background: linear-gradient(135deg, var(--card-accent) 0%, transparent 100%);
  transition: opacity 0.3s;
}

.stat-card:hover .card-bg-gradient {
  opacity: 0.08;
}

.card-inner {
  display: flex;
  gap: 16px;
  position: relative;
  z-index: 2;
}

.icon-wrapper {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(var(--card-accent-rgb), 0.1);
  color: var(--card-accent);
  transition: all 0.3s;
  flex-shrink: 0;
}

.stat-icon {
  font-size: 22px;
}

.stat-card:hover .icon-wrapper {
  background: var(--card-accent);
  color: #ffffff;
  transform: scale(1.05) rotate(5deg);
  box-shadow: 0 8px 16px rgba(var(--card-accent-rgb), 0.3);
}

.stat-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  text-align: left;
  min-width: 0;
}

.stat-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-value {
  font-family: 'Outfit', sans-serif;
  font-size: 34px;
  font-weight: 700;
  color: var(--text-main);
  line-height: 1.1;
  margin: 0 0 6px 0;
  letter-spacing: -1px;
}

.stat-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 0;
  line-height: 1.4;
}

/* Light / Dark themed accent settings */
.card-emerald {
  --card-accent: #10b981;
  --card-accent-rgb: 16, 185, 129;
}

.card-sapphire {
  --card-accent: #2563eb;
  --card-accent-rgb: 37, 99, 235;
}

.card-amber {
  --card-accent: #d97706;
  --card-accent-rgb: 217, 119, 6;
}

.card-violet {
  --card-accent: #8b5cf6;
  --card-accent-rgb: 139, 92, 246;
}

/* Glassmorphism custom components */
.glass-card {
  background: var(--glass-card-bg, rgba(255, 255, 255, 0.4));
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  box-shadow: var(--shadow-sm);
}

/* Responsive queries */
@media (max-width: 768px) {
  .content {
    padding: 24px 16px;
  }
  
  .page-header {
    margin-bottom: 24px;
  }
  
  .header-text h1 {
    font-size: 26px;
  }
  
  .stat-value {
    font-size: 30px;
  }
  
  .stat-card {
    padding: 20px;
  }
}
</style>
