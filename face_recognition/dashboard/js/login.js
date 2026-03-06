async function login(){

const id=document.getElementById("user_id").value
const password=document.getElementById("password").value

if(!id || !password){
document.getElementById("error").innerText="Enter ID and password"
return
}

const response=await fetch("http://127.0.0.1:8000/login",{

method:"POST",

headers:{
"Content-Type":"application/json"
},

body:JSON.stringify({
id:id,
password:password
})

})

const data=await response.json()

if(data.error){
document.getElementById("error").innerText=data.error
return
}

localStorage.setItem("user",JSON.stringify(data))

if(data.role==="student"){
window.location="student_dashboard.html"
}

if(data.role==="teacher"){
window.location="teacher_dashboard.html"
}

}