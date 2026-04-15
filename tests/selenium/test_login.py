import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

pytestmark = pytest.mark.selenium


def test_login_role_switch_and_validation(driver, wait, page_url):
    driver.get(page_url("login.html"))
    wait.until(EC.visibility_of_element_located((By.ID, "user-id")))

    tabs = driver.find_elements(By.CSS_SELECTOR, ".tab")
    assert len(tabs) == 4

    driver.execute_script("setRole('teacher', document.querySelectorAll('.tab')[1]);")
    wait.until(
        lambda d: d.find_element(By.ID, "id-label").get_attribute("textContent").strip()
        == "Teacher ID"
    )

    driver.execute_script("setRole('classroom', document.querySelectorAll('.tab')[3]);")
    wait.until(
        lambda d: d.find_element(By.ID, "password-label").get_attribute("textContent").strip()
        == "Room Password"
    )

    driver.find_element(By.ID, "login-btn").click()
    wait.until(EC.text_to_be_present_in_element((By.ID, "error"), "Please enter your ID."))

    driver.find_element(By.ID, "user-id").send_keys("202411052")
    driver.find_element(By.ID, "login-btn").click()
    wait.until(EC.text_to_be_present_in_element((By.ID, "error"), "Please enter your password."))


def test_student_login_redirects_to_student_dashboard(driver, wait, page_url):
    driver.get(page_url("login.html"))
    wait.until(EC.visibility_of_element_located((By.ID, "user-id")))

    user_id_input = driver.find_element(By.ID, "user-id")
    user_id_input.clear()
    user_id_input.send_keys("202411052")
    driver.find_element(By.ID, "password").send_keys("202411052")

    driver.find_element(By.ID, "login-btn").click()

    wait.until(lambda d: "student.html" in d.current_url)
    role = driver.execute_script("return window.localStorage.getItem('role');")
    user_id = driver.execute_script("return window.localStorage.getItem('user_id');")

    assert role == "student"
    assert user_id == "202411052"


def test_protected_page_redirects_to_login_when_not_authenticated(driver, wait, page_url):
    driver.get(page_url("student.html"))
    wait.until(lambda d: "login.html" in d.current_url)
