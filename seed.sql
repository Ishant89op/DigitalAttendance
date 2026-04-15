-- ─────────────────────────────────────────────
-- Smart Attendance System — Seed Data
-- Run: psql -U postgres -d attendance_system -f seed.sql
-- ─────────────────────────────────────────────


-- ── CLASSROOMS ──────────────────────────────
INSERT INTO classrooms (classroom_id, room_number, building, capacity)
VALUES
    ('CR-2113', '2113',      'Main Block', 60),
    ('CR-LAB',  'Lab Block', 'Lab Block',  30)
ON CONFLICT (classroom_id) DO NOTHING;


-- ── COURSES ─────────────────────────────────
INSERT INTO courses (course_id, course_name, department, semester, credits)
VALUES
    ('CS202', 'System Software',                             'CSE', 4, 3),
    ('CS204', 'Database Management Systems',                 'CSE', 4, 4),
    ('CS206', 'Software Engineering',                        'CSE', 4, 3),
    ('CS208', 'Computer Organisation and Architecture',      'CSE', 4, 4),
    ('MA202', 'Numerical Techniques',                        'CSE', 4, 4),
    ('CS264', 'Database Management Systems Lab',             'CSE', 4, 4),
    ('CS266', 'Software Engineering Lab',                    'CSE', 4, 3),
    ('CS268', 'Computer Organisation and Architecture Lab',  'CSE', 4, 4),
    ('MA262', 'Numerical Techniques Lab',                    'CSE', 4, 4)
ON CONFLICT (course_id) DO NOTHING;


-- ── TEACHERS ────────────────────────────────
INSERT INTO teachers (teacher_id, name, email, department)
VALUES
    ('T001', 'Varun',          'varun@diu.iiitvadodara.ac.in',           'CSE'),
    ('T002', 'Abhishek Paul',  'dbms@diu.iiitvadodara.ac.in',            'CSE'),
    ('T003', 'Gaurav Pareek',  'ss@diu.iiitvadodara.ac.in',              'CSE'),
    ('T004', 'Deepika Gupta',  'se@diu.iiitvadodara.ac.in',              'CSE'),
    ('T005', 'Mukesh Thakur',  'ma@diu.iiitvadodara.ac.in',              'CSE'),
    ('T006', 'Uday',           'uday@diu.iiitvadodara.ac.in',            'CSE')
ON CONFLICT (teacher_id) DO NOTHING;


-- ── COURSE–TEACHER ASSIGNMENTS ──────────────
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


-- ── STUDENTS ────────────────────────────────
INSERT INTO students (student_id, name, email, department, semester)
VALUES
    ('202411090', 'Shreyash Chaurasia', '202411090@diu.iiitvadodara.ac.in', 'CSE', 4),
    ('202411044', 'Ishant Yadav',       '202411044@diu.iiitvadodara.ac.in', 'CSE', 4),
    ('202411052', 'Kavya Sharma',       '202411052@diu.iiitvadodara.ac.in', 'CSE', 4),
    ('202411064', 'Naman Panwar',       '202411064@diu.iiitvadodara.ac.in', 'CSE', 4),
    ('202411028', 'Chinmay Patil',      '202411028@diu.iiitvadodara.ac.in', 'CSE', 4)
ON CONFLICT (student_id) DO NOTHING;


-- ── WEEKLY SCHEDULE ─────────────────────────
-- Monday
INSERT INTO weekly_schedule (course_id, classroom_id, day_of_week, start_time, end_time)
VALUES
    ('CS268', 'CR-LAB',  'Monday', '09:00', '13:15'),   -- COA lab
    ('CS208', 'CR-2113', 'Monday', '14:00', '15:30'),   -- COA theory
    ('CS202', 'CR-2113', 'Monday', '15:30', '17:00'),   -- System Software

-- Tuesday
    ('MA262', 'CR-LAB',  'Tuesday', '09:00', '11:00'),  -- Numerical Techniques lab
    ('MA262', 'CR-LAB',  'Tuesday', '11:00', '13:00'),  -- Numerical Techniques tutorial
    ('CS204', 'CR-2113', 'Tuesday', '14:00', '15:30'),  -- DBMS
    ('CS206', 'CR-2113', 'Tuesday', '15:30', '17:00'),  -- Software Engg

-- Wednesday
    ('CS264', 'CR-LAB',  'Wednesday', '10:45', '12:30'), -- DBMS lab
    ('MA202', 'CR-2113', 'Wednesday', '14:00', '15:30'), -- Numerical Techniques
    ('CS208', 'CR-2113', 'Wednesday', '15:30', '17:00'), -- COA

-- Thursday
    ('CS266', 'CR-LAB',  'Thursday', '09:00', '12:00'),  -- SE tut+lab
    ('CS202', 'CR-2113', 'Thursday', '14:00', '15:30'),  -- System Software
    ('CS204', 'CR-2113', 'Thursday', '15:30', '17:00'),  -- DBMS

-- Friday
    ('MA202', 'CR-2113', 'Friday', '14:00', '15:30');    -- Numerical Techniques


-- ── VERIFY ──────────────────────────────────
SELECT 'classrooms' AS table_name, COUNT(*) AS rows FROM classrooms
UNION ALL
SELECT 'courses',       COUNT(*) FROM courses
UNION ALL
SELECT 'teachers',      COUNT(*) FROM teachers
UNION ALL
SELECT 'course_teachers', COUNT(*) FROM course_teachers
UNION ALL
SELECT 'students',      COUNT(*) FROM students
UNION ALL
SELECT 'weekly_schedule', COUNT(*) FROM weekly_schedule;
