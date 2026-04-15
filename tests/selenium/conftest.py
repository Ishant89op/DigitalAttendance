import base64
import json
import os
from pathlib import Path
from typing import Any, Callable

import pytest
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.support.ui import WebDriverWait

ROOT_DIR = Path(__file__).resolve().parents[2]
UI_DIR = ROOT_DIR / "ui"


MOCK_DATA = {
    "students": [
        {
            "student_id": "202411052",
            "name": "Asha Patel",
            "email": "202411052@iiitvadodara.ac.in",
            "department": "CSE",
            "semester": 4,
            "face_registered": True,
        },
        {
            "student_id": "202411090",
            "name": "Ravi Shah",
            "email": "202411090@iiitvadodara.ac.in",
            "department": "CSE",
            "semester": 4,
            "face_registered": False,
        },
    ],
    "teachers": [
        {
            "teacher_id": "T001",
            "name": "Dr. Meera Iyer",
            "email": "meera.iyer@iiitvadodara.ac.in",
            "department": "CSE",
        }
    ],
    "courses": [
        {
            "course_id": "CS402",
            "course_name": "Database Management Systems",
            "department": "CSE",
            "semester": 4,
            "credits": 4,
        },
        {
            "course_id": "CS401",
            "course_name": "Computer Organization and Architecture",
            "department": "CSE",
            "semester": 4,
            "credits": 4,
        },
    ],
    "classrooms": [
        {
            "classroom_id": "CR-2113",
            "room_number": "2113",
            "building": "Main Block",
            "capacity": 60,
            "access_pin": "1234",
        },
        {
            "classroom_id": "CR-LAB",
            "room_number": "LAB-1",
            "building": "Lab Block",
            "capacity": 30,
            "access_pin": "1234",
        },
    ],
    "student_dashboard": {
        "overall_percentage": 82,
        "total_attended": 18,
        "total_lectures": 22,
        "alert": False,
        "subjects": [
            {
                "course_id": "CS402",
                "course_name": "Database Management Systems",
                "attended": 9,
                "total_lectures": 10,
                "percentage": 90,
                "status": "good",
            },
            {
                "course_id": "CS401",
                "course_name": "Computer Organization and Architecture",
                "attended": 9,
                "total_lectures": 12,
                "percentage": 75,
                "status": "warning",
            },
        ],
    },
    "student_history": [
        {
            "timestamp": "2026-04-14T09:11:00+05:30",
            "course_name": "Database Management Systems",
            "classroom_id": "CR-2113",
            "source": "face_recognition",
        },
        {
            "timestamp": "2026-04-13T11:03:00+05:30",
            "course_name": "Computer Organization and Architecture",
            "classroom_id": "CR-LAB",
            "source": "manual_override",
        },
    ],
    "teacher_dashboard": {
        "summary": {
            "total_courses": 2,
            "total_students": 2,
            "total_lectures": 18,
            "avg_attendance_pct": 82,
        },
        "courses": [
            {
                "course_id": "CS402",
                "course_name": "Database Management Systems",
                "total_students": 2,
                "total_lectures": 10,
                "avg_attendance_pct": 88,
                "today_status": "active",
            },
            {
                "course_id": "CS401",
                "course_name": "Computer Organization and Architecture",
                "total_students": 2,
                "total_lectures": 8,
                "avg_attendance_pct": 76,
                "today_status": "has_session",
            },
        ],
    },
    "teacher_course_details": {
        "CS402": {
            "course": {
                "course_id": "CS402",
                "course_name": "Database Management Systems",
                "department": "CSE",
                "semester": 4,
                "credits": 4,
                "teacher_names": "Dr. Meera Iyer",
                "total_students": 2,
                "total_lectures": 10,
                "avg_attendance_pct": 88,
            },
            "students": [
                {
                    "student_id": "202411052",
                    "name": "Asha Patel",
                    "email": "202411052@iiitvadodara.ac.in",
                    "total_lectures": 10,
                    "attended": 9,
                    "percentage": 90,
                    "last_present_at": "2026-04-14T09:11:00+05:30",
                    "face_registered": True,
                },
                {
                    "student_id": "202411090",
                    "name": "Ravi Shah",
                    "email": "202411090@iiitvadodara.ac.in",
                    "total_lectures": 10,
                    "attended": 7,
                    "percentage": 70,
                    "last_present_at": "2026-04-12T09:08:00+05:30",
                    "face_registered": False,
                },
            ],
            "recent_lectures": [
                {
                    "lecture_id": 4201,
                    "start_time": "2026-04-14T09:00:00+05:30",
                    "classroom_id": "CR-2113",
                    "status": "active",
                    "present_count": 1,
                    "percentage": 50,
                },
                {
                    "lecture_id": 4198,
                    "start_time": "2026-04-12T09:00:00+05:30",
                    "classroom_id": "CR-2113",
                    "status": "closed",
                    "present_count": 2,
                    "percentage": 100,
                },
            ],
        },
        "CS401": {
            "course": {
                "course_id": "CS401",
                "course_name": "Computer Organization and Architecture",
                "department": "CSE",
                "semester": 4,
                "credits": 4,
                "teacher_names": "Dr. Meera Iyer",
                "total_students": 2,
                "total_lectures": 8,
                "avg_attendance_pct": 76,
            },
            "students": [
                {
                    "student_id": "202411052",
                    "name": "Asha Patel",
                    "email": "202411052@iiitvadodara.ac.in",
                    "total_lectures": 8,
                    "attended": 6,
                    "percentage": 75,
                    "last_present_at": "2026-04-13T11:01:00+05:30",
                    "face_registered": True,
                },
                {
                    "student_id": "202411090",
                    "name": "Ravi Shah",
                    "email": "202411090@iiitvadodara.ac.in",
                    "total_lectures": 8,
                    "attended": 6,
                    "percentage": 75,
                    "last_present_at": "2026-04-13T11:03:00+05:30",
                    "face_registered": False,
                },
            ],
            "recent_lectures": [
                {
                    "lecture_id": 4301,
                    "start_time": "2026-04-13T11:00:00+05:30",
                    "classroom_id": "CR-LAB",
                    "status": "closed",
                    "present_count": 2,
                    "percentage": 100,
                }
            ],
        },
    },
    "admin_dashboard": {
        "totals": {
            "total_students": 2,
            "active_lectures": 1,
            "today_attendance": 1,
        },
        "low_attendance_students": [
            {
                "student_id": "202411090",
                "name": "Ravi Shah",
                "department": "CSE",
                "semester": 4,
                "percentage": 70,
            }
        ],
        "by_department": [{"department": "CSE", "avg_pct": 82.4}],
    },
    "lecture_upcoming": {
        "windows_mode": False,
        "manual_command": "python main.py recognize --classroom CR-2113",
        "active_lecture_id": None,
        "camera_active": False,
        "upcoming": [
            {
                "course_id": "CS402",
                "course_name": "Database Management Systems",
                "day_of_week": "Wednesday",
                "start_time": "09:00",
                "end_time": "10:30",
                "minutes_until_start": 0,
                "status": "ongoing",
            },
            {
                "course_id": "CS401",
                "course_name": "Computer Organization and Architecture",
                "day_of_week": "Wednesday",
                "start_time": "11:00",
                "end_time": "12:30",
                "minutes_until_start": 85,
                "status": "upcoming_today",
            },
        ],
    },
    "lecture_detail": {
        "lecture_id": 4201,
        "course_id": "CS402",
        "course_name": "Database Management Systems",
        "start_time": "2026-04-14T09:00:00+05:30",
        "status": "active",
    },
    "live_snapshot": {
        "present": 1,
        "absent": 1,
        "percentage": 50,
        "enrolled": 2,
        "absent_students": [{"student_id": "202411090", "name": "Ravi Shah"}],
    },
    "present_list": [
        {
            "student_id": "202411052",
            "name": "Asha Patel",
            "timestamp": "2026-04-14T09:11:00+05:30",
            "source": "face_recognition",
        }
    ],
    "audit_log": [
        {
            "created_at": "2026-04-14T09:11:10+05:30",
            "event_type": "attendance_marked",
            "actor_id": "recognizer",
            "target_id": "202411052",
            "detail": {"lecture_id": 4201},
        },
        {
            "created_at": "2026-04-14T09:13:00+05:30",
            "event_type": "manual_override",
            "actor_id": "T001",
            "target_id": "202411090",
            "detail": {"present": True},
        },
    ],
}

_MOCK_FIXTURES_JSON = json.dumps(MOCK_DATA, separators=(",", ":"))
MOCK_FETCH_SCRIPT = """
(() => {
  const fixtures = __FIXTURES__;

  const state = {
    activeLectureId: fixtures.lecture_detail.lecture_id,
    currentCourseId: fixtures.lecture_detail.course_id,
    currentCourseName: fixtures.lecture_detail.course_name,
  };

  const clone = (value) => JSON.parse(JSON.stringify(value));
  const parseBody = (rawBody) => {
    if (!rawBody || typeof rawBody !== "string") {
      return {};
    }
    try {
      return JSON.parse(rawBody);
    } catch (_err) {
      return {};
    }
  };

  const jsonResponse = (status, payload) =>
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    });

  const buildTeacherCourseDetail = (courseId) => {
    const fallback = fixtures.teacher_course_details.CS402;
    const detail = fixtures.teacher_course_details[courseId] || fallback;
    return clone(detail);
  };

  const route = (method, pathname, _search, bodyText) => {
        if (method === "POST" && pathname === "/auth/login") {
            const payload = parseBody(bodyText);
            const role = (payload.role || "").toLowerCase();
            const userId = payload.user_id;
            const password = payload.password;

            if (role === "student") {
                const found = fixtures.students.find((item) => item.student_id === userId);
                if (found && password === userId) {
                    return { role: "student", user_id: found.student_id, name: found.name };
                }
            }

            if (role === "teacher") {
                const found = fixtures.teachers.find((item) => item.teacher_id === userId);
                if (found && password === userId) {
                    return { role: "teacher", user_id: found.teacher_id, name: found.name };
                }
            }

            if (role === "admin") {
                if (userId === "admin" && password === "admin123") {
                    return { role: "admin", user_id: "admin", name: "Administrator" };
                }
            }

            return { __status: 401, detail: "Invalid ID or password." };
        }

    if (method === "GET" && pathname === "/admin/students") {
      return clone(fixtures.students);
    }
    if (method === "POST" && pathname === "/admin/students") {
      return parseBody(bodyText);
    }
    if (method === "PUT" && /^\/admin\/students\/[^/]+$/.test(pathname)) {
      return { ok: true };
    }
    if (method === "DELETE" && /^\/admin\/students\/[^/]+$/.test(pathname)) {
      return { deleted: true };
    }
    if (method === "GET" && pathname === "/admin/teachers") {
      return clone(fixtures.teachers);
    }
    if (method === "GET" && pathname === "/admin/courses") {
      return clone(fixtures.courses);
    }
    if (method === "GET" && pathname === "/admin/classrooms") {
      return clone(fixtures.classrooms);
    }
    if (method === "POST" && pathname === "/admin/classrooms") {
      return parseBody(bodyText);
    }
    if (method === "POST" && pathname.startsWith("/admin/upload/")) {
      return { inserted: 2, skipped: 0 };
    }
    if (method === "GET" && pathname === "/admin/audit-log") {
      return clone(fixtures.audit_log);
    }

    if (method === "GET" && /^\/analytics\/student\/[^/]+\/history$/.test(pathname)) {
      return clone(fixtures.student_history);
    }
    if (method === "GET" && /^\/analytics\/student\/[^/]+$/.test(pathname)) {
      return clone(fixtures.student_dashboard);
    }
    if (method === "GET" && /^\/analytics\/teacher\/[^/]+\/dashboard$/.test(pathname)) {
      return clone(fixtures.teacher_dashboard);
    }
    if (method === "GET" && /^\/analytics\/teacher\/[^/]+\/courses\/[^/]+$/.test(pathname)) {
      const courseId = pathname.split("/").pop();
      return buildTeacherCourseDetail(courseId);
    }
    if (method === "GET" && pathname === "/analytics/admin/dashboard") {
      return clone(fixtures.admin_dashboard);
    }

    if (method === "POST" && pathname === "/lecture/classroom-login") {
      return {
        room_number: "2113",
        building: "Main Block",
      };
    }
    if (method === "GET" && pathname.startsWith("/lecture/upcoming/")) {
      return clone(fixtures.lecture_upcoming);
    }
    if (method === "GET" && pathname.startsWith("/lecture/active/")) {
      return {
        lecture_id: null,
        windows_mode: false,
        camera_active: false,
        manual_command: "",
      };
    }
    if (method === "POST" && pathname === "/lecture/start") {
      const payload = parseBody(bodyText);
      const defaultCourse = fixtures.teacher_dashboard.courses[0];
      const selectedCourseId = payload.course_id || defaultCourse.course_id;
      const selectedCourse = fixtures.courses.find((course) => course.course_id === selectedCourseId) || defaultCourse;
      state.currentCourseId = selectedCourse.course_id;
      state.currentCourseName = selectedCourse.course_name;

      return {
        lecture_id: state.activeLectureId,
        resumed_today: false,
        session_status: "started_new",
        windows_mode: false,
        camera_active: true,
      };
    }
    if (method === "POST" && pathname === "/lecture/end") {
      return { ended: true };
    }
    if (method === "POST" && pathname.startsWith("/lecture/force-close/")) {
      return { force_closed: true };
    }
    if (method === "GET" && /^\/lecture\/\d+\/live$/.test(pathname)) {
      return clone(fixtures.live_snapshot);
    }
    if (method === "GET" && /^\/lecture\/\d+$/.test(pathname)) {
      const detail = clone(fixtures.lecture_detail);
      detail.course_id = state.currentCourseId;
      detail.course_name = state.currentCourseName;
      return detail;
    }

    if (method === "GET" && /^\/attendance\/list\/\d+$/.test(pathname)) {
      return clone(fixtures.present_list);
    }
    if (method === "POST" && pathname === "/attendance/override") {
      return { updated: true };
    }

    return {
      __status: 404,
      detail: `Mock not found for ${method} ${pathname}`,
    };
  };

  window.fetch = async (input, init = {}) => {
    const method = (
      init.method ||
      (typeof input !== "string" && input.method) ||
      "GET"
    ).toUpperCase();
    const rawUrl = typeof input === "string" ? input : input.url;
    const parsed = new URL(rawUrl, "http://localhost:8000");

    const routed = route(method, parsed.pathname, parsed.search, init.body || "");

    if (routed && routed.__status) {
      return jsonResponse(routed.__status, { detail: routed.detail });
    }
    return jsonResponse(200, routed);
  };
})();
""".replace("__FIXTURES__", _MOCK_FIXTURES_JSON)


def _headless_enabled() -> bool:
    raw_value = os.getenv("SELENIUM_HEADLESS", "1").strip().lower()
    return raw_value not in {"0", "false", "no"}


def _build_chrome_driver(headless: bool) -> webdriver.Chrome:
    options = ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1440,960")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    return webdriver.Chrome(options=options)


def _build_edge_driver(headless: bool) -> webdriver.Edge:
    options = EdgeOptions()
    options.use_chromium = True
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1440,960")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    return webdriver.Edge(options=options)


def _build_driver() -> webdriver.Remote:
    preferred = os.getenv("SELENIUM_BROWSER", "auto").strip().lower()
    headless = _headless_enabled()
    attempts: list[tuple[str, Callable[[], webdriver.Remote]]] = []

    if preferred in {"auto", "chrome"}:
        attempts.append(("chrome", lambda: _build_chrome_driver(headless)))
    if preferred in {"auto", "edge"}:
        attempts.append(("edge", lambda: _build_edge_driver(headless)))

    if not attempts:
        raise RuntimeError(
            "Unsupported SELENIUM_BROWSER value. Use one of: auto, chrome, edge."
        )

    errors: list[str] = []
    for browser_name, starter in attempts:
        try:
            return starter()
        except WebDriverException as exc:
            errors.append(f"{browser_name}: {exc.msg}")
        except Exception as exc:  # pragma: no cover
            errors.append(f"{browser_name}: {exc}")

    joined_errors = "\n".join(errors)
    raise RuntimeError(
        "Unable to start a Selenium browser driver. "
        "Install Chrome or Edge and ensure Selenium Manager can resolve the driver.\n"
        f"Attempts:\n{joined_errors}"
    )


@pytest.fixture(scope="session")
def page_url() -> Callable[[str], str]:
    def _builder(page_name: str) -> str:
        page_path = UI_DIR / page_name
        if not page_path.exists():
            raise FileNotFoundError(f"UI page not found: {page_path}")
        return page_path.resolve().as_uri()

    return _builder


@pytest.fixture()
def driver() -> webdriver.Remote:
    browser = _build_driver()
    browser.set_page_load_timeout(20)
    browser.set_window_size(1440, 960)

    try:
        browser.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": MOCK_FETCH_SCRIPT},
        )
    except Exception:
        # Chrome/Edge should support CDP. If they do not, tests still run
        # and assertions focus on static UI behavior.
        pass

    yield browser
    browser.quit()


@pytest.fixture()
def wait(driver: webdriver.Remote) -> WebDriverWait:
    timeout = int(os.getenv("SELENIUM_WAIT_SECONDS", "12"))
    return WebDriverWait(driver, timeout)


@pytest.fixture()
def set_auth(driver: webdriver.Remote, page_url: Callable[[str], str]) -> Callable[..., None]:
    def _set_auth(role: str, user_id: str, user_name: str, **extra_storage: Any) -> None:
        driver.get(page_url("login.html"))
        storage_data = {
            "role": role,
            "user_id": user_id,
            "user_name": user_name,
            **extra_storage,
        }
        for key, value in storage_data.items():
            driver.execute_script(
                "window.localStorage.setItem(arguments[0], arguments[1]);",
                key,
                str(value),
            )

    return _set_auth


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Any:
    outcome = yield
    report = outcome.get_result()

    if report.when != "call" or report.passed:
        return

    browser = item.funcargs.get("driver")
    if browser is None:
        return

    html_plugin = item.config.pluginmanager.getplugin("html")
    if html_plugin is None:
        return

    extras = getattr(report, "extras", [])
    screenshot_bytes = browser.get_screenshot_as_png()
    screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
    extras.append(html_plugin.extras.png(screenshot_b64, "failure-screenshot"))
    report.extras = extras
