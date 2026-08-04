export type Health = 'healthy' | 'unhealthy'
export type JobStatus = 'idle' | 'queued' | 'running'

export interface PhaseTiming { name: string; duration_ms: number }
export interface Outcome {
  health: Health
  checked_at: string
  user_query_latency_ms: number | null
  phase_timings: PhaseTiming[]
  total_probe_duration_ms: number
  failure_stage: string | null
  failure_mode: string | null
  failure_summary: string | null
  spec_version: string
  spec_hash: string
  app_version: string
  datarepo_version: string
}
export interface Schedule {
  interval_minutes: number
  phase_offset_minutes: number
  next_run_at: string
  enabled: boolean
}
export interface Check {
  check_id: string
  display_name: string
  description: string
  physical_source: string
  access_method: 'python_sdk' | 'roapi_http'
  catalog: string
  database: string
  table: string
  environment: string
  credential_profile: string
  query_description: string
  spec_version: string
  spec_hash: string
  latest_outcome: Outcome | null
  schedule: Schedule
  job: { status: JobStatus }
  validation_contract?: {
    selected_columns: string[]
    sort_columns: string[]
    expected_schema: { name: string; type: string; nullable: boolean }[]
    expected_row_count: number
    expected_sha256: string
    timeout_seconds: number
  }
}

