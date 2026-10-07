BEGIN;

-- Keep the current semester aligned with the requested subject list and faculty.
-- Theory:
--   CS202 System Software            -> Gaurav Pareek
--   CS204 Database Management Systems -> Abhishek Paul
--   CS206 Software Engineering        -> Deepika Gupta
--   CS208 COA                         -> Varun + Uday
--   MA202 Numerical Techniques        -> Mukesh Thakur
-- Labs reuse the same subject teacher and use +60 course codes.

INSERT INTO teachers (teacher_id, name, email, department)
VALUES
    ('T001', 'Varun',          'varun@diu.iiitvadodara.ac.in',  'CSE'),
    ('T002', 'Abhishek Paul',  'dbms@diu.iiitvadodara.ac.in',   'CSE'),
    ('T003', 'Gaurav Pareek',  'ss@diu.iiitvadodara.ac.in',     'CSE'),
    ('T004', 'Deepika Gupta',  'se@diu.iiitvadodara.ac.in',     'CSE'),
    ('T005', 'Mukesh Thakur',  'ma@diu.iiitvadodara.ac.in',     'CSE'),
    ('T006', 'Uday',           'uday@diu.iiitvadodara.ac.in',   'CSE')
ON CONFLICT (teacher_id) DO UPDATE
SET
    name = EXCLUDED.name,
    email = EXCLUDED.email,
    department = EXCLUDED.department;

INSERT INTO courses (course_id, course_name, department, semester, credits)
VALUES
    ('CS202', 'System Software',                            'CSE', 4, 3),
    ('CS204', 'Database Management Systems',                'CSE', 4, 4),
    ('CS206', 'Software Engineering',                       'CSE', 4, 3),
    ('CS208', 'Computer Organisation and Architecture',     'CSE', 4, 4),
    ('MA202', 'Numerical Techniques',                       'CSE', 4, 4),
    ('CS264', 'Database Management Systems Lab',            'CSE', 4, 4),
    ('CS266', 'Software Engineering Lab',                   'CSE', 4, 3),
    ('CS268', 'Computer Organisation and Architecture Lab', 'CSE', 4, 4),
    ('MA262', 'Numerical Techniques Lab',                   'CSE', 4, 4)
ON CONFLICT (course_id) DO UPDATE
SET
    course_name = EXCLUDED.course_name,
    department = EXCLUDED.department,
    semester = EXCLUDED.semester,
    credits = EXCLUDED.credits;

-- Preserve any existing lecture history by remapping old demo course IDs
-- to the requested theory/lab IDs before cleaning the old rows up.
UPDATE lecture_sessions
SET course_id = CASE
    WHEN course_id = 'CS401' AND classroom_id = 'CR-LAB' THEN 'CS268'
    WHEN course_id = 'CS401' THEN 'CS208'
    WHEN course_id = 'CS402' AND classroom_id = 'CR-LAB' THEN 'CS264'
    WHEN course_id = 'CS402' THEN 'CS204'
    WHEN course_id = 'CS403' THEN 'CS202'
    WHEN course_id = 'CS404' AND classroom_id = 'CR-LAB' THEN 'CS266'
    WHEN course_id = 'CS404' THEN 'CS206'
    WHEN course_id = 'CS405' AND classroom_id = 'CR-LAB' THEN 'MA262'
    WHEN course_id = 'CS405' THEN 'MA202'
    WHEN course_id = 'CS406' THEN 'MA202'
    ELSE course_id
END
WHERE course_id IN ('CS401', 'CS402', 'CS403', 'CS404', 'CS405', 'CS406');

DELETE FROM course_teachers;

INSERT INTO course_teachers (course_id, teacher_id)
VALUES
    ('CS208', 'T001'),
    ('CS208', 'T006'),
    ('CS268', 'T001'),
    ('CS268', 'T006'),
    ('CS206', 'T004'),
    ('CS266', 'T004'),
    ('MA202', 'T005'),
    ('MA262', 'T005'),
    ('CS204', 'T002'),
    ('CS264', 'T002'),
    ('CS202', 'T003')
ON CONFLICT (course_id, teacher_id) DO NOTHING;

DELETE FROM weekly_schedule;

INSERT INTO weekly_schedule (course_id, classroom_id, day_of_week, start_time, end_time)
VALUES
    ('CS268', 'CR-LAB',  'Monday',    '09:00', '13:15'),
    ('CS208', 'CR-2113', 'Monday',    '14:00', '15:30'),
    ('CS202', 'CR-2113', 'Monday',    '15:30', '17:00'),
    ('MA262', 'CR-LAB',  'Tuesday',   '09:00', '11:00'),
    ('MA262', 'CR-LAB',  'Tuesday',   '11:00', '13:00'),
    ('CS204', 'CR-2113', 'Tuesday',   '14:00', '15:30'),
    ('CS206', 'CR-2113', 'Tuesday',   '15:30', '17:00'),
    ('CS264', 'CR-LAB',  'Wednesday', '10:45', '12:30'),
    ('MA202', 'CR-2113', 'Wednesday', '14:00', '15:30'),
    ('CS208', 'CR-2113', 'Wednesday', '15:30', '17:00'),
    ('CS266', 'CR-LAB',  'Thursday',  '09:00', '12:00'),
    ('CS202', 'CR-2113', 'Thursday',  '14:00', '15:30'),
    ('CS204', 'CR-2113', 'Thursday',  '15:30', '17:00'),
    ('MA202', 'CR-2113', 'Friday',    '14:00', '15:30');

DELETE FROM courses
WHERE course_id IN ('CS401', 'CS402', 'CS403', 'CS404', 'CS405', 'CS406');

COMMIT;
