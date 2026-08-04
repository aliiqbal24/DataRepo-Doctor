import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Check } from './types'

const intervals = [5, 15, 30, 60, 120, 360, 720, 1440]

function relativeTime(value: string | undefined): string {
  if (!value) return 'Never'
  const delta = new Date(value).getTime() - Date.now()
  const minutes = Math.round(Math.abs(delta) / 60_000)
  if (minutes < 1) return delta < 0 ? 'Just now' : 'In <1m'
  if (minutes < 60) return delta < 0 ? `${minutes}m ago` : `In ${minutes}m`
  const hours = Math.round(minutes / 60)
  return delta < 0 ? `${hours}h ago` : `In ${hours}h`
}

function label(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

function HealthCell({ check }: { check: Check }) {
  const health = check.latest_outcome?.health
  return (
    <div className="state-stack">
      <span className={`health ${health ?? 'never'}`}>
        <i aria-hidden="true" />{health ? label(health) : 'Never checked'}
      </span>
      {check.job.status !== 'idle' && <span className="job-state">{label(check.job.status)}</span>}
    </div>
  )
}

function DetailDrawer({ check, onClose }: { check: Check; onClose: () => void }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', close)
    return () => document.removeEventListener('keydown', close)
  }, [onClose])
  const outcome = check.latest_outcome
  return (
    <div className="drawer-wrap" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="detail-title">
        <div className="drawer-head">
          <div><span className="eyebrow">Check detail</span><h2 id="detail-title">{check.display_name}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Close details">×</button>
        </div>
        <section className="detail-section">
          <h3>Retrieval path</h3>
          <dl className="detail-grid">
            <div><dt>Catalog</dt><dd>{check.catalog}</dd></div><div><dt>Database</dt><dd>{check.database}</dd></div>
            <div><dt>Table</dt><dd>{check.table}</dd></div><div><dt>Access</dt><dd>{label(check.access_method)}</dd></div>
            <div><dt>Environment</dt><dd>{check.environment}</dd></div><div><dt>Identity</dt><dd>{check.credential_profile}</dd></div>
          </dl>
          <p className="query-copy">{check.query_description}</p>
        </section>
        <section className="detail-section">
          <h3>Public source provenance</h3>
          <dl className="detail-grid">
            <div><dt>Owner</dt><dd>{check.source_owner}</dd></div><div><dt>Version</dt><dd>{check.source_version}</dd></div>
            <div><dt>License</dt><dd>{check.source_license}</dd></div><div><dt>Location</dt><dd><code>{check.source_uri}</code></dd></div>
          </dl>
          {check.source_documentation_url && <a href={check.source_documentation_url} target="_blank" rel="noreferrer">Source documentation</a>}
        </section>
        <section className="detail-section">
          <h3>Validation contract</h3>
          {check.validation_contract ? <>
            <p>{check.validation_contract.expected_row_count} exact rows · {check.validation_contract.selected_columns.length} declared columns · canonical sort by {check.validation_contract.sort_columns.join(', ')}</p>
            <div className="code-row"><span>SHA-256</span><code>{check.validation_contract.expected_sha256}</code></div>
          </> : <p>Loading contract…</p>}
        </section>
        <section className="detail-section">
          <h3>Latest completed run</h3>
          {!outcome && <p>No completed run yet.</p>}
          {outcome?.health === 'healthy' && <>
            <div className="hero-metric"><strong>{outcome.user_query_latency_ms?.toFixed(1)}</strong><span>ms user query latency</span></div>
            <div className="phases">{outcome.phase_timings.map((phase) => <div key={phase.name}><span>{label(phase.name)}</span><strong>{phase.duration_ms.toFixed(1)} ms</strong></div>)}</div>
            <p className="total">Total probe duration {outcome.total_probe_duration_ms.toFixed(1)} ms</p>
          </>}
          {outcome?.health === 'unhealthy' && <div className="failure-box">
            <div><span>Stage</span><strong>{label(outcome.failure_stage ?? 'unknown')}</strong></div>
            <div><span>Mode</span><strong>{label(outcome.failure_mode ?? 'unknown')}</strong></div>
            <p>{outcome.failure_summary}</p>
          </div>}
        </section>
        <section className="detail-section compact">
          <h3>Build provenance</h3>
          <dl className="detail-grid"><div><dt>Spec</dt><dd>v{check.spec_version}</dd></div><div><dt>App</dt><dd>{outcome?.app_version ?? '—'}</dd></div><div><dt>DataRepo</dt><dd>{outcome?.datarepo_version ?? '—'}</dd></div></dl>
          <div className="code-row"><span>Spec hash</span><code>{check.spec_hash}</code></div>
        </section>
      </aside>
    </div>
  )
}

export default function App() {
  const [checks, setChecks] = useState<Check[]>([])
  const [selected, setSelected] = useState<Check | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/checks')
      if (!response.ok) throw new Error('request failed')
      const result: Check[] = await response.json()
      setChecks(result); setError(null)
      setSelected((current) => {
        if (!current) return null
        const refreshed = result.find((item) => item.check_id === current.check_id)
        return refreshed
          ? { ...current, ...refreshed, validation_contract: current.validation_contract }
          : null
      })
    } catch { setError('Dashboard data is temporarily unavailable.') }
  }, [])

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0)
    const timer = window.setInterval(() => void load(), 2000)
    return () => { window.clearTimeout(initial); window.clearInterval(timer) }
  }, [load])

  const openDetail = async (check: Check) => {
    setSelected(check)
    const response = await fetch(`/api/checks/${check.check_id}`)
    if (response.ok) setSelected(await response.json())
  }
  const run = async (check: Check) => { await fetch(`/api/checks/${check.check_id}/run`, { method: 'POST' }); await load() }
  const updateInterval = async (check: Check, interval: number) => {
    await fetch(`/api/checks/${check.check_id}/schedule`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ interval_minutes: interval }) })
    await load()
  }
  const counts = useMemo(() => ({
    healthy: checks.filter((c) => c.latest_outcome?.health === 'healthy').length,
    unhealthy: checks.filter((c) => c.latest_outcome?.health === 'unhealthy').length,
    unchecked: checks.filter((c) => !c.latest_outcome).length,
  }), [checks])

  return <>
    <header className="topbar"><div className="brand-mark" aria-hidden="true">D</div><div><strong>DataRepo Doctor</strong><span>Retrieval monitor</span></div><div className="profile"><i aria-hidden="true" />doctor_reader · public internet</div></header>
    <main>
      <section className="intro">
        <div><span className="eyebrow">Live public-source retrieval health</span><h1>Can scientists get the whole result?</h1><p>Real, bounded reads from public AWS, PUDL, and RNAcentral sources through supported DataRepo access paths. Health means the complete result passed schema, row count, and fingerprint validation.</p></div>
        <div className="summary" aria-label="Check summary"><div><strong>{counts.healthy}</strong><span>Healthy</span></div><div><strong>{counts.unhealthy}</strong><span>Unhealthy</span></div><div><strong>{counts.unchecked}</strong><span>Not checked</span></div></div>
      </section>
      {error && <div className="error-banner" role="alert">{error}</div>}
      <section className="panel">
        <div className="panel-head"><div><h2>Access-path checks</h2><p>Sequential execution · latest completed outcome only</p></div><span className="live"><i />Polling live</span></div>
        <div className="table-scroll"><table><thead><tr><th>Check</th><th>Source / access</th><th>Latest health</th><th>Latency</th><th>Last checked</th><th>Next run</th><th>Interval</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{checks.map((check) => <tr key={check.check_id}>
            <td><button className="check-link" onClick={() => void openDetail(check)}><strong>{check.display_name}</strong><span>{check.table}</span></button></td>
            <td><strong>{check.physical_source}</strong><span className="method">{check.access_method === 'python_sdk' ? 'Python SDK' : 'ROAPI HTTP'}</span></td>
            <td><HealthCell check={check} /></td>
            <td className="latency">{check.latest_outcome?.health === 'healthy' ? `${check.latest_outcome.user_query_latency_ms?.toFixed(1)} ms` : '—'}</td>
            <td title={check.latest_outcome?.checked_at}>{relativeTime(check.latest_outcome?.checked_at)}</td>
            <td title={check.schedule.next_run_at}>{check.schedule.enabled ? relativeTime(check.schedule.next_run_at) : 'Disabled'}</td>
            <td><select aria-label={`Interval for ${check.display_name}`} value={check.schedule.interval_minutes} onChange={(e) => void updateInterval(check, Number(e.target.value))}>{intervals.map((value) => <option value={value} key={value}>{value < 60 ? `${value}m` : `${value / 60}h`}</option>)}</select></td>
            <td><button className="run-button" disabled={check.job.status !== 'idle'} onClick={() => void run(check)}>{check.job.status === 'idle' ? 'Check now' : label(check.job.status)}</button></td>
          </tr>)}</tbody></table></div>
        {!checks.length && !error && <div className="loading">Loading configured checks…</div>}
      </section>
      <p className="footnote">Latency is descriptive and never changes health. Failed and timed-out checks show no query latency.</p>
    </main>
    {selected && <DetailDrawer check={selected} onClose={() => setSelected(null)} />}
  </>
}
