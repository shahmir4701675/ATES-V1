"""Independent enrollment oracle for E01/E02; no solver membership/graph helpers.

Read raw enrollments as relations: a student takes each explicitly linked course,
and any incompletely enumerated offering in the same term/batch as that link.
Anonymous cohort witnesses account for students with no known enrollment IDs.
Complete offerings are not expanded merely because they share a batch.
"""
from collections import defaultdict


def validation_course_students(dataset, term_id=None):
    active = {course.course_id for course in dataset.courses if course.is_active}
    sources = {off.offering_id: off for off in dataset.course_offerings
               if term_id is None or off.term_id == term_id}
    offerings = {oid: off for oid, off in sources.items() if off.course_id in active}
    records = {(enr.offering_id, enr.student_id) for enr in dataset.enrollments
               if enr.offering_id in sources}
    incomplete = {oid for oid, off in offerings.items()
                  if sum(1 for record_oid, _ in records if record_oid == oid) < off.enrolled_count}
    courses_by_person = defaultdict(set)
    for oid, student in sorted(records):
        source = sources[oid]
        if source.course_id in active:
            courses_by_person[f"student:{student}"].add(source.course_id)
        for target_id in sorted(incomplete):
            target = offerings[target_id]
            if (source.term_id, source.batch_id) == (target.term_id, target.batch_id):
                courses_by_person[f"student:{student}"].add(target.course_id)
    for oid in sorted(incomplete):
        off = offerings[oid]
        courses_by_person[f"batch:{off.batch_id}"].add(off.course_id)
    result = {off.course_id: set() for off in offerings.values()}
    for person, courses in courses_by_person.items():
        for course_id in courses:
            result[course_id].add(person)
    return result
