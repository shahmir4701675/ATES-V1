import { useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, CheckCircle2, ShieldCheck } from 'lucide-react'
import { Button, Card, LoadState, Notice, PageHeader, SelectField, StatusBadge } from '../components/ui'
import { ConfirmDialog, DataTable } from '../components/Modal'
import { useAsync } from '../hooks/useAsync'
import { errorMessage, getConflicts, getSchedules, getTerms, publishScheduleMock } from '../services/api'
import type { ConflictItem } from '../types'

export function ReviewPublishPage({ onNavigate, onStatus }: { onNavigate: (path: string) => void; onStatus: (message: string) => void }) {
  const base = useAsync(() => Promise.all([getSchedules(), getTerms()]), [])
  const [scheduleId, setScheduleId] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const schedules = base.data?.[0] ?? []
  const terms = base.data?.[1] ?? []
  const termLabel = (id: string) => terms.find((item) => item.term_id === id)?.label ?? id

  const candidates = useMemo(() => schedules.filter((item) => item.status === 'Generated').sort((a, b) => b.version_no - a.version_no), [schedules])
  const history = useMemo(() => schedules.filter((item) => item.status === 'Published' || item.status === 'Archived').sort((a, b) => b.version_no - a.version_no), [schedules])
  const selected = candidates.find((item) => item.schedule_id === scheduleId) ?? candidates[0] ?? null

  const conflicts = useAsync(() => (selected ? getConflicts(selected.schedule_id) : Promise.resolve([] as ConflictItem[])), [selected?.schedule_id])
  const conflictList = conflicts.data ?? []
  const hardCount = selected ? (selected.hard_violation_count ?? conflictList.filter((item) => item.severity === 'Hard').length) : 0
  const unit = selected?.schedule_type === 'Exam schedule' ? 'Exam entries' : 'Timetable sessions'

  const publish = async () => {
    if (!selected) return
    setBusy(true)
    setError('')
    try {
      await publishScheduleMock(selected.schedule_id)
      setConfirming(false)
      onStatus(`Published ${selected.schedule_type.toLowerCase()} version ${selected.version_no}.`)
      base.reload()
    } catch (reason) {
      setError(errorMessage(reason))
    } finally {
      setBusy(false)
    }
  }

  return <div className="page-stack">
    <PageHeader
      eyebrow="Approvals"
      title="Review and publish"
      description="Inspect generated timetable and examination versions, verify that there are zero hard-constraint violations, and publish."
    />
    {error && <Notice tone="error" title="Could not publish version">{error}</Notice>}
    <LoadState loading={base.loading || conflicts.loading} error={base.error || conflicts.error} onRetry={() => { base.reload(); conflicts.reload() }}>
      {!selected ? (
        <Notice title="No generated versions are waiting for approval">When a Coordinator generates a new timetable or exam schedule, it will appear here for review.</Notice>
      ) : (
        <Card
          title="Generated version summary"
          actions={
            <div className="card-actions">
              <Button variant="secondary" icon={ArrowRight} onClick={() => onNavigate(selected.schedule_type === 'Timetable' ? '/timetable' : '/exams')}>Open view</Button>
              <Button icon={ShieldCheck} disabled={hardCount > 0 || busy} onClick={() => setConfirming(true)}>Publish version</Button>
            </div>
          }
        >
          <div className="stack-gap">
            <SelectField
              label="Generated version"
              id="rev-version"
              value={selected.schedule_id}
              onChange={setScheduleId}
              options={candidates.map((item) => ({ value: item.schedule_id, label: `${item.schedule_type} · Version ${item.version_no} (${termLabel(item.term_id)})` }))}
            />
            <div className="stat-row">
              <div><span>{unit}</span><strong className="tabular">{selected.entry_count ?? '—'}</strong></div>
              <div><span>Soft score</span><strong className="tabular">{selected.objective_score ?? '—'}</strong></div>
              <div><span>Hard violations</span><strong className={`tabular ${hardCount === 0 ? 'success-text' : 'text-danger'}`}>{hardCount}</strong></div>
              <div><span>Total conflicts</span><strong className="tabular">{selected.conflict_count ?? conflictList.length}</strong></div>
            </div>
            {hardCount > 0 ? (
              <Notice tone="error" title="Publish is disabled because hard-constraint violations exist">
                <AlertTriangle size={14} aria-hidden="true" /> Resolve all {hardCount} hard violation(s) before publishing.
              </Notice>
            ) : (
              <Notice tone="success" title="Ready for publication">
                <CheckCircle2 size={14} aria-hidden="true" /> Zero hard-constraint violations detected. Publishing this version will archive any earlier published {selected.schedule_type.toLowerCase()} for {termLabel(selected.term_id)}.
              </Notice>
            )}
          </div>
        </Card>
      )}

      <Card title="Published and archived versions">
        <DataTable
          rows={history}
          rowKey={(row) => row.schedule_id}
          caption="Published and archived schedule versions"
          emptyText="No published or archived versions yet."
          searchText={(row) => `${row.schedule_type} v${row.version_no} ${row.status} ${termLabel(row.term_id)}`}
          columns={[
            { key: 'type', label: 'Schedule type', value: (row) => row.schedule_type, render: (row) => <strong>{row.schedule_type}</strong> },
            { key: 'version', label: 'Version', value: (row) => row.version_no, render: (row) => `Version ${row.version_no}` },
            { key: 'term', label: 'Term', value: (row) => termLabel(row.term_id) },
            { key: 'score', label: 'Soft score', value: (row) => row.objective_score ?? 0, render: (row) => <span className="tabular">{row.objective_score ?? '—'}</span> },
            { key: 'status', label: 'Status', value: (row) => row.status, render: (row) => <StatusBadge status={row.status} /> },
          ]}
        />
      </Card>
    </LoadState>

    {confirming && selected && (
      <ConfirmDialog
        title={`Publish ${selected.schedule_type.toLowerCase()} version ${selected.version_no}?`}
        confirmLabel="Publish"
        danger={false}
        busy={busy}
        onCancel={() => setConfirming(false)}
        onConfirm={() => void publish()}
        message={<p>Publish <strong>{selected.schedule_type} version {selected.version_no}</strong> for {termLabel(selected.term_id)}? Any currently published version of the same type becomes Archived, and published schedules are read-only.</p>}
      />
    )}
  </div>
}
