import { useMemo } from 'react'
import { LoadState } from '../../components/ui'
import { useAsync } from '../../hooks/useAsync'
import {
  USE_MOCK, createBatch, createCourse, createEnrollment, createInstructor, createOffering, createRoom, deactivateBatch, deactivateCourse, deactivateInstructor, deactivateRoom,
  getBatches, getCourseOfferings, getCourses, getDepartments, getEnrollments, getInstructors, getRooms, getTerms, reactivateRecord, removeEnrollment, removeOffering,
  updateBatch, updateCourse, updateInstructor, updateOffering, updateRoom,
} from '../../services/api'
import type { Batch, Course, CourseOffering, Enrollment, Instructor, Room } from '../../types'
import { MasterTab, same, toInt, type MasterConfig } from './MasterTab'

interface TabProps { readOnly: boolean; onStatus: (message: string) => void }
const batchLabel = (batch: Batch) => `${batch.program_code} ${batch.batch_year} · ${batch.section}`
const required = (form: Record<string, string>, names: Array<[string, string]>, errors: Record<string, string>) => names.forEach(([name, label]) => { if (!form[name]?.trim()) errors[name] = `${label} is required.` })
const mustBeInt = (form: Record<string, string>, name: string, label: string, min: number, errors: Record<string, string>) => {
  if (errors[name]) return
  const value = toInt(form[name])
  if (Number.isNaN(value)) errors[name] = `${label} must be a whole number.`
  else if (value < min) errors[name] = min === 1 ? `${label} must be greater than 0.` : `${label} must be at least ${min}.`
}

/* ------------------------------------------------------------------------------ Courses */
export function CoursesTab({ readOnly, onStatus }: TabProps) {
  const departments = useAsync(getDepartments, [])
  const config = useMemo<MasterConfig<Course>>(() => {
    const deptName = (id: string) => departments.data?.find((item) => item.department_id === id)?.code ?? id
    return {
      noun: 'Course', plural: 'Courses', idOf: (row) => row.course_id, isActive: (row) => row.is_active, describe: (row) => row.course_code,
      searchText: (row) => `${row.course_code} ${row.title} ${deptName(row.department_id)}`,
      columns: [
        { key: 'code', label: 'Code', value: (row) => row.course_code, render: (row) => <strong>{row.course_code}</strong> },
        { key: 'title', label: 'Title', value: (row) => row.title },
        { key: 'dept', label: 'Department', value: (row) => deptName(row.department_id) },
        { key: 'credit', label: 'Credit hours', value: (row) => row.credit_hours },
        { key: 'lec', label: 'Lecture hours', value: (row) => row.lecture_hours },
        { key: 'lab', label: 'Lab hours', value: (row) => row.lab_hours },
      ],
      fields: [
        { name: 'course_code', label: 'Course code', type: 'text', tooltip: 'Unique code, up to 15 characters, for example CSE 204.' },
        { name: 'title', label: 'Title', type: 'text', tooltip: 'Full course title, up to 150 characters.' },
        { name: 'department_id', label: 'Department', type: 'select', tooltip: 'Department that owns the course.', options: (departments.data ?? []).map((item) => ({ value: item.department_id, label: `${item.code} · ${item.name}` })) },
        { name: 'credit_hours', label: 'Credit hours', type: 'number', min: 0, tooltip: 'Whole number, 0 or more.' },
        { name: 'lecture_hours', label: 'Lecture hours per week', type: 'number', min: 0, tooltip: 'Weekly lecture contact hours.' },
        { name: 'lab_hours', label: 'Lab hours per week', type: 'number', min: 0, tooltip: 'Weekly lab contact hours. Lecture plus lab must be more than 0.' },
      ],
      blank: { course_code: '', title: '', department_id: departments.data?.[0]?.department_id ?? '', credit_hours: '3', lecture_hours: '3', lab_hours: '0' },
      toForm: (row) => ({ course_code: row.course_code, title: row.title, department_id: row.department_id, credit_hours: String(row.credit_hours), lecture_hours: String(row.lecture_hours), lab_hours: String(row.lab_hours) }),
      validate: (form, rows, id) => {
        const errors: Record<string, string> = {}
        required(form, [['course_code', 'Course code'], ['title', 'Title'], ['department_id', 'Department']], errors)
        if (!errors.course_code && form.course_code.trim().length > 15) errors.course_code = 'Course code can have at most 15 characters.'
        if (!errors.course_code && rows.some((row) => row.course_id !== id && same(row.course_code, form.course_code))) errors.course_code = `Course code ${form.course_code.trim()} already exists. Codes must be unique.`
        if (!errors.title && form.title.trim().length > 150) errors.title = 'Title can have at most 150 characters.'
        mustBeInt(form, 'credit_hours', 'Credit hours', 0, errors); mustBeInt(form, 'lecture_hours', 'Lecture hours', 0, errors); mustBeInt(form, 'lab_hours', 'Lab hours', 0, errors)
        if (!errors.lecture_hours && !errors.lab_hours && toInt(form.lecture_hours) + toInt(form.lab_hours) <= 0) errors.lab_hours = 'Lecture hours plus lab hours must be greater than 0.'
        return errors
      },
      toPayload: (form) => ({ course_code: form.course_code.trim(), title: form.title.trim(), department_id: form.department_id, credit_hours: toInt(form.credit_hours), lecture_hours: toInt(form.lecture_hours), lab_hours: toInt(form.lab_hours) }),
      create: (payload) => createCourse({ is_active: true, ...payload } as Omit<Course, 'course_id'>), update: (id, payload) => updateCourse(id, payload),
      deactivate: deactivateCourse, reactivate: (id) => reactivateRecord('courses', id),
    }
  }, [departments.data])
  return <LoadState loading={departments.loading} error={departments.error} onRetry={departments.reload}><MasterTab config={config} load={getCourses} readOnly={readOnly} onStatus={onStatus} /></LoadState>
}

/* -------------------------------------------------------------------------- Instructors */
export function InstructorsTab({ readOnly, onStatus }: TabProps) {
  const departments = useAsync(getDepartments, [])
  const config = useMemo<MasterConfig<Instructor>>(() => {
    const deptName = (id: string) => departments.data?.find((item) => item.department_id === id)?.code ?? id
    return {
      noun: 'Instructor', plural: 'Instructors', idOf: (row) => row.instructor_id, isActive: (row) => row.is_active, describe: (row) => row.full_name,
      searchText: (row) => `${row.full_name} ${row.email} ${deptName(row.department_id)}`,
      columns: [
        { key: 'name', label: 'Name', value: (row) => row.full_name, render: (row) => <strong>{row.full_name}</strong> },
        { key: 'email', label: 'E-mail', value: (row) => row.email },
        { key: 'dept', label: 'Department', value: (row) => deptName(row.department_id) },
        { key: 'daily', label: 'Max daily hours', value: (row) => row.max_daily_hours },
        { key: 'weekly', label: 'Max weekly hours', value: (row) => row.max_weekly_hours },
      ],
      fields: [
        { name: 'full_name', label: 'Full name', type: 'text', tooltip: 'Name as it should appear on timetables.' },
        { name: 'email', label: 'E-mail', type: 'email', tooltip: 'Unique e-mail address.' },
        { name: 'department_id', label: 'Department', type: 'select', tooltip: 'Home department.', options: (departments.data ?? []).map((item) => ({ value: item.department_id, label: `${item.code} · ${item.name}` })) },
        { name: 'max_daily_hours', label: 'Maximum daily hours', type: 'number', min: 1, tooltip: 'Teaching hours allowed per day. Greater than 0.' },
        { name: 'max_weekly_hours', label: 'Maximum weekly hours', type: 'number', min: 1, tooltip: 'Teaching hours allowed per week. Not less than the daily maximum.' },
      ],
      blank: { full_name: '', email: '', department_id: departments.data?.[0]?.department_id ?? '', max_daily_hours: '4', max_weekly_hours: '18' },
      toForm: (row) => ({ full_name: row.full_name, email: row.email, department_id: row.department_id, max_daily_hours: String(row.max_daily_hours), max_weekly_hours: String(row.max_weekly_hours) }),
      validate: (form, rows, id) => {
        const errors: Record<string, string> = {}
        required(form, [['full_name', 'Full name'], ['email', 'E-mail'], ['department_id', 'Department']], errors)
        if (!errors.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) errors.email = 'Enter a valid e-mail address.'
        if (!errors.email && rows.some((row) => row.instructor_id !== id && same(row.email, form.email))) errors.email = `E-mail ${form.email.trim()} is already used by another instructor.`
        mustBeInt(form, 'max_daily_hours', 'Maximum daily hours', 1, errors); mustBeInt(form, 'max_weekly_hours', 'Maximum weekly hours', 1, errors)
        if (!errors.max_daily_hours && !errors.max_weekly_hours && toInt(form.max_weekly_hours) < toInt(form.max_daily_hours)) errors.max_weekly_hours = 'Weekly hours must be greater than or equal to daily hours.'
        return errors
      },
      toPayload: (form) => ({ full_name: form.full_name.trim(), email: form.email.trim(), department_id: form.department_id, max_daily_hours: toInt(form.max_daily_hours), max_weekly_hours: toInt(form.max_weekly_hours) }),
      create: (payload) => createInstructor({ is_active: true, ...payload } as Omit<Instructor, 'instructor_id'>), update: (id, payload) => updateInstructor(id, payload),
      deactivate: deactivateInstructor, reactivate: (id) => reactivateRecord('instructors', id),
    }
  }, [departments.data])
  return <LoadState loading={departments.loading} error={departments.error} onRetry={departments.reload}><MasterTab config={config} load={getInstructors} readOnly={readOnly} onStatus={onStatus} /></LoadState>
}

/* ------------------------------------------------------------------------------- Rooms */
export function RoomsTab({ readOnly, onStatus }: TabProps) {
  const config = useMemo<MasterConfig<Room>>(() => ({
    noun: 'Room', plural: 'Rooms', idOf: (row) => row.room_id, isActive: (row) => row.is_active, describe: (row) => row.room_code,
    searchText: (row) => `${row.room_code} ${row.building} ${row.room_type}`,
    columns: [
      { key: 'code', label: 'Room code', value: (row) => row.room_code, render: (row) => <strong>{row.room_code}</strong> },
      { key: 'building', label: 'Building', value: (row) => row.building },
      { key: 'capacity', label: 'Capacity', value: (row) => row.capacity },
      { key: 'type', label: 'Type', value: (row) => row.room_type },
    ],
    fields: [
      { name: 'room_code', label: 'Room code', type: 'text', tooltip: 'Unique code, up to 20 characters.' },
      { name: 'building', label: 'Building', type: 'text', tooltip: 'Building or block name.' },
      { name: 'capacity', label: 'Capacity', type: 'number', min: 1, tooltip: 'Number of seats. Greater than 0.' },
      { name: 'room_type', label: 'Room type', type: 'select', tooltip: 'Lectures use Lecture rooms, labs use Lab rooms, exams use Exam Halls.', options: ['Lecture', 'Lab', 'Exam Hall'].map((value) => ({ value, label: value })) },
    ],
    blank: { room_code: '', building: '', capacity: '40', room_type: 'Lecture' },
    toForm: (row) => ({ room_code: row.room_code, building: row.building, capacity: String(row.capacity), room_type: row.room_type }),
    validate: (form, rows, id) => {
      const errors: Record<string, string> = {}
      required(form, [['room_code', 'Room code'], ['building', 'Building'], ['room_type', 'Room type']], errors)
      if (!errors.room_code && form.room_code.trim().length > 20) errors.room_code = 'Room code can have at most 20 characters.'
      if (!errors.room_code && rows.some((row) => row.room_id !== id && same(row.room_code, form.room_code))) errors.room_code = `Room code ${form.room_code.trim()} already exists. Codes must be unique.`
      mustBeInt(form, 'capacity', 'Capacity', 1, errors)
      return errors
    },
    toPayload: (form) => ({ room_code: form.room_code.trim(), building: form.building.trim(), capacity: toInt(form.capacity), room_type: form.room_type }),
    create: (payload) => createRoom({ is_active: true, ...payload } as Omit<Room, 'room_id'>), update: (id, payload) => updateRoom(id, payload),
    deactivate: deactivateRoom, reactivate: (id) => reactivateRecord('rooms', id),
  }), [])
  return <MasterTab config={config} load={getRooms} readOnly={readOnly} onStatus={onStatus} />
}

/* ----------------------------------------------------------------------------- Batches */
export function BatchesTab({ readOnly, onStatus }: TabProps) {
  const config = useMemo<MasterConfig<Batch>>(() => ({
    noun: 'Batch', plural: 'Batches', idOf: (row) => row.batch_id, isActive: (row) => row.is_active, describe: (row) => batchLabel(row),
    searchText: (row) => `${row.program_code} ${row.batch_year} ${row.section}`,
    columns: [
      { key: 'program', label: 'Program', value: (row) => row.program_code, render: (row) => <strong>{row.program_code}</strong> },
      { key: 'year', label: 'Year', value: (row) => row.batch_year },
      { key: 'section', label: 'Section', value: (row) => row.section },
      { key: 'strength', label: 'Strength', value: (row) => row.strength },
    ],
    fields: [
      { name: 'program_code', label: 'Program code', type: 'text', tooltip: 'Program code, up to 10 characters, for example BSCS.' },
      { name: 'batch_year', label: 'Batch year', type: 'number', min: 2000, max: 2100, tooltip: 'Year of admission, 2000 to 2100.' },
      { name: 'section', label: 'Section', type: 'text', tooltip: 'Section label, up to 5 characters.' },
      { name: 'strength', label: 'Strength', type: 'number', min: 1, tooltip: 'Number of students. Greater than 0.' },
    ],
    blank: { program_code: '', batch_year: String(new Date().getFullYear()), section: 'A', strength: '50' },
    toForm: (row) => ({ program_code: row.program_code, batch_year: String(row.batch_year), section: row.section, strength: String(row.strength) }),
    validate: (form, rows, id) => {
      const errors: Record<string, string> = {}
      required(form, [['program_code', 'Program code'], ['section', 'Section']], errors)
      if (!errors.program_code && form.program_code.trim().length > 10) errors.program_code = 'Program code can have at most 10 characters.'
      if (!errors.section && form.section.trim().length > 5) errors.section = 'Section can have at most 5 characters.'
      mustBeInt(form, 'batch_year', 'Batch year', 2000, errors)
      if (!errors.batch_year && toInt(form.batch_year) > 2100) errors.batch_year = 'Batch year must be 2100 or earlier.'
      mustBeInt(form, 'strength', 'Strength', 1, errors)
      if (!errors.program_code && !errors.batch_year && !errors.section && rows.some((row) => row.batch_id !== id && same(row.program_code, form.program_code) && row.batch_year === toInt(form.batch_year) && same(row.section, form.section))) errors.section = 'This program, year and section already exist. Each batch must be unique.'
      return errors
    },
    toPayload: (form) => ({ program_code: form.program_code.trim(), batch_year: toInt(form.batch_year), section: form.section.trim(), strength: toInt(form.strength) }),
    create: (payload) => createBatch({ is_active: true, ...payload } as Omit<Batch, 'batch_id'>), update: (id, payload) => updateBatch(id, payload),
    deactivate: deactivateBatch, reactivate: (id) => reactivateRecord('batches', id),
  }), [])
  return <MasterTab config={config} load={getBatches} readOnly={readOnly} onStatus={onStatus} />
}

/* --------------------------------------------------------------------------- Offerings */
export function OfferingsTab({ readOnly, onStatus }: TabProps) {
  const refs = useAsync(() => Promise.all([getTerms(), getCourses(), getBatches(), getInstructors()]), [])
  const config = useMemo<MasterConfig<CourseOffering>>(() => {
    const [terms, courses, batches, instructors] = refs.data ?? [[], [], [], []]
    const termName = (id: string) => terms.find((item) => item.term_id === id)?.label ?? id
    const courseName = (id: string) => courses.find((item) => item.course_id === id)?.course_code ?? id
    const batchName = (id: string) => { const found = batches.find((item) => item.batch_id === id); return found ? batchLabel(found) : id }
    const instructorName = (id: string) => instructors.find((item) => item.instructor_id === id)?.full_name ?? id
    return {
      noun: 'Offering', plural: 'Offerings', idOf: (row) => row.offering_id, describe: (row) => `${courseName(row.course_id)} for ${batchName(row.batch_id)}`, removeLabel: 'Remove',
      searchText: (row) => `${termName(row.term_id)} ${courseName(row.course_id)} ${batchName(row.batch_id)} ${instructorName(row.instructor_id)}`,
      columns: [
        { key: 'term', label: 'Term', value: (row) => termName(row.term_id) },
        { key: 'course', label: 'Course', value: (row) => courseName(row.course_id), render: (row) => <strong>{courseName(row.course_id)}</strong> },
        { key: 'batch', label: 'Batch', value: (row) => batchName(row.batch_id) },
        { key: 'instructor', label: 'Instructor', value: (row) => instructorName(row.instructor_id) },
        { key: 'enrolled', label: 'Enrolled', value: (row) => row.enrolled_count },
      ],
      fields: [
        { name: 'term_id', label: 'Term', type: 'select', tooltip: 'Academic term of the offering.', options: terms.map((item) => ({ value: item.term_id, label: item.label })) },
        { name: 'course_id', label: 'Course', type: 'select', tooltip: 'Course being offered.', options: courses.filter((item) => item.is_active).map((item) => ({ value: item.course_id, label: `${item.course_code} · ${item.title}` })) },
        { name: 'batch_id', label: 'Batch', type: 'select', tooltip: 'Student batch taking the course.', options: batches.filter((item) => item.is_active).map((item) => ({ value: item.batch_id, label: batchLabel(item) })) },
        { name: 'instructor_id', label: 'Instructor', type: 'select', tooltip: 'Instructor who teaches the offering.', options: instructors.filter((item) => item.is_active).map((item) => ({ value: item.instructor_id, label: item.full_name })) },
        { name: 'enrolled_count', label: 'Enrolled students', type: 'number', min: 1, tooltip: 'Number of students enrolled. Greater than 0.' },
      ],
      blank: { term_id: terms.find((item) => item.status === 'Active')?.term_id ?? '', course_id: '', batch_id: '', instructor_id: '', enrolled_count: '40' },
      toForm: (row) => ({ term_id: row.term_id, course_id: row.course_id, batch_id: row.batch_id, instructor_id: row.instructor_id, enrolled_count: String(row.enrolled_count) }),
      validate: (form, rows, id) => {
        const errors: Record<string, string> = {}
        required(form, [['term_id', 'Term'], ['course_id', 'Course'], ['batch_id', 'Batch'], ['instructor_id', 'Instructor']], errors)
        mustBeInt(form, 'enrolled_count', 'Enrolled students', 1, errors)
        if (!errors.term_id && !errors.course_id && !errors.batch_id && rows.some((row) => row.offering_id !== id && row.term_id === form.term_id && row.course_id === form.course_id && row.batch_id === form.batch_id)) errors.course_id = 'This course is already offered to this batch in this term.'
        return errors
      },
      toPayload: (form) => ({ term_id: form.term_id, course_id: form.course_id, batch_id: form.batch_id, instructor_id: form.instructor_id, enrolled_count: toInt(form.enrolled_count) }),
      create: (payload) => createOffering(payload as Omit<CourseOffering, 'offering_id'>), update: (id, payload) => updateOffering(id, payload), deactivate: removeOffering,
    }
  }, [refs.data])
  return <LoadState loading={refs.loading} error={refs.error} onRetry={refs.reload}><MasterTab config={config} load={() => getCourseOfferings()} readOnly={readOnly} onStatus={onStatus} /></LoadState>
}

/* ------------------------------------------------------------------------- Enrollments */
export function EnrollmentsTab({ readOnly, onStatus }: TabProps) {
  const refs = useAsync(() => Promise.all([getCourseOfferings(), getCourses(), getBatches()]), [])
  const config = useMemo<MasterConfig<Enrollment>>(() => {
    const [offerings, courses, batches] = refs.data ?? [[], [], []]
    const offeringName = (id: string) => {
      const offering = offerings.find((item) => item.offering_id === id)
      if (!offering) return `Offering ${id}`
      const batch = batches.find((item) => item.batch_id === offering.batch_id)
      return `${courses.find((item) => item.course_id === offering.course_id)?.course_code ?? offering.course_id} · ${batch ? batchLabel(batch) : offering.batch_id}`
    }
    return {
      noun: 'Enrollment', plural: 'Enrollments', idOf: (row) => row.enrollment_id, describe: (row) => `student ${row.student_id} in ${offeringName(row.offering_id)}`, removeLabel: 'Remove',
      searchText: (row) => `${offeringName(row.offering_id)} ${row.student_id}`,
      columns: [
        { key: 'offering', label: 'Offering', value: (row) => offeringName(row.offering_id), render: (row) => <strong>{offeringName(row.offering_id)}</strong> },
        { key: 'student', label: 'Student user ID', value: (row) => row.student_id },
      ],
      fields: [
        { name: 'offering_id', label: 'Offering', type: 'select', tooltip: 'Course offering the student joins.', options: offerings.map((item) => ({ value: item.offering_id, label: offeringName(item.offering_id) })) },
        { name: 'student_id', label: 'Student user ID', type: USE_MOCK ? 'text' : 'number', min: 1, tooltip: 'ID of an existing user account with the Student role. Student names will be listed once the server has a users route.' },
      ],
      blank: { offering_id: '', student_id: '' },
      toForm: (row) => ({ offering_id: row.offering_id, student_id: row.student_id }),
      validate: (form, rows) => {
        const errors: Record<string, string> = {}
        required(form, [['offering_id', 'Offering'], ['student_id', 'Student user ID']], errors)
        if (!errors.student_id && !USE_MOCK && !(toInt(form.student_id) > 0)) errors.student_id = 'Student user ID must be a whole number greater than 0.'
        if (!errors.offering_id && !errors.student_id && rows.some((row) => row.offering_id === form.offering_id && row.student_id === form.student_id.trim())) errors.student_id = 'This student is already enrolled in this offering.'
        return errors
      },
      toPayload: (form) => ({ offering_id: form.offering_id, student_id: form.student_id.trim() }),
      create: (payload) => createEnrollment(payload as Omit<Enrollment, 'enrollment_id'>), deactivate: removeEnrollment,
    }
  }, [refs.data])
  return <LoadState loading={refs.loading} error={refs.error} onRetry={refs.reload}><MasterTab config={config} load={getEnrollments} readOnly={readOnly} onStatus={onStatus} /></LoadState>
}
