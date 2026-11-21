import { useMemo, useState } from 'react'
import { ArrowRightLeft, CalendarDays, CheckCircle2, Filter, Info, LockKeyhole, Search } from 'lucide-react'
import { Button, Card, ExportActions, LoadState, Notice, PageHeader, SelectField, StatusBadge } from '../components/ui'
import { Modal } from '../components/Modal'
import { useAsync } from '../hooks/useAsync'
import { errorMessage, getBatches, getCourses, getExamSchedule, getExamSlots, getRooms, getSchedules, moveExamEntry } from '../services/api'
import type { ExamScheduleRow, ExamSlot, MoveResult } from '../types'
import type { Role } from '../components/AppShell'

const formatDate = (value: string) => { const [year, month, day] = value.split('-'); return `${day}/${month}/${year}` }
const batchLabel = (item: { program_code: string; batch_year: number; section: string }) => (item.batch_year ? `${item.program_code} ${item.batch_year} · ${item.section}` : item.program_code)

function MoveDialog({ row, slots, scheduleId, onClose, onMoved }: { row: ExamScheduleRow; slots: ExamSlot[]; scheduleId: string; onClose: () => void; onMoved: () => void }) {
  const [slotId, setSlotId] = useState(row.examSlot.exam_slot_id)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Extract<MoveResult, { ok: false }> | null>(null)
  const [error, setError] = useState('')
  const submit = async () => {
    setBusy(true); setFailure(null); setError('')
    try { const result = await moveExamEntry(scheduleId, row.entry.exam_entry_id, { exam_slot_id: slotId }); if (result.ok) onMoved(); else setFailure(result) }
    catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }
  return <Modal title={`Move exam ${row.course.course_code}`} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy || slotId === row.examSlot.exam_slot_id}>{busy ? 'Checking…' : 'Move exam'}</Button></>}>
    <div className="stack-gap">
      <p className="subtle-note"><Info size={15} aria-hidden="true" />The server re-validates every enabled hard constraint before it saves the move. Room allocations stay as they are.</p>
      {failure && <Notice tone="error" title={failure.rule_code ? `Move rejected: ${failure.violated_constraints.join(', ') || failure.rule_code} violated` : 'Move rejected'}>{failure.message}</Notice>}
      {error && <Notice tone="error" title="The move could not be sent">{error}</Notice>}
      <SelectField label="Exam session" id="move-exam-slot" value={slotId} onChange={setSlotId} options={slots.map((slot) => ({ value: slot.exam_slot_id, label: `${formatDate(slot.exam_date)} · ${slot.start_time}–${slot.end_time}${slot.label ? ` · ${slot.label}` : ''}` }))} />
    </div>
  </Modal>
}

export function ExamSchedulePage({ onStatus, role }: { onStatus: (message: string) => void; role: Role }) {
  const [date, setDate] = useState('all')
  const [batch, setBatch] = useState('all')
  const [course, setCourse] = useState('all')
  const [room, setRoom] = useState('all')
  const [scheduleId, setScheduleId] = useState('')
  const [moving, setMoving] = useState<ExamScheduleRow | null>(null)

  const base = useAsync(() => Promise.all([getBatches(), getCourses(), getRooms(), getSchedules()]), [])
  const versions = useMemo(() => (base.data?.[3] ?? []).filter((item) => item.schedule_type === 'Exam schedule' && item.status !== 'Generating').sort((a, b) => b.version_no - a.version_no), [base.data])
  const selected = versions.find((item) => item.schedule_id === scheduleId) ?? versions.find((item) => item.status === 'Published') ?? versions[0]
  const view = useAsync(() => (selected ? Promise.all([getExamSchedule(selected.schedule_id), getExamSlots(selected.term_id)]) : Promise.resolve([[], []] as [ExamScheduleRow[], ExamSlot[]])), [selected?.schedule_id])
  const [batches, courses, rooms] = base.data ?? [[], [], []]
  const rows = view.data?.[0] ?? []
  const slots = view.data?.[1] ?? []
  const dates = [...new Set(rows.map((item) => item.examSlot.exam_date))].sort()
  const filteredRows = useMemo(() => rows.filter((item) => (date === 'all' || item.examSlot.exam_date === date) && (batch === 'all' || item.batches.some((entry) => entry.batch_id === batch)) && (course === 'all' || item.course.course_id === course) && (room === 'all' || item.rooms.some((entry) => entry.room.room_id === room))), [rows, date, batch, course, room])
  const canMove = (role === 'Administrator' || role === 'Coordinator') && (selected?.status === 'Generated' || selected?.status === 'Draft')
  const seatShort = rows.filter((item) => item.rooms.reduce((sum, entry) => sum + entry.seats, 0) < item.entry.student_count).length

  return <div className="page-stack">
    <PageHeader eyebrow="Exams / View" title="Exam schedule view" description={selected ? `Version ${selected.version_no} · ${selected.status} · Ordered by date and session` : 'No exam schedule has been generated yet'} actions={<ExportActions onStatus={onStatus} />} />
    <LoadState loading={base.loading || view.loading} error={base.error || view.error} onRetry={() => { base.reload(); view.reload() }}>
      {!selected ? <Notice title="No exam schedule yet">Generate an exam schedule from the Generate screen to see it here.</Notice> : <>
        <Card className="filter-card no-print"><div className="filter-card-heading"><div><span className="eyebrow"><CalendarDays size={14} /> Planning view</span><h2>Filter exam schedule</h2></div>
          <div className="view-version"><label htmlFor="exam-version">Version</label><select id="exam-version" value={selected.schedule_id} onChange={(event) => setScheduleId(event.target.value)}>{versions.map((item) => <option key={item.schedule_id} value={item.schedule_id}>Version {item.version_no} · {item.status}</option>)}</select></div></div>
          <div className="filter-grid exam-filter-grid">
            <SelectField label="Date" value={date} onChange={setDate} options={[{ value: 'all', label: 'All dates' }, ...dates.map((item) => ({ value: item, label: formatDate(item) }))]} id="date-filter" />
            <SelectField label="Batch" value={batch} onChange={setBatch} options={[{ value: 'all', label: 'All batches' }, ...batches.map((item) => ({ value: item.batch_id, label: batchLabel(item) }))]} id="exam-batch-filter" />
            <SelectField label="Course" value={course} onChange={setCourse} options={[{ value: 'all', label: 'All courses' }, ...courses.map((item) => ({ value: item.course_id, label: `${item.course_code} · ${item.title}` }))]} id="exam-course-filter" />
            <SelectField label="Room" value={room} onChange={setRoom} options={[{ value: 'all', label: 'All rooms' }, ...rooms.filter((item) => item.room_type === 'Exam Hall').map((item) => ({ value: item.room_id, label: item.room_code }))]} id="exam-room-filter" />
          </div>
          <div className="filter-summary"><span><Filter size={14} /> {filteredRows.length} exam sessions shown</span><button type="button" onClick={() => { setDate('all'); setBatch('all'); setCourse('all'); setRoom('all') }}>Clear filters</button></div></Card>
        <Card title="Exam sessions" actions={<StatusBadge status={selected.status} />}><div className="table-wrap"><table className="data-table"><caption className="sr-only">Exam sessions ordered by date and time</caption>
          <thead><tr><th scope="col">Date</th><th scope="col">Session</th><th scope="col">Course</th><th scope="col">Batch</th><th scope="col">Rooms</th><th scope="col">Seats</th><th scope="col">Status</th>{canMove && <th scope="col" className="no-print">Actions</th>}</tr></thead>
          <tbody>{filteredRows.map((item) => <tr key={item.entry.exam_entry_id}>
            <td className="tabular"><strong>{formatDate(item.examSlot.exam_date)}</strong><small>{item.examSlot.start_time}–{item.examSlot.end_time}</small></td><td>{item.examSlot.label || '—'}</td>
            <td><strong>{item.course.course_code}</strong><small>{item.course.title}</small></td>
            <td>{item.batches.length ? item.batches.map((entry) => <span key={entry.batch_id}>{entry.program_code}<small>{entry.batch_year} · Section {entry.section}</small></span>) : <span>Not linked<small>No offering for this course</small></span>}</td>
            <td><div className="room-list">{item.rooms.map((entry) => <span key={entry.room.room_id}>{entry.room.room_code} <small>{entry.seats} seats</small></span>)}</div></td><td className="tabular"><strong>{item.entry.student_count}</strong></td>
            <td>{item.entry.is_locked ? <span className="inline-status"><LockKeyhole size={14} aria-hidden="true" /> Locked</span> : <span className="inline-status success"><CheckCircle2 size={14} aria-hidden="true" /> Allocated</span>}</td>
            {canMove && <td className="no-print"><Button variant="secondary" icon={ArrowRightLeft} onClick={() => setMoving(item)} ariaLabel={`Move exam ${item.course.course_code}`}>Move</Button></td>}
          </tr>)}</tbody></table>
          {filteredRows.length === 0 && <div className="empty-state"><Search size={20} /><strong>No sessions match these filters</strong><span>Clear one or more filters to see more results.</span></div>}</div>
          <div className="table-footnote">{seatShort === 0 ? <><CheckCircle2 size={14} /> All listed rooms have enough seats for their allocated candidates.</> : <><Info size={14} /> {seatShort} exam{seatShort === 1 ? ' has' : 's have'} fewer allocated seats than students. See the conflict report.</>}</div></Card>
      </>}
    </LoadState>
    {moving && selected && <MoveDialog row={moving} slots={slots} scheduleId={selected.schedule_id} onClose={() => setMoving(null)} onMoved={() => { setMoving(null); onStatus(`${moving.course.course_code} exam moved. All hard constraints re-validated.`); view.reload() }} />}
  </div>
}
