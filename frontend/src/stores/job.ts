import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { TranslationJob, JobStatus } from '@/types'
import { apolloClient } from '@/services/apollo'
import { JOB_HISTORY_QUERY } from '@/graphql/queries'

// Filter interface for job history queries
export interface JobHistoryFilters {
  status?: JobStatus
  dateFrom?: string
  dateTo?: string
}

// Response types for GraphQL query
interface JobHistoryResponse {
  jobHistory: {
    jobs: TranslationJob[]
    total: number
    page: number
    pageSize: number
    hasNext: boolean
  }
}

export const useJobStore = defineStore('job', () => {
  // Helper to deep clone objects (removes Apollo's freeze)
  // Apollo Client freezes query/mutation results to prevent cache corruption,
  // so we need to clone before storing/modifying
  function deepClone<T>(obj: T): T {
    return JSON.parse(JSON.stringify(obj))
  }

  // Current session state (in-memory)
  const currentJob = ref<TranslationJob | null>(null)
  const jobs = ref<TranslationJob[]>([])
  const isPolling = ref(false)

  // Pagination state for API-based fetching
  const currentPage = ref<number>(1)
  const pageSize = ref<number>(20)
  const totalJobs = ref<number>(0)
  const isLoadingHistory = ref<boolean>(false)

  // Computed properties
  const activeJobs = computed(() =>
    jobs.value.filter((job: TranslationJob) =>
      job.status === 'PROCESSING' || job.status === 'PENDING'
    )
  )

  const completedJobs = computed(() =>
    jobs.value.filter((job: TranslationJob) =>
      job.status === 'COMPLETED' ||
      job.status === 'FAILED' ||
      job.status === 'PARTIAL_SUCCESS'
    )
  )

  const hasActiveJob = computed(() => activeJobs.value.length > 0)

  /**
   * Fetch job history from backend API
   * @param page Page number to fetch (defaults to currentPage)
   * @param filters Optional filters for the query
   */
  async function fetchJobHistory(page?: number, filters?: JobHistoryFilters): Promise<void> {
    isLoadingHistory.value = true

    try {
      const variables = {
        page: page ?? currentPage.value,
        pageSize: pageSize.value,
        status: filters?.status,
        dateFrom: filters?.dateFrom,
        dateTo: filters?.dateTo,
      }

      const result = await apolloClient.query<JobHistoryResponse>({
        query: JOB_HISTORY_QUERY,
        variables,
        fetchPolicy: 'network-only',
      })

      if (result.data?.jobHistory) {
        const { jobs: fetchedJobs, total, page: responsePage, pageSize: responsePageSize } = result.data.jobHistory
        jobs.value = fetchedJobs.map(deepClone)
        totalJobs.value = total
        currentPage.value = responsePage
        pageSize.value = responsePageSize
      }
    } catch (error) {
      console.error('Failed to fetch job history:', error)
      throw error
    } finally {
      isLoadingHistory.value = false
    }
  }

  /**
   * Navigate to a specific page
   */
  async function setPage(page: number, filters?: JobHistoryFilters): Promise<void> {
    await fetchJobHistory(page, filters)
  }

  /**
   * Change page size and reset to page 1
   */
  async function setPageSize(size: number, filters?: JobHistoryFilters): Promise<void> {
    pageSize.value = size
    await fetchJobHistory(1, filters)
  }

  /**
   * Reset pagination state
   */
  function resetPagination(): void {
    currentPage.value = 1
    totalJobs.value = 0
  }

  /**
   * Set the current active job
   */
  function setCurrentJob(job: TranslationJob) {
    const clonedJob = deepClone(job)
    currentJob.value = clonedJob
    updateJob(clonedJob)
  }

  /**
   * Update a job in the store (in-memory only)
   */
  function updateJob(job: TranslationJob) {
    const clonedJob = deepClone(job)
    const index = jobs.value.findIndex((j: TranslationJob) => j.id === clonedJob.id)
    if (index !== -1) {
      // Create new array to avoid mutating frozen arrays
      jobs.value = [
        ...jobs.value.slice(0, index),
        clonedJob,
        ...jobs.value.slice(index + 1)
      ]
    } else {
      jobs.value = [...jobs.value, clonedJob]
    }

    if (currentJob.value?.id === clonedJob.id) {
      currentJob.value = clonedJob
    }
  }

  /**
   * Add a new job to the store (in-memory only)
   */
  function addJob(job: TranslationJob) {
    // Clone and create new array to avoid mutating frozen Apollo objects
    jobs.value = [deepClone(job), ...jobs.value]
  }

  /**
   * Clear the current job
   */
  function clearCurrentJob() {
    currentJob.value = null
  }

  /**
   * Get a job by ID
   */
  function getJobById(id: string): TranslationJob | undefined {
    return jobs.value.find((job: TranslationJob) => job.id === id)
  }

  /**
   * Remove a job from the store (in-memory only)
   */
  function removeJob(id: string) {
    jobs.value = jobs.value.filter((job: TranslationJob) => job.id !== id)

    if (currentJob.value?.id === id) {
      clearCurrentJob()
    }
  }

  /**
   * Clear all completed jobs (in-memory only)
   */
  function clearCompletedJobs() {
    jobs.value = jobs.value.filter((job: TranslationJob) =>
      job.status === 'PROCESSING' || job.status === 'PENDING'
    )
  }

  /**
   * Clear all jobs (in-memory only)
   */
  function clearAllJobs() {
    jobs.value = []
    clearCurrentJob()
    resetPagination()
  }

  /**
   * Set polling state
   */
  function setPolling(polling: boolean) {
    isPolling.value = polling
  }

  /**
   * Update job status (in-memory only)
   */
  function updateJobStatus(id: string, status: JobStatus) {
    const job = getJobById(id)
    if (job) {
      const updatedJob = { ...job, status }
      if (status === 'COMPLETED' || status === 'FAILED' || status === 'PARTIAL_SUCCESS') {
        updatedJob.completedAt = new Date().toISOString()
      }
      updateJob(updatedJob)
    }
  }

  /**
   * Update job progress (in-memory only)
   */
  function updateJobProgress(id: string, progress: number) {
    const job = getJobById(id)
    if (job) {
      updateJob({ ...job, progress })
    }
  }

  return {
    // State
    currentJob,
    jobs,
    isPolling,
    currentPage,
    pageSize,
    totalJobs,
    isLoadingHistory,

    // Computed
    activeJobs,
    completedJobs,
    hasActiveJob,

    // Actions
    fetchJobHistory,
    setPage,
    setPageSize,
    resetPagination,
    setCurrentJob,
    updateJob,
    addJob,
    clearCurrentJob,
    getJobById,
    removeJob,
    clearCompletedJobs,
    clearAllJobs,
    setPolling,
    updateJobStatus,
    updateJobProgress,
  }
})
