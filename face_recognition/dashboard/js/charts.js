function createStudentChart(data){

const ctx=document.getElementById("attendanceChart")

new Chart(ctx,{

type:"pie",

data:{

labels:["Present","Absent"],

datasets:[{

data:[data.present,data.total_classes-data.present],

backgroundColor:["green","red"]

}]

}

})

}


function createTeacherChart(data){

const ctx=document.getElementById("classChart")

new Chart(ctx,{

type:"doughnut",

data:{

labels:["Present","Absent"],

datasets:[{

data:[data.present_today,data.absent_today],

backgroundColor:["green","red"]

}]

}

})

}