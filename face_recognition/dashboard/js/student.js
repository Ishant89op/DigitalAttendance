const user=JSON.parse(localStorage.getItem("user"))

if(!user){
window.location="login.html"
}

async function loadStudentAnalytics(){

const res=await fetch(
`http://127.0.0.1:8000/analytics/student/${user.id}`
)

const data=await res.json()

document.getElementById("percentage").innerText =
data.attendance_percentage+" %"

document.getElementById("total_classes").innerText =
data.total_classes

document.getElementById("present").innerText =
data.present

if(data.attendance_percentage < 75){

document.getElementById("warning").innerText =
"⚠ Attendance below 75%"

}

createStudentChart(data)

}

loadStudentAnalytics()