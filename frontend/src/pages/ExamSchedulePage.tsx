import { useMemo, useState } from 'react'
import { ArrowRightLeft, CalendarDays, CheckCircle2, Filter, Info, LockKeyhole, Search } from 'lucide-react'
import { Button, Card, ExportActions, LoadState, Notice, PageHeader, SelectField, StatusBadge } from '../components/ui'
import { Modal, ConfirmDialog } from '../components/Modal'
import { useAsync } from '../hooks/useAsync'
import { errorMessage, exportSchedule, getExamSchedule, getScheduleEditContext, undoSchedule, getSchedules, getTerms, moveExamEntry } from '../services/api'
import type { ExamScheduleRow, ExamSlot, MoveResult, Room } from '../types'
import type { Role } from '../components/AppShell'

const formatDate = (value: string) => { const [year, month, day] = value.split('-'); return `${day}/${month}/${year}` }
const batchLabel = (item: { program_code: string; batch_year: number; section: string }) => (item.batch_year ? `${item.program_code} ${item.batch_year} · ${item.section}` : item.program_code)

function MoveDialog({ row, slots, rooms, scheduleId, onClose, onMoved }: { row: ExamScheduleRow; slots: ExamSlot[]; rooms: Room[]; scheduleId: string; onClose: () => void; onMoved: () => void }) {
  const [slotId, setSlotId] = useState(row.examSlot.exam_slot_id)
  const [locked, setLocked] = useState(row.entry.is_locked)
  const [allocations, setAllocations] = useState(row.rooms.map(({ room, seats }) => ({ room_id: room.room_id, seats_allocated: seats })))
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Extract<MoveResult, { ok: false }> | null>(null)
  const [error, setError] = useState('')
  const total = allocations.reduce((sum, r) => sum + r.seats_allocated, 0)
  const signature = (list: typeof allocations) => JSON.stringify([...list].sort((a, b) => a.room_id.localeCompare(b.room_id)))
  const unchanged = slotId === row.examSlot.exam_slot_id && locked === row.entry.is_locked && signature(allocations) === signature(row.rooms.map(({ room, seats }) => ({ room_id: room.room_id, seats_allocated: seats })))
  const submit = async () => {
    setBusy(true); setFailure(null); setError('')
    try { const result = await moveExamEntry(scheduleId, row.entry.exam_entry_id, { exam_slot_id: slotId, is_locked: locked, room_allocations: allocations, expected_revision: row.entry.edit_revision ?? 0 }); if (result.ok) onMoved(); else setFailure(result) }
    catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }
  return <Modal title={`Adjust exam ${row.course.course_code}`} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy || unchanged || total !== row.entry.student_count || allocations.some((r) => !Number.isFinite(r.seats_allocated) || r.seats_allocated <= 0)}>{busy ? 'Checking…' : 'Save adjustment'}</Button></>}>
    <div className="stack-gap">
      <p className="subtle-note">All assignments are independently checked before saving. Unlock before moving or reassigning a locked exam.</p>
      {failure && <Notice tone="error" title="Adjustment rejected">{failure.message}</Notice>}
      {error && <Notice tone="error" title="Request failed">{error}</Notice>}
      <SelectField label="Exam session" id="move-exam-slot" value={slotId} onChange={setSlotId} options={slots.map((slot) => ({ value: slot.exam_slot_id, label: `${formatDate(slot.exam_date)} · ${slot.start_time}–${slot.end_time}` }))} />
      <label><input type="checkbox" checked={locked} onChange={(event) => setLocked(event.target.checked)} /> Lock this exam's session and exact room/seat allocations during regeneration</label>
      <fieldset><legend>Room allocations · {total} / {row.entry.student_count} seats</legend>
        {rooms.filter((room) => room.is_active && room.room_type !== 'Lab').map((room) => {
          const allocation = allocations.find((r) => r.room_id === room.room_id)
          return <div key={room.room_id} className="form-actions"><label><input type="checkbox" checked={Boolean(allocation)} onChange={(event) => setAllocations(event.target.checked ? [...allocations, { room_id: room.room_id, seats_allocated: Math.min(room.capacity, Math.max(1, row.entry.student_count - total)) }] : allocations.filter((r) => r.room_id !== room.room_id))} /> {room.room_code} · {room.capacity} capacity</label>
            {allocation && <input type="number" min={1} max={room.capacity} aria-label={`Seats in ${room.room_code}`} value={allocation.seats_allocated} onChange={(event) => setAllocations(allocations.map((r) => r.room_id === room.room_id ? { ...r, seats_allocated: Number(event.target.value) } : r))} />}</div>
        })}
      </fieldset>
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

  const base = useAsync(getSchedules, [])
  const terms = useAsync(getTerms, [])
  const [termId, setTermId] = useState('')
  const currentTerm = termId || terms.data?.find((t) => t.status === 'Active')?.term_id || (base.data ?? []).find((s) => s.schedule_type === 'Exam schedule')?.term_id || ''
  const versions = useMemo(() => (base.data ?? []).filter((item) => item.schedule_type === 'Exam schedule' && item.term_id === currentTerm && item.status !== 'Generating').sort((a, b) => b.version_no - a.version_no), [base.data, currentTerm])
  const selected = versions.find((item) => item.schedule_id === scheduleId) ?? versions.find((item) => item.status === 'Published') ?? versions[0]
  const view = useAsync(() => (selected ? Promise.all([getExamSchedule(selected.schedule_id), getScheduleEditContext(selected.schedule_id)]) : Promise.resolve([[], { revision: 0, rooms: [], slots: [], examSlots: [] }] as [ExamScheduleRow[], import('../services/api').EditContext])), [selected?.schedule_id])
  const rows = view.data?.[0] ?? []
  const slots = view.data?.[1]?.examSlots ?? []
  const availableRooms = view.data?.[1]?.rooms ?? []
  const batches = [...new Map(rows.flatMap((row) => row.batches.map((batch) => [batch.batch_id, batch] as const))).values()]
  const courses = [...new Map(rows.map((row) => [row.course.course_id, row.course])).values()]
  const rooms = [...new Map(rows.flatMap((row) => row.rooms.map(({ room }) => [room.room_id, room] as const))).values()]
  const dates = [...new Set(rows.map((item) => item.examSlot.exam_date))].sort()
  const filteredRows = useMemo(() => rows.filter((item) => (date === 'all' || item.examSlot.exam_date === date) && (batch === 'all' || item.batches.some((entry) => entry.batch_id === batch)) && (course === 'all' || item.course.course_id === course) && (room === 'all' || item.rooms.some((entry) => entry.room.room_id === room))), [rows, date, batch, course, room])
  const canMove = role === 'Coordinator' && selected?.status === 'Generated'
  const [undoConfirm, setUndoConfirm] = useState(false)
  const [undoBusy, setUndoBusy] = useState(false)
  const [editError, setEditError] = useState('')
  const undoAll = async () => {
    if (!selected) return
    setUndoBusy(true); setEditError('')
    try { await undoSchedule(selected.schedule_id, rows[0]?.entry.edit_revision ?? view.data?.[1]?.revision ?? 0); view.reload(); setUndoConfirm(false); onStatus('The server restored the captured exam baseline, rooms and locks.') }
    catch (reason) { setEditError(errorMessage(reason)) }
    finally { setUndoBusy(false) }
  }
  const seatShort = rows.filter((item) => item.rooms.reduce((sum, entry) => sum + entry.seats, 0) < item.entry.student_count).length

  return <div className="page-stack">
    <PageHeader eyebrow="Exams / View" title="Exam schedule view" description={selected ? `Version ${selected.version_no} · ${selected.status} · Ordered by date and session` : 'No exam schedule has been generated yet'} actions={<ExportActions onStatus={onStatus} disabled={!selected} allowGrouped={role === 'Coordinator'} onExport={(format, group) => selected ? exportSchedule(selected.schedule_id, format, { batch_id: batch === 'all' ? undefined : batch, room_id: room === 'all' ? undefined : room, course_id: course === 'all' ? undefined : course, exam_date: date === 'all' ? undefined : date }, group) : Promise.resolve()} />} />
    {canMove && <div className="form-actions"><Button variant="secondary" onClick={() => setUndoConfirm(true)}>Undo all tracked manual edits</Button></div>}
    {editError && <Notice tone="error" title="Undo failed">{editError}</Notice>}
    {undoConfirm && selected && <ConfirmDialog title={`Restore exam version ${selected.version_no} baseline?`} confirmLabel="Restore baseline" danger={false} busy={undoBusy} onCancel={() => setUndoConfirm(false)} onConfirm={() => void undoAll()} message={<p>Restore all exams, room/seat allocations and locks to the captured baseline? Revision history is retained.</p>} />}
    <LoadState loading={base.loading || terms.loading || view.loading} error={base.error || terms.error || view.error} onRetry={() => { base.reload(); terms.reload(); view.reload() }}>
      {!selected ? <Notice title="No exam schedule yet">{role === 'Coordinator' ? 'Generate a new version from the Generate screen.' : 'No schedule is available in your permitted scope. Contact the Coordinator.'}</Notice> : <>
        <Card className="filter-card no-print"><div className="filter-card-heading"><div><span className="eyebrow"><CalendarDays size={14} /> Planning view</span><h2>Filter exam schedule</h2></div>
          <div className="view-version"><SelectField label="Term" id="view-term" value={currentTerm} onChange={(value) => { setTermId(value); setScheduleId(''); setDate('all'); setBatch('all'); setCourse('all'); setRoom('all') }} options={(terms.data ?? []).map((t) => ({ value: t.term_id, label: t.label }))} /><label htmlFor="exam-version">Version</label><select id="exam-version" value={selected.schedule_id} onChange={(event) => setScheduleId(event.target.value)}>{versions.map((item) => <option key={item.schedule_id} value={item.schedule_id}>Version {item.version_no} · {item.status}</option>)}</select></div></div>
          <div className="filter-grid exam-filter-grid">
            <SelectField label="Date" value={date} onChange={setDate} options={[{ value: 'all', label: 'All dates' }, ...dates.map((item) => ({ value: item, label: formatDate(item) }))]} id="date-filter" />
            <SelectField label="Batch" value={batch} onChange={setBatch} options={[{ value: 'all', label: role === 'Student' ? 'My batch' : 'All permitted batches' }, ...batches.map((item) => ({ value: item.batch_id, label: batchLabel(item) }))]} id="exam-batch-filter" />
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
            <td>{item.entry.is_locked ? <span className="inline-status"><LockKeyhole size={14} aria-hidden="true" /> Locked</span> : <span className="inline-status success"><CheckCircle2 size={14} aria-hidden="true" /> Allocated</span>}{item.entry.is_manual_override && <small>Manual override</small>}</td>
            {canMove && <td className="no-print"><Button variant="secondary" icon={ArrowRightLeft} onClick={() => setMoving(item)} ariaLabel={`Move exam ${item.course.course_code}`}>Adjust / lock</Button></td>}
          </tr>)}</tbody></table>
          {filteredRows.length === 0 && <div className="empty-state"><Search size={20} /><strong>No sessions match these filters</strong><span>Clear one or more filters to see more results.</span></div>}</div>
          <div className="table-footnote">{seatShort === 0 ? <><CheckCircle2 size={14} /> All listed rooms have enough seats for their allocated candidates.</> : <><Info size={14} /> {seatShort} exam{seatShort === 1 ? ' has' : 's have'} fewer allocated seats than students. See the conflict report.</>}</div></Card>
      </>}
    </LoadState>
    {moving && selected && <MoveDialog row={moving} slots={slots} rooms={availableRooms} scheduleId={selected.schedule_id} onClose={() => setMoving(null)} onMoved={() => { setMoving(null); onStatus(`${moving.course.course_code} exam moved. All hard constraints re-validated.`); view.reload() }} />}
  </div>
}
