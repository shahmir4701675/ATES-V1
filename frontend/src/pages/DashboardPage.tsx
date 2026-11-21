import { ArrowRight, BookOpen, Building2, CalendarCheck2, CalendarRange, CheckCircle2, AlertTriangle, ClipboardList, GraduationCap, MapPin, Network, UsersRound } from 'lucide-react'
import { Button, Card, LoadState, Notice, PageHeader, StatCard, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { getDashboardSummary } from '../services/api'
import type { Schedule } from '../types'

function SchedulePanel({ title, schedule, emptyText, path, onNavigate }: { title: string; schedule: Schedule | null; emptyText: string; path: string; onNavigate: (path: string) => void }) {
  const description = !schedule ? emptyText
    : schedule.status === 'Published' ? 'Approved for departmental circulation.'
      : schedule.status === 'Generated' ? 'Generated and waiting for review and publication.'
        : schedule.status === 'Infeasible' ? 'The solver found no feasible result. Review the conflict report.' : `Current state: ${schedule.status.toLowerCase()}.`
  return <Card title={title} actions={<Button variant="ghost" onClick={() => onNavigate(path)}>Open view <ArrowRight size={14} /></Button>}>
    {schedule ? <>
      <div className="status-panel"><div><StatusBadge status={schedule.status} /><h3>Version {schedule.version_no} is {schedule.status.toLowerCase()}</h3><p>{description}</p></div><div className="status-panel-score"><span>Soft score</span><strong className="tabular">{schedule.objective_score ?? '—'}</strong></div></div>
      <div className="status-detail-row"><span>Solver status</span><strong><StatusBadge status={schedule.solver_status} /></strong><span>Run time</span><strong className="tabular">{schedule.run_seconds ?? '—'}{schedule.run_seconds !== null ? 's' : ''}</strong></div>
    </> : <div className="status-panel"><div><StatusBadge status="Draft" label="Not generated" /><h3>No version yet</h3><p>{description}</p></div></div>}
  </Card>
}

export function DashboardPage({ onNavigate, onStatus }: { onNavigate: (path: string) => void; onStatus: (message: string) => void }) {
  const { data: summary, loading, error, reload } = useAsync(getDashboardSummary, [])
  return <div className="page-stack">
    <PageHeader eyebrow="Dashboard" title="Department scheduling" description={summary ? (summary.activeTerm ? `Active term: ${summary.activeTerm.label}. Review schedule health and move to the next administrative action.` : 'No term is marked Active. Mark one in Data management › Terms and slots.') : 'Loading the current term…'} actions={<Button icon={ArrowRight} onClick={() => onNavigate('/generate')}>Generate schedule</Button>} />
    <LoadState loading={loading} error={error} onRetry={reload}>{summary && <>
      {summary.conflicts.hard > 0
        ? <Notice tone="error" title={`${summary.conflicts.hard} hard-constraint violation${summary.conflicts.hard === 1 ? '' : 's'} in the current schedules`} action={<button type="button" onClick={() => onNavigate('/conflicts')}>Open conflict report</button>}>Resolve these before a version can be published.</Notice>
        : <div className="notice notice-info"><CheckCircle2 size={18} aria-hidden="true" /><div><strong>No hard-constraint violations</strong><p>{summary.conflicts.warning} warning{summary.conflicts.warning === 1 ? '' : 's'} recorded for the current timetable and exam schedule.</p></div><button type="button" onClick={() => { onStatus('Opening the conflict report.'); onNavigate('/conflicts') }}>View conflict report</button></div>}
      <section className="section-grid two-columns">
        <SchedulePanel title="Timetable status" schedule={summary.timetable} emptyText="Generate a timetable to see its status here." path="/timetable" onNavigate={onNavigate} />
        <SchedulePanel title="Exam schedule status" schedule={summary.examSchedule} emptyText="Generate an exam schedule to see its status here." path="/exams" onNavigate={onNavigate} />
      </section>
      <section><div className="section-heading"><div><span className="eyebrow">Academic inventory</span><h2>Current term overview</h2></div><span className="muted">Updated {new Date().toLocaleDateString('en-GB')}</span></div><div className="metrics-grid">
        <StatCard label="Active courses" value={summary.counts.courses} detail={`Across ${summary.counts.departments} departments`} icon={BookOpen} />
        <StatCard label="Instructors" value={summary.counts.instructors} detail="Active records" icon={UsersRound} />
        <StatCard label="Rooms" value={summary.counts.rooms} detail="Lecture, lab and exam" icon={Building2} />
        <StatCard label="Batches" value={summary.counts.batches} detail="Active sections" icon={GraduationCap} />
        <StatCard label="Offerings" value={summary.counts.offerings} detail="Term-course assignments" icon={ClipboardList} />
      </div></section>
      <section className="section-grid two-columns">
        <Card title="Next actions"><div className="action-list">
          <button type="button" onClick={() => onNavigate('/generate')}><span className="action-icon"><Network size={17} /></span><span><strong>Generate a new schedule</strong><small>Run the solver with current term constraints.</small></span><ArrowRight size={16} /></button>
          <button type="button" onClick={() => onNavigate('/timetable')}><span className="action-icon"><CalendarRange size={17} /></span><span><strong>Review timetable exceptions</strong><small>Check locked and manually overridden entries.</small></span><ArrowRight size={16} /></button>
          <button type="button" onClick={() => onNavigate('/exams')}><span className="action-icon"><CalendarCheck2 size={17} /></span><span><strong>Review exam room allocation</strong><small>Confirm seat assignments before approval.</small></span><ArrowRight size={16} /></button>
          <button type="button" onClick={() => onNavigate('/conflicts')}><span className="action-icon"><AlertTriangle size={17} /></span><span><strong>Open the conflict report</strong><small>See hard violations and warnings by type.</small></span><ArrowRight size={16} /></button>
        </div></Card>
        <Card title="Recent activity"><div className="activity-list">
          {summary.activity.length === 0 && <span className="muted">No schedule activity yet.</span>}
          {summary.activity.map((item) => <div key={item.id}><span className={`activity-dot ${item.tone === 'neutral' ? '' : item.tone}`} /><span><strong>{item.title}</strong><small>{item.detail}</small></span></div>)}
        </div></Card>
      </section>
      <div className="page-footnote"><MapPin size={14} /> Department of Computer and Electrical Engineering · Academic operations workspace</div>
    </>}</LoadState>
  </div>
}
