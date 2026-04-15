import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

pytestmark = pytest.mark.selenium


def test_student_dashboard_overview_and_history(driver, wait, set_auth, page_url):
    set_auth("student", "202411052", "Asha Patel")
    driver.get(page_url("student.html"))

    wait.until(EC.visibility_of_element_located((By.ID, "stats-grid")))
    wait.until(lambda d: "Overall Attendance" in d.page_source)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#subject-list .progress-row")))

    driver.find_element(
        By.XPATH,
        "//button[contains(@class,'nav-item') and contains(.,'History')]",
    ).click()

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#history-body tr")))
    assert "Database Management Systems" in driver.find_element(By.ID, "history-body").text


def test_teacher_dashboard_session_control_flow(driver, wait, set_auth, page_url):
    set_auth("teacher", "T001", "Dr. Meera Iyer")
    driver.get(page_url("teacher.html"))

    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#course-list-body tr.course-row")))

    driver.find_element(
        By.XPATH,
        "//button[contains(@class,'nav-item') and contains(.,'Session Control')]",
    ).click()

    start_button = wait.until(EC.element_to_be_clickable((By.ID, "start-btn")))
    start_button.click()

    wait.until(lambda d: d.find_element(By.ID, "end-btn").is_displayed())
    wait.until(lambda d: d.find_element(By.ID, "stat-present").text.strip() != "")
    assert "Asha Patel" in driver.find_element(By.ID, "present-body").text


def test_admin_dashboard_data_tab_and_audit_log(driver, wait, set_auth, page_url):
    set_auth("admin", "admin", "Administrator")
    driver.get(page_url("admin.html"))

    wait.until(EC.visibility_of_element_located((By.ID, "admin-stats")))
    wait.until(lambda d: "Total Students" in d.page_source)

    driver.find_element(
        By.XPATH,
        "//button[contains(@class,'nav-item') and contains(.,'Data Management')]",
    ).click()
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#students-body tr")))

    driver.find_element(
        By.XPATH,
        "//button[contains(@class,'tab-pill') and normalize-space()='Teachers']",
    ).click()
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#teachers-body tr")))

    driver.find_element(
        By.XPATH,
        "//button[contains(@class,'nav-item') and contains(.,'Audit Log')]",
    ).click()
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#audit-body tr")))

    assert "attendance_marked" in driver.find_element(By.ID, "audit-body").text


def test_classroom_dashboard_start_from_upcoming_lecture(driver, wait, set_auth, page_url):
    set_auth(
        "classroom",
        "CR-2113",
        "CR-2113",
        classroom_id="CR-2113",
        building="Main Block",
    )
    driver.get(page_url("classroom.html"))

    lecture_card = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "#upcoming-list .lecture-card"))
    )
    lecture_card.click()

    wait.until(EC.visibility_of_element_located((By.ID, "active-section")))
    wait.until(
        EC.text_to_be_present_in_element((By.ID, "active-lecture-badge"), "Session #")
    )
    wait.until(lambda d: d.find_element(By.ID, "stat-present").text.strip() != "")

    assert "Asha Patel" in driver.find_element(By.ID, "present-body").text
