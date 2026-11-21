import { useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Download, Search, TriangleAlert } from 'lucide-react'
import { Button, Card, LoadState, Notice, PageHeader, SelectField } from '../components/ui'
import { DataTable } from '../components/Modal'
import { useAsync } from '../hooks/useAsync'
import { getConflicts, getSchedules } from '../services/api'
import type { ConflictItem } from '../types'

const csvCell = (value: string) => `"${value.replace(/"/g, '""')}"`

export function ConflictReportPage({ onStatus }: { onStatus: (message: string) => void }) {
  const [scheduleId, setScheduleId] = useState('')
  const [type, setType] = useState('all')
  const [severity, setSeverity] = useState('all')
  const schedules = useAsync(getSchedules, [])
  const list = useMemo(() => [...(schedules.data ?? [])].filter((item) => item.status !== 'Generating').sort((a, b) => b.schedule_id.localeCompare(a.schedule_id, undefined, { numeric: true })), [schedules.data])
  const selected = list.find((item) => item.schedule_id === scheduleId) ?? list.find((item) => item.status === 'Generated') ?? list[0]
  const conflicts = useAsync(() => (selected ? getConflicts(selected.schedule_id) : Promise.resolve([] as ConflictItem[])), [selected?.schedule_id])
  const rows = conflicts.data ?? []
  const types = [...new Set(rows.map((item) => item.conflict_type))].sort()
  const filtered = rows.filter((item) => (type === 'all' || item.conflict_type === type) && (severity === 'all' || item.severity === severity))
  const hard = rows.filter((item) => item.severity === 'Hard').length

  const exportCsv = () => {
    const header = ['type', 'severity', 'affected', 'description', 'detected_at', 'resolved']
    const body = filtered.map((item) => [item.conflict_type, item.severity, item.entity_ref ?? '', item.description, item.detected_at, item.is_resolved ? 'yes' : 'no'].map(csvCell).join(','))
    const url = URL.createObjectURL(new Blob([[header.join(','), ...body].join('\r\n')], { type: 'text/csv;charset=utf-8' }))
    const link = Object.assign(document.createElement('a'), { href: url, download: `conflicts-${selected?.schedule_type.toLowerCase().replace(' ', '-')}-v${selected?.version_no}.csv` })
    link.click()
    URL.revokeObjectURL(url)
    onStatus(`Exported ${filtered.length} conflict record(s) to CSV.`)
  }

  return <div className="page-stack">
    <PageHeader eyebrow="Conflict report" title="Conflict report" description="Hard violations block publication. Warnings show where soft preferences were not met." actions={<Button variant="secondary" icon={Download} onClick={exportCsv} disabled={!filtered.length}>Export CSV</Button>} />
    <LoadState loading={schedules.loading || conflicts.loading} error={schedules.error || conflicts.error} onRetry={() => { schedules.reload(); conflicts.reload() }}>
      {!selected ? <Notice title="No schedule versions yet">Generate a timetable or exam schedule to see its conflicts here.</Notice> : <>
        <Card className="filter-card no-print"><div className="filter-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))' }}>
          <SelectField label="Schedule version" id="conflict-version" value={selected.schedule_id} onChange={(value) => { setScheduleId(value); setType('all'); setSeverity('all') }} options={list.map((item) => ({ value: item.schedule_id, label: `${item.schedule_type} v${item.version_no} · ${item.status}` }))} />
          <SelectField label="Conflict type" id="conflict-type" value={type} onChange={setType} options={[{ value: 'all', label: 'All types' }, ...types.map((item) => ({ value: item, label: item }))]} />
          <SelectField label="Severity" id="conflict-severity" value={severity} onChange={setSeverity} options={[{ value: 'all', label: 'All severities' }, { value: 'Hard', label: 'Hard' }, { value: 'Warning', label: 'Warning' }]} />
        </div></Card>
        {hard > 0 ? <Notice tone="error" title={`${hard} hard violation${hard === 1 ? '' : 's'} in this version`}>This version cannot be published until they are resolved or a new version is generated.</Notice>
          : <Notice tone="success" title="No hard violations in this version">{rows.length ? `${rows.length} warning${rows.length === 1 ? '' : 's'} recorded.` : 'No conflicts of any kind were recorded.'}</Notice>}
        <Card title="Conflicts"><DataTable rows={filtered} rowKey={(row) => row.conflict_id} caption="Conflicts of the selected schedule version" emptyText="No conflicts match this filter." searchText={(row) => `${row.conflict_type} ${row.severity} ${row.description} ${row.entity_ref ?? ''}`}
          columns={[
            { key: 'type', label: 'Type', value: (row) => row.conflict_type, render: (row) => <strong>{row.conflict_type}</strong> },
            { key: 'severity', label: 'Severity', value: (row) => row.severity, render: (row) => row.severity === 'Hard' ? <span className="status-badge status-danger"><AlertTriangle size={14} aria-hidden="true" /><span>Hard</span></span> : <span className="status-badge status-warning"><TriangleAlert size={14} aria-hidden="true" /><span>Warning</span></span> },
            { key: 'entity', label: 'Affected', value: (row) => row.entity_ref ?? '' },
            { key: 'description', label: 'Description', value: (row) => row.description },
            { key: 'state', label: 'State', value: (row) => (row.is_resolved ? 'Resolved' : 'Open'), render: (row) => row.is_resolved ? <span className="inline-status success"><CheckCircle2 size={14} aria-hidden="true" /> Resolved</span> : <span className="inline-status"><Search size={14} aria-hidden="true" /> Open</span> },
          ]} /></Card>
      </>}
    </LoadState>
  </div>
}
