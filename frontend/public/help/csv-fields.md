# CSV field reference
All fields are required. Use UTF-8, exact headers, at most 10 MB, and the server preview/confirmation workflow. Examples are illustrative: create the referenced term/department/accounts before import. Imported duplicates are rejected, never treated as updates.

## courses
```csv
course_code,title,department_code,credit_hours,lecture_hours,lab_hours
CSE 205,Operating Systems,CSE,3,3,0
```
- `course_code`: Unique course code for course creation; an existing active course reference in offerings/enrollments.
- `title`: UTF-8 course title.
- `department_code`: Existing department code; exact reference match.
- `credit_hours`: Whole-number course credit hours within the form limits.
- `lecture_hours`: Nonnegative whole-number weekly lecture slots; total contact hours must be positive.
- `lab_hours`: Nonnegative whole-number lab slots; multi-slot labs must be consecutive.

## instructors
```csv
full_name,email,department_code,max_daily_hours,max_weekly_hours
Example Instructor,instructor@example.edu,CSE,4,16
```
- `full_name`: UTF-8 instructor name.
- `email`: Unique valid instructor email.
- `department_code`: Existing department code; exact reference match.
- `max_daily_hours`: Positive whole-number instructor daily teaching limit within form bounds.
- `max_weekly_hours`: Positive whole-number instructor weekly limit within form bounds.

## rooms
```csv
room_code,building,capacity,room_type
R101,Main,50,Lecture
```
- `room_code`: Unique room code.
- `building`: Room building name/code.
- `capacity`: Positive whole-number seat capacity.
- `room_type`: Exactly Lecture, Lab or Exam Hall.

## batches
```csv
program_code,batch_year,section,strength,department_code
CSE,2027,A,40,CSE
```
- `program_code`: Program identifier; together with batch_year and section identifies a batch.
- `batch_year`: Whole-number batch year, combined with program_code and section.
- `section`: Batch section; combined with program_code and batch_year.
- `strength`: Positive whole-number batch strength.
- `department_code`: Existing department code; exact reference match.

## offerings
```csv
term_name,course_code,program_code,batch_year,section,instructor_email,enrolled_count
Example term,CSE 205,CSE,2027,A,instructor@example.edu,40
```
- `term_name`: Existing academic term name; selects the term scope.
- `course_code`: Unique course code for course creation; an existing active course reference in offerings/enrollments.
- `program_code`: Program identifier; together with batch_year and section identifies a batch.
- `batch_year`: Whole-number batch year, combined with program_code and section.
- `section`: Batch section; combined with program_code and batch_year.
- `instructor_email`: Existing active instructor email.
- `enrolled_count`: Nonnegative whole-number offering enrollment count.

## enrollments
```csv
term_name,course_code,program_code,batch_year,section,student_username
Example term,CSE 205,CSE,2027,A,student_example
```
- `term_name`: Existing academic term name; selects the term scope.
- `course_code`: Unique course code for course creation; an existing active course reference in offerings/enrollments.
- `program_code`: Program identifier; together with batch_year and section identifies a batch.
- `batch_year`: Whole-number batch year, combined with program_code and section.
- `section`: Batch section; combined with program_code and batch_year.
- `student_username`: Existing active Student account with a trusted batch identity link; repeat/elective enrollments may cross offering batches.
