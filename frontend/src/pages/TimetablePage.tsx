import { useMemo, useState } from 'react'
import { ArrowRightLeft, CheckCircle2, Filter, Info, LockKeyhole, PencilLine, SlidersHorizontal } from 'lucide-react'
import { Button, Card, ExportActions, LoadState, Notice, PageHeader, SelectField, StatusBadge } from '../components/ui'
import { Modal } from '../components/Modal'
import { useAsync } from '../hooks/useAsync'
import { DAY_NAMES } from '../data/reference'
import { errorMessage, getBatches, getCourses, getInstructors, getRooms, getSchedules, getTimeSlots, getTimetable, moveTimetableEntry } from '../services/api'
import type { MoveResult, Room, TimeSlot, TimetableRow } from '../types'
import type { Role } from '../components/AppShell'

type Failure = Extract<MoveResult, { ok: false }>

function MoveDialog({ row, slots, rooms, scheduleId, onClose, onMoved }: { row: TimetableRow; slots: TimeSlot[]; rooms: Room[]; scheduleId: string; onClose: () => void; onMoved: () => void }) {
  const [slotId, setSlotId] = useState(row.startSlot.slot_id)
  const [roomId, setRoomId] = useState(row.room.room_id)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [error, setError] = useState('')
  const free = slots.filter((slot) => !slot.is_blocked || slot.slot_id === row.startSlot.slot_id)
  const unchanged = slotId === row.startSlot.slot_id && roomId === row.room.room_id
  const submit = async () => {
    setBusy(true); setFailure(null); setError('')
    try {
      const result = await moveTimetableEntry(scheduleId, row.entry.entry_id, { slot_id: slotId === row.startSlot.slot_id ? undefined : slotId, room_id: roomId === row.room.room_id ? undefined : roomId })
      if (result.ok) onMoved(); else setFailure(result)
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }
  return <Modal title={`Move ${row.course.course_code} ${row.entry.session_type.toLowerCase()}`} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy || unchanged}>{busy ? 'Checking…' : 'Move session'}</Button></>}>
    <div className="stack-gap">
      <p className="subtle-note"><Info size={15} aria-hidden="true" />The server re-validates every enabled hard constraint before it saves a move. Current placement: {row.day} {row.startSlot.start_time}–{row.startSlot.end_time}, {row.room.room_code}.</p>
      {failure && <Notice tone="error" title={failure.rule_code ? `Move rejected: ${failure.violated_constraints.join(', ') || failure.rule_code} violated` : 'Move rejected'}>{failure.message}</Notice>}
      {error && <Notice tone="error" title="The move could not be sent">{error}</Notice>}
      <SelectField label="Day and time" id="move-slot" value={slotId} onChange={setSlotId} options={free.map((slot) => ({ value: slot.slot_id, label: `${slot.day_of_week} · ${slot.start_time}–${slot.end_time}` }))} hint="Blocked slots are not offered." />
      <SelectField label="Room" id="move-room" value={roomId} onChange={setRoomId} options={rooms.filter((room) => room.is_active || room.room_id === row.room.room_id).map((room) => ({ value: room.room_id, label: `${room.room_code} · ${room.room_type} · ${room.capacity} seats` }))} />
    </div>
  </Modal>
}

export function TimetablePage({ onStatus, role }: { onStatus: (message: string) => void; role: Role }) {
  const [batch, setBatch] = useState('all')
  const [instructor, setInstructor] = useState('all')
  const [room, setRoom] = useState('all')
  const [course, setCourse] = useState('all')
  const [day, setDay] = useState('all')
  const [scheduleId, setScheduleId] = useState('')
  const [moving, setMoving] = useState<TimetableRow | null>(null)

  const base = useAsync(() => Promise.all([getBatches(), getInstructors(), getRooms(), getCourses(), getSchedules()]), [])
  const versions = useMemo(() => (base.data?.[4] ?? []).filter((item) => item.schedule_type === 'Timetable' && item.status !== 'Generating').sort((a, b) => b.version_no - a.version_no), [base.data])
  const selectedVersion = versions.find((item) => item.schedule_id === scheduleId) ?? versions.find((item) => item.status === 'Published') ?? versions[0]
  const view = useAsync(() => (selectedVersion ? Promise.all([getTimetable(selectedVersion.schedule_id, selectedVersion.term_id), getTimeSlots(selectedVersion.term_id)]) : Promise.resolve([[], []] as [TimetableRow[], TimeSlot[]])), [selectedVersion?.schedule_id])
  const [batches, instructors, rooms, courses] = base.data ?? [[], [], [], [], []]
  const rows = view.data?.[0] ?? []
  const slots = view.data?.[1] ?? []
  const days = useMemo(() => DAY_NAMES.filter((name) => slots.some((slot) => slot.day_of_week === name)), [slots])
  const hours = useMemo(() => [...new Map(slots.map((slot) => [slot.slot_index, slot])).values()].sort((a, b) => a.slot_index - b.slot_index), [slots])
  const rowOf = (slotIndex: number) => hours.findIndex((hour) => hour.slot_index === slotIndex) + 2
  const filteredRows = useMemo(() => rows.filter((item) => (batch === 'all' || item.batch.batch_id === batch) && (instructor === 'all' || item.instructor.instructor_id === instructor) && (room === 'all' || item.room.room_id === room) && (course === 'all' || item.course.course_id === course) && (day === 'all' || item.day === day)), [rows, batch, instructor, room, course, day])
  const canMove = (role === 'Administrator' || role === 'Coordinator') && (selectedVersion?.status === 'Generated' || selectedVersion?.status === 'Draft')

  const labelFor = (value: string, allLabel: string, items: Array<{ value: string; label: string }>) => value === 'all' ? allLabel : items.find((item) => item.value === value)?.label ?? value
  const batchLabel = (item: { program_code: string; batch_year: number; section: string }) => `${item.program_code} ${item.batch_year} · ${item.section}`
  const filterText = [
    `Batch: ${labelFor(batch, 'All', batches.map((item) => ({ value: item.batch_id, label: batchLabel(item) })))}`,
    `Instructor: ${labelFor(instructor, 'All', instructors.map((item) => ({ value: item.instructor_id, label: item.full_name })))}`,
    `Room: ${labelFor(room, 'All', rooms.map((item) => ({ value: item.room_id, label: item.room_code })))}`,
    `Course: ${labelFor(course, 'All', courses.map((item) => ({ value: item.course_id, label: item.course_code })))}`,
    `Day: ${day === 'all' ? 'All' : day}`,
  ].join('  ·  ')

  return <div className="page-stack">
    <PageHeader eyebrow="Timetable / View" title="Timetable view" description={`${selectedVersion ? `Version ${selectedVersion.version_no} · ${selectedVersion.status}` : 'No version selected'}${canMove ? ' · Use Move on a session to adjust it; every move is re-validated.' : ''}`} actions={<ExportActions onStatus={onStatus} />} />
    <LoadState loading={base.loading || view.loading} error={base.error || view.error} onRetry={() => { base.reload(); view.reload() }}>
      {!selectedVersion ? <Notice title="No timetable has been generated yet">Generate a timetable from the Generate screen to see it here.</Notice> : <>
        <Card className="filter-card no-print"><div className="filter-card-heading"><div><span className="eyebrow"><SlidersHorizontal size={14} /> Weekly timetable</span><h2>Filter timetable</h2></div>
          <div className="view-version"><label htmlFor="version-select">Version</label><select id="version-select" value={selectedVersion.schedule_id} onChange={(event) => setScheduleId(event.target.value)}>{versions.map((item) => <option key={item.schedule_id} value={item.schedule_id}>Version {item.version_no} · {item.status}</option>)}</select></div></div>
          <div className="filter-grid">
            <SelectField label="Batch" value={batch} onChange={setBatch} options={[{ value: 'all', label: 'All batches' }, ...batches.map((item) => ({ value: item.batch_id, label: batchLabel(item) }))]} id="batch-filter" />
            <SelectField label="Instructor" value={instructor} onChange={setInstructor} options={[{ value: 'all', label: 'All instructors' }, ...instructors.map((item) => ({ value: item.instructor_id, label: item.full_name }))]} id="instructor-filter" />
            <SelectField label="Room" value={room} onChange={setRoom} options={[{ value: 'all', label: 'All rooms' }, ...rooms.map((item) => ({ value: item.room_id, label: item.room_code }))]} id="room-filter" />
            <SelectField label="Course" value={course} onChange={setCourse} options={[{ value: 'all', label: 'All courses' }, ...courses.map((item) => ({ value: item.course_id, label: `${item.course_code} · ${item.title}` }))]} id="course-filter" />
            <SelectField label="Day" value={day} onChange={setDay} options={[{ value: 'all', label: 'All days' }, ...days.map((item) => ({ value: item, label: item }))]} id="day-filter" />
          </div>
          <div className="filter-summary"><span><Filter size={14} /> {filteredRows.length} sessions shown</span><button type="button" onClick={() => { setBatch('all'); setInstructor('all'); setRoom('all'); setCourse('all'); setDay('all') }}>Clear filters</button></div></Card>
        <div className="print-only print-header"><strong>ATES · Timetable view</strong><span>Version {selectedVersion.version_no} · {selectedVersion.status}</span><span>{filterText}</span></div>
        <div className="legend-row"><div className="legend"><span className="legend-label">Legend</span><span><i className="legend-swatch lecture" />Lecture</span><span><i className="legend-swatch lab" />Lab</span><span><i className="legend-swatch blocked" />Break</span><span><LockKeyhole size={14} />Locked</span><span><PencilLine size={14} />Manual override</span></div><div className="legend-note"><CheckCircle2 size={14} /> Version {selectedVersion.version_no} · <StatusBadge status={selectedVersion.status} /></div></div>
        {selectedVersion.status === 'Published' && role !== 'Student' && <Notice title="This version is published and read-only">Generate a new version to make changes.</Notice>}
        <Card className="timetable-card"><div className="timetable-scroll"><div className="timetable-grid" style={{ gridTemplateColumns: `82px repeat(${days.length}, minmax(145px, 1fr))`, gridTemplateRows: `40px repeat(${hours.length}, minmax(78px, auto))` }}>
          <div className="grid-corner">Time</div>
          {days.map((item) => <div className="day-header" key={item}>{item}<span>{item.slice(0, 3).toUpperCase()}</span></div>)}
          {hours.map((hour, index) => <div className="time-cell tabular" style={{ gridColumn: 1, gridRow: index + 2 }} key={`time-${hour.slot_index}`}>{hour.start_time}<span>{hour.end_time}</span></div>)}
          {hours.flatMap((hour, hourIndex) => days.map((item, dayIndex) => { const slot = slots.find((candidate) => candidate.slot_index === hour.slot_index && candidate.day_of_week === item); return <div className={`grid-cell ${slot?.is_blocked ? 'grid-cell-blocked' : ''}`} style={{ gridColumn: dayIndex + 2, gridRow: hourIndex + 2 }} key={`${item}-${hour.slot_index}`}>{slot?.is_blocked && <span>{slot.block_reason ?? 'Break'}</span>}</div> }))}
          {filteredRows.map((item) => { const dayIndex = days.indexOf(item.day); return <div className={`session-cell ${item.entry.session_type === 'Lab' ? 'session-lab' : 'session-lecture'}`} style={{ gridColumn: dayIndex + 2, gridRow: `${rowOf(item.startSlot.slot_index)} / span ${item.durationSlots}` }} key={item.entry.entry_id} title={`${item.course.course_code} · ${item.room.room_code} · ${item.instructor.full_name}`} role="group" aria-label={`${item.course.course_code}, ${item.room.room_code}, ${item.instructor.full_name}`}>
            <div className="session-topline"><strong>{item.course.course_code}</strong><span>{item.entry.session_type}</span></div><div className="session-title">{item.course.title}</div><div className="session-meta"><span>{item.room.room_code}</span><span>{item.instructor.full_name}</span></div>
            <div className="session-flags">{item.entry.is_locked && <span className="session-flag" title="Locked entry"><LockKeyhole size={13} aria-hidden="true" /><em>Locked</em></span>}{item.entry.is_manual_override && <span className="session-flag" title="Manual override"><PencilLine size={13} aria-hidden="true" /><em>Manual override</em></span>}</div>
            {canMove && <div className="session-actions no-print"><button type="button" disabled={item.durationSlots > 1} title={item.durationSlots > 1 ? 'Multi-slot lab blocks cannot be moved one entry at a time' : 'Move this session'} onClick={() => setMoving(item)} aria-label={`Move ${item.course.course_code} ${item.entry.session_type}`}><ArrowRightLeft size={11} aria-hidden="true" />Move</button></div>}
          </div> })}
          {filteredRows.length === 0 && <div className="grid-empty" style={{ gridColumn: '2 / -1', gridRow: '2 / -1' }}>No timetable entries match this version and filter set.</div>}
        </div></div><div className="table-footnote"><Info size={14} /> Hover over a session for the full course, room and instructor label. Lab sessions occupy consecutive slots.{canMove ? ' Multi-slot lab blocks cannot be moved yet.' : ''}</div></Card>
      </>}
    </LoadState>
    {moving && selectedVersion && <MoveDialog row={moving} slots={slots} rooms={rooms} scheduleId={selectedVersion.schedule_id} onClose={() => setMoving(null)} onMoved={() => { setMoving(null); onStatus(`${moving.course.course_code} moved. All hard constraints re-validated.`); view.reload() }} />}
  </div>
}
