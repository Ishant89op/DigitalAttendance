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
    ('CS401', 'Computer Organisation and Architecture', 'CSE', 4, 4),
    ('CS402', 'Database Management Systems',            'CSE', 4, 4),
    ('CS403', 'System Software',                        'CSE', 4, 3),
    ('CS404', 'Software Engineering',                   'CSE', 4, 3),
    ('CS405', 'Mathematics',                            'CSE', 4, 4),
    ('CS406', 'Economics',                              'CSE', 4, 3)
ON CONFLICT (course_id) DO NOTHING;


-- ── TEACHERS ────────────────────────────────
INSERT INTO teachers (teacher_id, name, email, department)
VALUES
    ('T001', 'Prof. COA Faculty',             'coa@diu.iiitvadodara.ac.in', 'CSE'),
    ('T002', 'Prof. DBMS Faculty',            'dbms@diu.iiitvadodara.ac.in', 'CSE'),
    ('T003', 'Prof. System Software Faculty', 'ss@diu.iiitvadodara.ac.in',   'CSE'),
    ('T004', 'Prof. Software Engg Faculty',   'se@diu.iiitvadodara.ac.in',   'CSE'),
    ('T005', 'Prof. Mathematics Faculty',     'ma@diu.iiitvadodara.ac.in',   'CSE'),
    ('T006', 'Prof. Economics Faculty',       'eco@diu.iiitvadodara.ac.in',  'CSE')
ON CONFLICT (teacher_id) DO NOTHING;


-- ── COURSE–TEACHER ASSIGNMENTS ──────────────
INSERT INTO course_teachers (course_id, teacher_id)
VALUES
    ('CS401', 'T001'),
    ('CS402', 'T002'),
    ('CS403', 'T003'),
    ('CS404', 'T004'),
    ('CS405', 'T005'),
    ('CS406', 'T006')
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
    ('CS401', 'CR-LAB',  'Monday', '09:00', '13:15'),   -- COA lab
    ('CS401', 'CR-2113', 'Monday', '14:00', '15:30'),   -- COA theory
    ('CS403', 'CR-2113', 'Monday', '15:30', '17:00'),   -- System Software

-- Tuesday
    ('CS405', 'CR-LAB',  'Tuesday', '09:00', '11:00'),  -- MA lab
    ('CS405', 'CR-LAB',  'Tuesday', '11:00', '13:00'),  -- MA tutorial
    ('CS402', 'CR-2113', 'Tuesday', '14:00', '15:30'),  -- DBMS
    ('CS404', 'CR-2113', 'Tuesday', '15:30', '17:00'),  -- Software Engg

-- Wednesday
    ('CS402', 'CR-LAB',  'Wednesday', '10:45', '12:30'), -- DBMS lab
    ('CS406', 'CR-2113', 'Wednesday', '14:00', '15:30'), -- Economics
    ('CS401', 'CR-2113', 'Wednesday', '15:30', '17:00'), -- COA

-- Thursday
    ('CS404', 'CR-LAB',  'Thursday', '09:00', '12:00'),  -- SE tut+lab
    ('CS403', 'CR-2113', 'Thursday', '14:00', '15:30'),  -- System Software
    ('CS402', 'CR-2113', 'Thursday', '15:30', '17:00'),  -- DBMS

-- Friday
    ('CS406', 'CR-2113', 'Friday', '14:00', '15:30');    -- Economics


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
