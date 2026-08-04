import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

const check = {
  check_id: 'delta-part-sdk', display_name: 'Part / Delta', description: 'Bounded read',
  physical_source: 'Delta Lake · MinIO', access_method: 'python_sdk', catalog: 'demo_catalog.catalog',
  source_owner: 'Public source owner', source_uri: 's3://public/example', source_version: 'v1',
  source_license: 'CC-BY-4.0', source_documentation_url: 'https://example.com/source',
  database: 'tpch', table: 'part', environment: 'local', credential_profile: 'doctor_reader',
  query_description: 'Select declared columns with literals redacted.', spec_version: '1', spec_hash: 'a'.repeat(64),
  validation_contract: { expected_row_count: 10, selected_columns: ['partkey', 'name'], sort_columns: ['partkey'], expected_sha256: 'b'.repeat(64) },
  latest_outcome: { health: 'healthy', checked_at: new Date().toISOString(), user_query_latency_ms: 12.5, phase_timings: [], total_probe_duration_ms: 14, failure_stage: null, failure_mode: null, failure_summary: null, spec_version: '1', spec_hash: 'a'.repeat(64), app_version: '0.1.0', datarepo_version: '0.0.2' },
  schedule: { interval_minutes: 60, phase_offset_minutes: 0, next_run_at: new Date(Date.now()+3600000).toISOString(), enabled: true },
  job: { status: 'idle' },
} as const

describe('dashboard', () => {
  afterEach(() => vi.restoreAllMocks())
  it('shows binary health, successful latency, and details', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      return { ok: true, json: async () => url.endsWith('/api/checks') ? [check] : check } as Response
    })
    render(<App />)
    expect(await screen.findByText('12.5 ms')).toBeInTheDocument()
    expect(screen.getAllByText('Healthy').length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: /part \/ delta/i }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('doctor_reader')
    expect(dialog).toHaveTextContent('10 exact rows')
    expect(dialog).toHaveTextContent('Public source owner')
  })
})
