import type {
  AppUser,
  AuditEntry,
  Batch,
  Course,
  CourseOffering,
  Department,
  Enrollment,
  ExamEntry,
  ExamRoomAllocation,
  ExamSlot,
  Instructor,
  Room,
  Schedule,
  Student,
  Term,
  TimeSlot,
  TimetableEntry,
} from '../types'

export const terms: Term[] = [
  { term_id: 'fall-2026', label: 'Fall 2026', start_date: '2026-08-24', end_date: '2026-12-18', status: 'Active' },
  { term_id: 'spring-2027', label: 'Spring 2027', start_date: '2027-01-18', end_date: '2027-05-14', status: 'Planned' },
]

export const courses: Course[] = [
  { course_id: 'c-cse101', course_code: 'CSE 101', title: 'Introduction to Computing', department_id: 'CSE', credit_hours: 3, lecture_hours: 3, lab_hours: 0, is_active: true },
  { course_id: 'c-cse204', course_code: 'CSE 204', title: 'Data Structures', department_id: 'CSE', credit_hours: 4, lecture_hours: 3, lab_hours: 2, is_active: true },
  { course_id: 'c-cse310', course_code: 'CSE 310', title: 'Database Systems', department_id: 'CSE', credit_hours: 3, lecture_hours: 3, lab_hours: 0, is_active: true },
  { course_id: 'c-mth201', course_code: 'MTH 201', title: 'Discrete Mathematics', department_id: 'MTH', credit_hours: 3, lecture_hours: 3, lab_hours: 0, is_active: true },
  { course_id: 'c-eee212', course_code: 'EEE 212', title: 'Digital Logic Design', department_id: 'EEE', credit_hours: 3, lecture_hours: 2, lab_hours: 2, is_active: true },
  { course_id: 'c-hum110', course_code: 'HUM 110', title: 'Academic Writing', department_id: 'HUM', credit_hours: 2, lecture_hours: 2, lab_hours: 0, is_active: true },
  { course_id: 'c-cse402', course_code: 'CSE 402', title: 'Software Engineering', department_id: 'CSE', credit_hours: 3, lecture_hours: 3, lab_hours: 0, is_active: true },
]

export const instructors: Instructor[] = [
  { instructor_id: 'i-01', full_name: 'Dr. Meera Rao', email: 'meera.rao@university.edu', department_id: 'CSE', max_daily_hours: 6, max_weekly_hours: 16, is_active: true },
  { instructor_id: 'i-02', full_name: 'Prof. Daniel Kim', email: 'daniel.kim@university.edu', department_id: 'CSE', max_daily_hours: 6, max_weekly_hours: 16, is_active: true },
  { instructor_id: 'i-03', full_name: 'Dr. Anika Sen', email: 'anika.sen@university.edu', department_id: 'MTH', max_daily_hours: 5, max_weekly_hours: 14, is_active: true },
  { instructor_id: 'i-04', full_name: 'Dr. Luis Moreno', email: 'luis.moreno@university.edu', department_id: 'EEE', max_daily_hours: 6, max_weekly_hours: 16, is_active: true },
  { instructor_id: 'i-05', full_name: 'Ms. Priya Shah', email: 'priya.shah@university.edu', department_id: 'HUM', max_daily_hours: 5, max_weekly_hours: 12, is_active: true },
]

export const rooms: Room[] = [
  { room_id: 'r-101', room_code: 'A-101', building: 'Academic Block A', capacity: 72, room_type: 'Lecture', is_active: true },
  { room_id: 'r-201', room_code: 'A-201', building: 'Academic Block A', capacity: 64, room_type: 'Lecture', is_active: true },
  { room_id: 'r-lab1', room_code: 'CS Lab 1', building: 'Technology Centre', capacity: 36, room_type: 'Lab', is_active: true },
  { room_id: 'r-lab2', room_code: 'EE Lab 2', building: 'Engineering Block', capacity: 32, room_type: 'Lab', is_active: true },
  { room_id: 'r-hall', room_code: 'Main Hall', building: 'Central Hall', capacity: 180, room_type: 'Exam Hall', is_active: true },
  { room_id: 'r-hall2', room_code: 'Seminar Hall', building: 'Central Hall', capacity: 96, room_type: 'Exam Hall', is_active: true },
]

export const batches: Batch[] = [
  { batch_id: 'b-cse24a', program_code: 'B.Tech CSE', batch_year: 2024, section: 'A', strength: 62, is_active: true },
  { batch_id: 'b-cse24b', program_code: 'B.Tech CSE', batch_year: 2024, section: 'B', strength: 58, is_active: true },
  { batch_id: 'b-eee24a', program_code: 'B.Tech EEE', batch_year: 2024, section: 'A', strength: 46, is_active: true },
]

const week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
const hours = [
  ['08:00', '09:00'], ['09:00', '10:00'], ['10:00', '11:00'], ['11:00', '12:00'],
  ['12:00', '13:00'], ['13:00', '14:00'], ['14:00', '15:00'], ['15:00', '16:00'], ['16:00', '17:00'],
]

export const time_slots: TimeSlot[] = week.flatMap((day) => hours.map(([start_time, end_time], slot_index) => ({
  slot_id: `slot-${day.slice(0, 3).toLowerCase()}-${slot_index}`,
  term_id: 'fall-2026',
  day_of_week: day,
  slot_index,
  start_time,
  end_time,
  is_blocked: slot_index === 4,
  block_reason: slot_index === 4 ? 'Lunch break' : null,
})))

export const course_offerings: CourseOffering[] = [
  { offering_id: 'off-101-a', term_id: 'fall-2026', course_id: 'c-cse101', batch_id: 'b-cse24a', instructor_id: 'i-01', enrolled_count: 62 },
  { offering_id: 'off-204-a', term_id: 'fall-2026', course_id: 'c-cse204', batch_id: 'b-cse24a', instructor_id: 'i-02', enrolled_count: 62 },
  { offering_id: 'off-204-b', term_id: 'fall-2026', course_id: 'c-cse204', batch_id: 'b-cse24b', instructor_id: 'i-02', enrolled_count: 58 },
  { offering_id: 'off-310-a', term_id: 'fall-2026', course_id: 'c-cse310', batch_id: 'b-cse24b', instructor_id: 'i-01', enrolled_count: 58 },
  { offering_id: 'off-201-e', term_id: 'fall-2026', course_id: 'c-mth201', batch_id: 'b-eee24a', instructor_id: 'i-03', enrolled_count: 46 },
  { offering_id: 'off-212-e', term_id: 'fall-2026', course_id: 'c-eee212', batch_id: 'b-eee24a', instructor_id: 'i-04', enrolled_count: 46 },
  { offering_id: 'off-110-a', term_id: 'fall-2026', course_id: 'c-hum110', batch_id: 'b-cse24a', instructor_id: 'i-05', enrolled_count: 62 },
]

const slot = (day: string, slot_index: number) => time_slots.find((item) => item.day_of_week === day && item.slot_index === slot_index)!.slot_id

export const timetable_entries: TimetableEntry[] = [
  { entry_id: 'tte-001', schedule_id: 'sch-tt-v3', offering_id: 'off-101-a', instructor_id: 'i-01', batch_id: 'b-cse24a', room_id: 'r-101', slot_id: slot('Monday', 0), session_type: 'Lecture', is_locked: true, is_manual_override: false },
  { entry_id: 'tte-002', schedule_id: 'sch-tt-v3', offering_id: 'off-204-a', instructor_id: 'i-02', batch_id: 'b-cse24a', room_id: 'r-201', slot_id: slot('Tuesday', 1), session_type: 'Lecture', is_locked: false, is_manual_override: false },
  { entry_id: 'tte-003', schedule_id: 'sch-tt-v3', offering_id: 'off-204-a', instructor_id: 'i-02', batch_id: 'b-cse24a', room_id: 'r-lab1', slot_id: slot('Wednesday', 5), session_type: 'Lab', is_locked: false, is_manual_override: true },
  { entry_id: 'tte-004', schedule_id: 'sch-tt-v3', offering_id: 'off-204-a', instructor_id: 'i-02', batch_id: 'b-cse24a', room_id: 'r-lab1', slot_id: slot('Wednesday', 6), session_type: 'Lab', is_locked: false, is_manual_override: true },
  { entry_id: 'tte-005', schedule_id: 'sch-tt-v3', offering_id: 'off-310-a', instructor_id: 'i-01', batch_id: 'b-cse24b', room_id: 'r-101', slot_id: slot('Thursday', 2), session_type: 'Lecture', is_locked: false, is_manual_override: false },
  { entry_id: 'tte-006', schedule_id: 'sch-tt-v3', offering_id: 'off-201-e', instructor_id: 'i-03', batch_id: 'b-eee24a', room_id: 'r-201', slot_id: slot('Friday', 3), session_type: 'Lecture', is_locked: false, is_manual_override: false },
  { entry_id: 'tte-007', schedule_id: 'sch-tt-v3', offering_id: 'off-212-e', instructor_id: 'i-04', batch_id: 'b-eee24a', room_id: 'r-lab2', slot_id: slot('Monday', 7), session_type: 'Lab', is_locked: false, is_manual_override: false },
  { entry_id: 'tte-008', schedule_id: 'sch-tt-v3', offering_id: 'off-212-e', instructor_id: 'i-04', batch_id: 'b-eee24a', room_id: 'r-lab2', slot_id: slot('Monday', 8), session_type: 'Lab', is_locked: false, is_manual_override: false },
  { entry_id: 'tte-009', schedule_id: 'sch-tt-v3', offering_id: 'off-110-a', instructor_id: 'i-05', batch_id: 'b-cse24a', room_id: 'r-201', slot_id: slot('Friday', 0), session_type: 'Lecture', is_locked: false, is_manual_override: false },
]

export const exam_slots: ExamSlot[] = [
  { exam_slot_id: 'exslot-1', term_id: 'fall-2026', exam_date: '2026-12-02', start_time: '09:00', end_time: '12:00', label: 'Morning session' },
  { exam_slot_id: 'exslot-2', term_id: 'fall-2026', exam_date: '2026-12-04', start_time: '14:00', end_time: '17:00', label: 'Afternoon session' },
  { exam_slot_id: 'exslot-3', term_id: 'fall-2026', exam_date: '2026-12-07', start_time: '09:00', end_time: '12:00', label: 'Morning session' },
  { exam_slot_id: 'exslot-4', term_id: 'fall-2026', exam_date: '2026-12-09', start_time: '14:00', end_time: '17:00', label: 'Afternoon session' },
]

export const exam_entries: ExamEntry[] = [
  { exam_entry_id: 'ex-001', schedule_id: 'sch-ex-v2', course_id: 'c-cse101', exam_slot_id: 'exslot-1', student_count: 62, is_locked: true },
  { exam_entry_id: 'ex-002', schedule_id: 'sch-ex-v2', course_id: 'c-mth201', exam_slot_id: 'exslot-1', student_count: 46, is_locked: false },
  { exam_entry_id: 'ex-003', schedule_id: 'sch-ex-v2', course_id: 'c-cse204', exam_slot_id: 'exslot-2', student_count: 120, is_locked: false },
  { exam_entry_id: 'ex-004', schedule_id: 'sch-ex-v2', course_id: 'c-cse310', exam_slot_id: 'exslot-3', student_count: 58, is_locked: false },
  { exam_entry_id: 'ex-005', schedule_id: 'sch-ex-v2', course_id: 'c-eee212', exam_slot_id: 'exslot-4', student_count: 46, is_locked: false },
]

export const exam_entry_batches: Record<string, string> = {
  'ex-001': 'b-cse24a',
  'ex-002': 'b-eee24a',
  'ex-003': 'b-cse24b',
  'ex-004': 'b-cse24b',
  'ex-005': 'b-eee24a',
}

export const exam_room_allocations: ExamRoomAllocation[] = [
  { allocation_id: 'alloc-001', exam_entry_id: 'ex-001', room_id: 'r-hall', seats_allocated: 62 },
  { allocation_id: 'alloc-002', exam_entry_id: 'ex-002', room_id: 'r-hall', seats_allocated: 46 },
  { allocation_id: 'alloc-003', exam_entry_id: 'ex-003', room_id: 'r-hall', seats_allocated: 86 },
  { allocation_id: 'alloc-004', exam_entry_id: 'ex-003', room_id: 'r-hall2', seats_allocated: 34 },
  { allocation_id: 'alloc-005', exam_entry_id: 'ex-004', room_id: 'r-hall', seats_allocated: 58 },
  { allocation_id: 'alloc-006', exam_entry_id: 'ex-005', room_id: 'r-hall', seats_allocated: 46 },
]

export const schedules: Schedule[] = [
  { schedule_id: 'sch-tt-v2', term_id: 'fall-2026', schedule_type: 'Timetable', version_no: 2, status: 'Archived', solver_status: 'Feasible', objective_score: 91.1, run_seconds: 68 },
  { schedule_id: 'sch-tt-v3', term_id: 'fall-2026', schedule_type: 'Timetable', version_no: 3, status: 'Published', solver_status: 'Optimal', objective_score: 94.2, run_seconds: 74 },
  { schedule_id: 'sch-ex-v2', term_id: 'fall-2026', schedule_type: 'Exam schedule', version_no: 2, status: 'Generated', solver_status: 'Feasible', objective_score: 88.6, run_seconds: 51 },
]

export const departments: Department[] = [
  { department_id: 'CSE', code: 'CSE', name: 'Computer Science and Engineering' },
  { department_id: 'EEE', code: 'EEE', name: 'Electrical and Electronic Engineering' },
  { department_id: 'MTH', code: 'MTH', name: 'Mathematics' },
  { department_id: 'HUM', code: 'HUM', name: 'Humanities' },
]

export const students: Student[] = [
  { student_id: 'u-s01', full_name: 'Hira Baig', batch_id: 'b-cse24a' },
  { student_id: 'u-s02', full_name: 'Omar Siddiqui', batch_id: 'b-cse24a' },
  { student_id: 'u-s03', full_name: 'Sana Qureshi', batch_id: 'b-cse24b' },
  { student_id: 'u-s04', full_name: 'Zain Abbas', batch_id: 'b-eee24a' },
]

export const enrollments: Enrollment[] = [
  { enrollment_id: 'enr-1', offering_id: 'off-101-a', student_id: 'u-s01' },
  { enrollment_id: 'enr-2', offering_id: 'off-101-a', student_id: 'u-s02' },
  { enrollment_id: 'enr-3', offering_id: 'off-204-b', student_id: 'u-s03' },
  { enrollment_id: 'enr-4', offering_id: 'off-212-e', student_id: 'u-s04' },
]

export const users: AppUser[] = [
  { user_id: 'u-1', username: 'aroy', full_name: 'Alex Roy', email: 'alex.roy@university.edu', role: 'Administrator', account_status: 'Active', instructor_id: null, batch_id: null },
  { user_id: 'u-2', username: 'coordinator', full_name: 'Nadia Khan', email: 'nadia.khan@university.edu', role: 'Coordinator', account_status: 'Active', instructor_id: null, batch_id: null },
  { user_id: 'u-3', username: 'approver', full_name: 'Prof. Imran Lodhi', email: 'imran.lodhi@university.edu', role: 'Approver', account_status: 'Active', instructor_id: null, batch_id: null },
  { user_id: 'u-4', username: 'mrao', full_name: 'Dr. Meera Rao', email: 'meera.rao@university.edu', role: 'Faculty', account_status: 'Active', instructor_id: 'i-01', batch_id: null },
  { user_id: 'u-s01', username: 'hbaig', full_name: 'Hira Baig', email: 'hira.baig@student.university.edu', role: 'Student', account_status: 'Locked', instructor_id: null, batch_id: 'b-cse24a' },
]

export const audit_log: AuditEntry[] = [
  { log_id: 'a-5', user_id: 'u-3', username: 'approver', action: 'PUBLISH', entity_type: 'schedules', entity_id: 'sch-tt-v3', details: 'Published timetable version 3.', created_at: '2026-11-08T10:18:00Z' },
  { log_id: 'a-4', user_id: 'u-2', username: 'coordinator', action: 'MANUAL_ADJUST', entity_type: 'timetable_entries', entity_id: 'tte-003', details: 'Moved lab session to Wednesday slot 6.', created_at: '2026-11-07T16:50:00Z' },
  { log_id: 'a-3', user_id: 'u-2', username: 'coordinator', action: 'GENERATE', entity_type: 'schedules', entity_id: 'sch-ex-v2', details: 'Generated exam schedule version 2.', created_at: '2026-11-07T16:42:00Z' },
  { log_id: 'a-2', user_id: 'u-2', username: 'coordinator', action: 'CONFIG_CHANGE', entity_type: 'scheduling_configs', entity_id: '1', details: 'Updated 16 constraint rules.', created_at: '2026-11-07T13:06:00Z' },
  { log_id: 'a-1', user_id: 'u-1', username: 'aroy', action: 'USER_CREATE', entity_type: 'users', entity_id: 'u-4', details: 'Created account mrao (Faculty).', created_at: '2026-11-06T09:30:00Z' },
]
