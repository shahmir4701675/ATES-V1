import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, Info, Play, RotateCcw, XCircle } from 'lucide-react'
import { Button, Card, Field, LoadState, Notice, PageHeader, SelectField, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { cancelGeneration, errorMessage, generateSchedule, getConfigs, getScheduleStatus, getTerms } from '../services/api'
import type { GenerationConfig, GenerationStatus, ScheduleType } from '../types'

const POLL_MS = 2000
const MIN_LIMIT = 10
const MAX_LIMIT = 600

export function GeneratePage({ onNavigate, onStatus }: { onNavigate: (path: string) => void; onStatus: (message: string) => void }) {
  const terms = useAsync(getTerms, [])
  const [config, setConfig] = useState<GenerationConfig>({ term_id: '', schedule_type: 'Timetable', time_limit: 120 })
  const [configId, setConfigId] = useState('')
  const [run, setRun] = useState<GenerationStatus | null>(null)
  const [error, setError] = useState('')
  const [pollError, setPollError] = useState('')
  const timer = useRef<number | undefined>(undefined)
  const stopPolling = () => { if (timer.current !== undefined) { window.clearInterval(timer.current); timer.current = undefined } }
  useEffect(() => stopPolling, [])

  const termId = config.term_id || terms.data?.find((term) => term.status === 'Active')?.term_id || terms.data?.[0]?.term_id || ''
  const configs = useAsync(() => (termId ? getConfigs(termId, config.schedule_type) : Promise.resolve([])), [termId, config.schedule_type])
  const selectedConfig = configs.data?.find((item) => item.config_id === configId)
  const limitInvalid = !Number.isFinite(config.time_limit) || config.time_limit < MIN_LIMIT || config.time_limit > MAX_LIMIT
  const generating = run?.status === 'Generating'

  const poll = async (runId: string) => {
    try {
      const next = await getScheduleStatus(runId)
      setPollError('')
      setRun(next)
      if (next.status !== 'Generating') { stopPolling(); onStatus(next.message) }
    } catch (reason) {
      setPollError(errorMessage(reason))
    }
  }

  const start = async () => {
    setError('')
    if (limitInvalid) { setError(`Time limit must be between ${MIN_LIMIT} and ${MAX_LIMIT} seconds.`); return }
    if (!termId) { setError('No academic term is available. Create a term in Data management first.'); return }
    try {
      const limit = selectedConfig ? config.time_limit : config.time_limit
      const { run_id } = await generateSchedule({ ...config, term_id: termId, time_limit: limit, config_id: configId || undefined })
      setRun({ run_id, status: 'Generating', solver_status: 'Running', progress: 0, elapsed_seconds: 0, message: 'Run accepted by the server', result: null })
      onStatus(`Generating ${config.schedule_type.toLowerCase()}…`)
      stopPolling()
      timer.current = window.setInterval(() => void poll(run_id), POLL_MS)
      void poll(run_id)
    } catch (reason) {
      setError(errorMessage(reason))
    }
  }

  const cancel = () => {
    if (!run) return
    cancelGeneration(run.run_id)
    void poll(run.run_id)
    onStatus('Stopped following the run. No schedule was published.')
  }

  const reset = () => { stopPolling(); setConfig({ term_id: '', schedule_type: 'Timetable', time_limit: 120 }); setConfigId(''); setRun(null); setError(''); setPollError('') }
  const result = run?.result
  const type = config.schedule_type

  return <div className="page-stack">
    <PageHeader eyebrow="Generate" title="Generate schedule" description="Choose the term, schedule type and configuration, then start the solver. The page checks the server every 2 seconds until the run ends." />
    {error && <div className="validation-summary" role="alert"><AlertTriangle size={18} /><div><strong>Review the highlighted field</strong><p>{error}</p></div></div>}
    <LoadState loading={terms.loading} error={terms.error} onRetry={terms.reload}>
      <section className="section-grid two-columns generate-layout">
        <Card title="Generation parameters"><div className="form-grid">
          <SelectField label="Term" value={termId} onChange={(value) => { setConfig((current) => ({ ...current, term_id: value })); setConfigId('') }} options={(terms.data ?? []).map((term) => ({ value: term.term_id, label: `${term.label}${term.status === 'Active' ? ' (active)' : ''}` }))} hint="Schedules are generated against one academic term." id="term" />
          <SelectField label="Schedule type" value={type} onChange={(value) => { setConfig((current) => ({ ...current, schedule_type: value as ScheduleType })); setConfigId('') }} options={[{ value: 'Timetable', label: 'Timetable' }, { value: 'Exam schedule', label: 'Exam schedule' }]} hint="Choose the record that the solver should produce." id="schedule-type" />
          <SelectField label="Configuration" value={configId} onChange={(value) => { setConfigId(value); const chosen = configs.data?.find((item) => item.config_id === value); if (chosen) setConfig((current) => ({ ...current, time_limit: chosen.solver_time_limit_s })) }} options={[{ value: '', label: 'Server default for this term' }, ...(configs.data ?? []).map((item) => ({ value: item.config_id, label: item.name }))]} hint="Constraint set, weights and solver settings. Manage them in Settings." id="config" />
          <Field label="Time limit" htmlFor="time-limit" hint={`Allowed range: ${MIN_LIMIT}–${MAX_LIMIT} seconds. Default is 120 seconds.`} error={limitInvalid ? `Enter a whole number from ${MIN_LIMIT} to ${MAX_LIMIT}.` : undefined}><div className="input-with-suffix"><input id="time-limit" className="tabular" type="number" min={MIN_LIMIT} max={MAX_LIMIT} value={config.time_limit} aria-invalid={limitInvalid} onChange={(event) => setConfig((current) => ({ ...current, time_limit: Number(event.target.value) }))} /><span>seconds</span></div></Field>
        </div>
        <div className="form-actions"><Button variant="secondary" icon={RotateCcw} onClick={reset}>Reset</Button><Button variant="secondary" icon={XCircle} onClick={cancel} disabled={!generating}>Cancel</Button><Button icon={Play} onClick={start} disabled={generating}>{generating ? 'Generating…' : 'Generate schedule'}</Button></div></Card>
        <div className="generation-side">
          <Card title="Run guidance"><div className="guidance-list">
            <div><span className="guidance-number">01</span><span><strong>Validate constraints</strong><small>Room capacity, instructor availability and blocked slots are checked by the solver.</small></span></div>
            <div><span className="guidance-number">02</span><span><strong>Search assignments</strong><small>The server reports the final state; progress shown while running is the share of the time limit used.</small></span></div>
            <div><span className="guidance-number">03</span><span><strong>Review before publish</strong><small>Generated versions stay separate from the published version until an Approver publishes them.</small></span></div>
          </div><div className="helper-callout"><Info size={16} /><span>A run creates a new version. The published schedule is never changed by generation.</span></div></Card>
          {pollError && <Notice tone="warning" title="Status check failed">{pollError} The page will keep trying every 2 seconds.</Notice>}
          {run && <Card title="Generation status" className="generation-status-card"><div className="run-status-header"><div><StatusBadge status={run.status} /><h3>{run.message}</h3></div><span className="run-time tabular">{run.elapsed_seconds}s</span></div>
            <div className="progress-track" aria-label={`Share of time limit used ${run.progress}%`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={run.progress}><span style={{ width: `${run.progress}%` }} /></div>
            <div className="progress-meta"><span>{run.progress}% {generating ? 'of time limit used' : 'complete'}</span><span>Solver: {run.solver_status}</span></div>
            {generating && <div className="polling-note"><Clock3 size={14} /> Polling every 2 seconds</div>}
            {run.status === 'Draft' && <div className="cancelled-note"><XCircle size={15} /> You stopped following this run before a result was shown.</div>}
          </Card>}
        </div>
      </section>
      {result && run && <Card title="Result summary" actions={<StatusBadge status={run.status} />}>
        <div className="result-grid">
          <div><span>Version</span><strong className="tabular">{result.version_no ?? '—'}</strong></div>
          <div><span>Solver status</span><strong><StatusBadge status={run.solver_status} /></strong></div>
          <div><span>Run time</span><strong className="tabular">{run.elapsed_seconds}s</strong></div>
          <div><span>Hard-constraint violations</span><strong className={`tabular ${result.hard_constraint_violations === 0 ? 'success-text' : 'text-danger'}`}>{result.hard_constraint_violations}</strong></div>
          <div><span>Soft score</span><strong className="tabular">{result.soft_score}</strong></div>
          <div><span>{type === 'Timetable' ? 'Sessions' : 'Exams'} scheduled</span><strong className="tabular">{result.entry_count ?? '—'}</strong></div>
          <div><span>Conflict records</span><strong className="tabular">{result.conflict_count ?? '—'}</strong></div>
        </div>
        <div className="result-footer"><div>{run.status === 'Generated' ? <><CheckCircle2 size={17} /><span>Review the generated version before requesting approval.</span></> : <><AlertTriangle size={17} /><span>This run produced no usable schedule. Review the conflict report.</span></>}</div>
          <div className="result-links"><button type="button" onClick={() => onNavigate(type === 'Timetable' ? '/timetable' : '/exams')}>View {type === 'Timetable' ? 'timetable' : 'exam schedule'} <ArrowRight size={14} /></button><button type="button" onClick={() => onNavigate('/conflicts')}>Conflict report <ArrowRight size={14} /></button></div></div>
      </Card>}
    </LoadState>
  </div>
}
