async function loadClassAnalytics(){

const course_id=document.getElementById("course_id").value

const res=await fetch(
`http://127.0.0.1:8000/analytics/class/${course_id}`
)

const data=await res.json()

document.getElementById("present_today").innerText=data.present_today
document.getElementById("absent_today").innerText=data.absent_today

createTeacherChart(data)

}


async function markAttendance(){

const student_id=document.getElementById("student_id").value
const course_id=document.getElementById("course_id").value
const status=document.getElementById("status").value

const res=await fetch("http://127.0.0.1:8000/attendance/mark",{

method:"POST",

headers:{
"Content-Type":"application/json"
},

body:JSON.stringify({
student_id,
course_id,
status
})

})

const data=await res.json()

alert(data.message)

}