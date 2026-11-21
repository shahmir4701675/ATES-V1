/** Static reference data (not mock records): constraint catalogue, day names, CSV import specs. */
import type { ConstraintRule, ImportType, ScheduleType } from '../types'

export const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export interface ConstraintMeta {
  code: string
  type: 'Hard' | 'Soft'
  title: string
  mandatory: boolean
  scheduleType: ScheduleType
  defaultWeight: number
  param?: { label: string; unit: string; min: number; max: number; defaultValue: number }
}

const hard = (code: string, title: string, scheduleType: ScheduleType, mandatory = false, param?: ConstraintMeta['param']): ConstraintMeta => ({ code, type: 'Hard', title, mandatory, scheduleType, defaultWeight: 0, param })
const soft = (code: string, title: string, scheduleType: ScheduleType, defaultWeight: number, param?: ConstraintMeta['param']): ConstraintMeta => ({ code, type: 'Soft', title, mandatory: false, scheduleType, defaultWeight, param })

/** Source: SRS constraint catalogue (H01–H10, S01–S06, E01–E05, ES01–ES03). */
export const CONSTRAINT_CATALOGUE: ConstraintMeta[] = [
  hard('H01', 'An instructor teaches at most one session in a slot', 'Timetable', true),
  hard('H02', 'A room hosts at most one session in a slot', 'Timetable', true),
  hard('H03', 'A batch attends at most one session in a slot', 'Timetable', true),
  hard('H04', 'Room capacity is at least the enrolled count of the offering', 'Timetable'),
  hard('H05', 'Labs are held in lab rooms and lectures in lecture rooms', 'Timetable'),
  hard('H06', 'No session in a slot in which the instructor is unavailable', 'Timetable'),
  hard('H07', 'No session in a blocked slot (break or prayer time)', 'Timetable'),
  hard('H08', 'Every offering receives exactly its required lecture sessions and lab blocks', 'Timetable', true),
  hard('H09', 'A lab block occupies consecutive slots of one day in one room', 'Timetable'),
  hard('H10', 'An instructor does not exceed the daily and weekly teaching hours', 'Timetable'),
  soft('S01', 'Minimise idle gaps between the sessions of a batch on a day', 'Timetable', 5),
  soft('S02', 'Spread the sessions of one offering over different days', 'Timetable', 5),
  soft('S03', 'Keep the sessions of a batch per day at or below the parameter', 'Timetable', 5, { label: 'Maximum sessions per batch per day', unit: 'sessions', min: 1, max: 12, defaultValue: 5 }),
  soft('S04', 'Keep consecutive teaching slots of an instructor at or below the parameter', 'Timetable', 5, { label: 'Maximum consecutive slots', unit: 'slots', min: 1, max: 12, defaultValue: 3 }),
  soft('S05', 'Prefer the same slot and room as in the previous version', 'Timetable', 5),
  soft('S06', 'Prefer the smallest room that fits the offering', 'Timetable', 5),
  hard('E01', 'Two courses that share a student are not in the same exam session', 'Exam schedule', true),
  hard('E02', 'No student has more exams per day than the configured maximum', 'Exam schedule', false, { label: 'Maximum exams per student per day', unit: 'exams', min: 1, max: 5, defaultValue: 2 }),
  hard('E03', 'Allocated seats equal the student count and never exceed room capacity', 'Exam schedule'),
  hard('E04', 'A room is used by at most one exam in a session', 'Exam schedule', true),
  hard('E05', 'Every course with an exam is assigned to exactly one session', 'Exam schedule', true),
  soft('ES01', 'Spread the exams of one batch over different days', 'Exam schedule', 8),
  soft('ES02', 'Use as few rooms as possible per exam', 'Exam schedule', 5),
  soft('ES03', 'Keep the rooms of one exam in the same building', 'Exam schedule', 4),
]

export const MANDATORY_CODES = new Set(CONSTRAINT_CATALOGUE.filter((item) => item.mandatory).map((item) => item.code))

export const defaultRules = (scheduleType: ScheduleType): ConstraintRule[] => CONSTRAINT_CATALOGUE
  .filter((item) => item.scheduleType === scheduleType)
  .map((item) => ({ rule_code: item.code, rule_type: item.type, is_enabled: true, weight: item.defaultWeight, param_value: item.param?.defaultValue ?? null }))

/* ---------------------------------------------------------------- CSV import specs */

export interface ImportColumn {
  name: string
  kind: 'text' | 'int' | 'enum'
  min?: number
  enumValues?: string[]
  example: string
}

export const IMPORT_SPECS: Record<ImportType, { label: string; columns: ImportColumn[] }> = {
  courses: { label: 'Courses', columns: [
    { name: 'course_code', kind: 'text', example: 'CSE 205' }, { name: 'title', kind: 'text', example: 'Operating Systems' }, { name: 'department_code', kind: 'text', example: 'CSE' },
    { name: 'credit_hours', kind: 'int', min: 0, example: '3' }, { name: 'lecture_hours', kind: 'int', min: 0, example: '3' }, { name: 'lab_hours', kind: 'int', min: 0, example: '0' },
  ] },
  instructors: { label: 'Instructors', columns: [
    { name: 'full_name', kind: 'text', example: 'Dr. Sara Malik' }, { name: 'email', kind: 'text', example: 'sara.malik@university.edu' }, { name: 'department_code', kind: 'text', example: 'CSE' },
    { name: 'max_daily_hours', kind: 'int', min: 1, example: '4' }, { name: 'max_weekly_hours', kind: 'int', min: 1, example: '16' },
  ] },
  rooms: { label: 'Rooms', columns: [
    { name: 'room_code', kind: 'text', example: 'B-101' }, { name: 'building', kind: 'text', example: 'Academic Block B' },
    { name: 'capacity', kind: 'int', min: 1, example: '60' }, { name: 'room_type', kind: 'enum', enumValues: ['Lecture', 'Lab', 'Exam Hall'], example: 'Lecture' },
  ] },
  batches: { label: 'Batches', columns: [
    { name: 'program_code', kind: 'text', example: 'BSCS' }, { name: 'batch_year', kind: 'int', min: 2000, example: '2025' },
    { name: 'section', kind: 'text', example: 'A' }, { name: 'strength', kind: 'int', min: 1, example: '55' },
  ] },
  offerings: { label: 'Offerings', columns: [
    { name: 'term_name', kind: 'text', example: 'Fall 2026' }, { name: 'course_code', kind: 'text', example: 'CSE 204' }, { name: 'program_code', kind: 'text', example: 'BSCS' },
    { name: 'batch_year', kind: 'int', min: 2000, example: '2024' }, { name: 'section', kind: 'text', example: 'A' }, { name: 'instructor_email', kind: 'text', example: 'meera.rao@university.edu' },
    { name: 'enrolled_count', kind: 'int', min: 1, example: '60' },
  ] },
  enrollments: { label: 'Enrollments', columns: [
    { name: 'term_name', kind: 'text', example: 'Fall 2026' }, { name: 'course_code', kind: 'text', example: 'CSE 204' }, { name: 'program_code', kind: 'text', example: 'BSCS' },
    { name: 'batch_year', kind: 'int', min: 2000, example: '2024' }, { name: 'section', kind: 'text', example: 'A' }, { name: 'student_username', kind: 'text', example: 'hbaig' },
  ] },
}

export const MAX_IMPORT_BYTES = 10 * 1024 * 1024

export function importTemplateCsv(type: ImportType): string {
  const columns = IMPORT_SPECS[type].columns
  return `${columns.map((column) => column.name).join(',')}\r\n${columns.map((column) => csvCell(column.example)).join(',')}\r\n`
}

const csvCell = (value: string) => (/[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value)

/** Minimal RFC 4180 parser. Returns rows with their 1-based physical line numbers. */
export function parseCsv(text: string): Array<{ line: number; cells: string[] }> {
  const rows: Array<{ line: number; cells: string[] }> = []
  let cells: string[] = []
  let cell = ''
  let quoted = false
  let line = 1
  let rowLine = 1
  const pushRow = () => { cells.push(cell); if (cells.some((item) => item.trim() !== '')) rows.push({ line: rowLine, cells }); cells = []; cell = '' }
  const source = text.replace(/^\uFEFF/, '')
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index]
    if (quoted) {
      if (char === '"' && source[index + 1] === '"') { cell += '"'; index += 1 } else if (char === '"') quoted = false
      else { if (char === '\n') line += 1; cell += char }
    } else if (char === '"') quoted = true
    else if (char === ',') { cells.push(cell); cell = '' }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && source[index + 1] === '\n') index += 1
      pushRow(); line += 1; rowLine = line
    } else cell += char
  }
  if (cell !== '' || cells.length) pushRow()
  return rows
}
