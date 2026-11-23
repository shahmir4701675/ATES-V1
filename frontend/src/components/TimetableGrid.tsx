import { ArrowRightLeft } from 'lucide-react'
import { useMemo } from 'react'
import type { TimeSlot, TimetableRow } from '../types'

/** Each physical day/slot owns a normal-flow stack; parallel classes never overlay. */
export function TimetableGrid({ rows, slots, days, canMove, onMove }: { rows: TimetableRow[]; slots: TimeSlot[]; days: string[]; canMove: boolean; onMove: (row: TimetableRow) => void }) {
  const { hours, slotByCell, rowsByCell } = useMemo(() => {
    const slotByCell = new Map(slots.map((slot) => [`${slot.day_of_week}:${slot.slot_index}`, slot]))
    const rowsByCell = new Map<string, TimetableRow[]>()
    for (const row of rows) {
      for (let i = 0; i < row.durationSlots; i += 1) {
        const key = `${row.day}:${row.startSlot.slot_index + i}`
        const list = rowsByCell.get(key) ?? []
        list.push(row); rowsByCell.set(key, list)
      }
    }
    return { hours: [...new Map(slots.map((slot) => [slot.slot_index, slot])).values()].sort((a, b) => a.slot_index - b.slot_index), slotByCell, rowsByCell }
  }, [slots, rows])
  return <div className="timetable-grid" style={{ gridTemplateColumns: `82px repeat(${days.length}, minmax(145px, 1fr))`, gridTemplateRows: `40px repeat(${hours.length}, minmax(78px, auto))` }}>
          <div className="grid-corner">Time</div>
          {days.map((item) => <div className="day-header" key={item}>{item}<span>{item.slice(0, 3).toUpperCase()}</span></div>)}
          {hours.map((hour, index) => <div className="time-cell tabular" style={{ gridColumn: 1, gridRow: index + 2 }} key={`time-${hour.slot_index}`}>Slot {hour.slot_index}</div>)}
          {hours.flatMap((hour, hourIndex) => days.map((day, dayIndex) => {
            const slot = slotByCell.get(`${day}:${hour.slot_index}`)
            const matches = rowsByCell.get(`${day}:${hour.slot_index}`) ?? []
            return <div className={`grid-cell session-stack ${slot?.is_blocked ? 'grid-cell-blocked' : ''}`} style={{ gridColumn: dayIndex + 2, gridRow: hourIndex + 2 }} key={`${day}-${hour.slot_index}`}>
              <small className="tabular">{slot?.start_time}–{slot?.end_time}</small>
              {slot?.is_blocked && <span>{slot.block_reason ?? 'Break'}</span>}
              {matches.map((item) => <div className={`session-cell session-in-stack ${item.entry.session_type === 'Lab' ? 'session-lab' : 'session-lecture'}`} key={item.entry.entry_id}>
                <strong>{item.course.course_code}</strong><span>{item.course.title}</span>
                <small>{item.batch.program_code} {item.batch.batch_year} {item.batch.section} · {item.instructor.full_name} · {item.room.room_code}</small>
                <small>{item.entry.session_type}{item.startSlot.slot_index < hour.slot_index ? ' (continued)' : ''}{item.entry.is_locked ? ' · Locked' : ''}{item.entry.is_manual_override ? ' · Manual override' : ''}</small>
                {canMove && <button type="button" className="move-session" onClick={() => onMove(item)} aria-label={`Adjust ${item.course.course_code}, ${item.batch.program_code}, slot ${hour.slot_index}`}><ArrowRightLeft size={11} aria-hidden="true" />Adjust / lock</button>}
              </div>)}
            </div>
          }))}
          {rows.length === 0 && <div className="grid-empty" style={{ gridColumn: '2 / -1', gridRow: '2 / -1' }}>No timetable entries match this version and filter set.</div>}
        </div>
}
