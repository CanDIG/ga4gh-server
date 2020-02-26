"use strict";function groupBy(a,b){return a.reduce(function(a,c){var d=c[b];return a[d]||(a[d]=0),a[d]+=1,delete a.undefined,a},{})}function makeRequest(a,b){return new Promise(function(c,d){function e(h){b.pageToken=h;var i=new XMLHttpRequest;i.open("POST",prepend_path+a,!0),i.setRequestHeader("Content-Type","application/json"),i.setRequestHeader("Accept","application/json"),i.onload=function(){if(200==i.status){let a=JSON.parse(i.response);if(null==a.results.nextPageToken&&0==g.length&&c(i.response),null==f){let b=Object.keys(a.results);for(let a=0;a<b.length;a++)"nextPageToken"!=b[a]&&"total"!=b[a]&&(f=b[a])}a.results.nextPageToken?(g.push.apply(g,a.results[f]),e(a.results.nextPageToken)):(g.push.apply(g,a.results[f]),a.results[f]=g,c(JSON.stringify(a)))}else 403==i.status||401==i.status?alertBuilder("Your session might have expired. Click <a href='/'>here</a> to restore your session. If problems persist, please contact your system administrators for assistance."):500==i.status&&alertBuilder("Unexpected errors occurred. Click <a href='/'>here</a> to refresh your session. If problems persist, please contact your system administrators for assistance."),d(Error(i.response));stopLoading()},i.onerror=function(){d(Error(i.response))},i.send(JSON.stringify(b))}let f,g=[];return e("")})}$(".alert").on("close.bs.alert",function(a){a.preventDefault();var b=document.getElementById("warningMsg");b.innerHTML="<a href=\"#\" class=\"close\" data-dismiss=\"alert\" aria-label=\"close\">\xD7</a>",b.style.display="none"});function alertCloser(){var a=document.getElementById("warningMsg");a.innerHTML="<a href=\"#\" class=\"close\" data-dismiss=\"alert\" aria-label=\"close\">\xD7</a>",a.style.display="none"}function alertBuilder(a){let b=document.getElementById("warningMsg");b.style.display="block",b.innerHTML="<a href=\"#\" class=\"close\" data-dismiss=\"alert\" aria-label=\"close\">\xD7</a>",b.innerHTML+=a}function startLoading(){document.getElementById("initial_loader").style.display="block"}function stopLoading(){setTimeout(function(){document.getElementById("initial_loader").style.display="None"},0)}function getCookie(a){let b=document.cookie.split("; ");for(let c=0;c<b.length;c++)if(b[c].split("=")[0]==a)return b[c].split("=")[1];return null}function setCookie(a,b){document.cookie=a+"="+b}function searchRequest(a,b,c,d={},e){return complexRequestHelper(a,b,c,d,!1,e)}function countRequest(a,b,c,d={}){return complexRequestHelper(a,b,c,d,!0,a)}function complexRequestHelper(a,b,c,d={},e=!0,f){return new Promise(function(g,h){let i="/count",j={dataset_id:c,logic:{id:"A"},components:[{id:"A"}],results:[{table:f,fields:b}]};j.components[0][a]={},0!=Object.keys(d).length&&(j.components[0][a].filters=[],j.components[0][a].filters.push(d)),e||(i="/search"),makeRequest(i,j).then(function(a){"/count"==i?g(a):g(JSON.parse(a).results[f])}),function(a){h(a(response))}})}function singleLayerDrawer(a,b,c,d){if(d==null)noPermissionMessage(a);else{var e=Object.keys(d),f=Object.values(d),g=highChartSeriesObjectMaker(e,f);Highcharts.chart(a,{chart:{type:b,style:{fontFamily:"Roboto"}},credits:{enabled:!1},exporting:{enabled:!1},title:{text:c},xAxis:{type:"category"},legend:{enabled:!1},plotOptions:{series:{borderWidth:0,dataLabels:{enabled:!0}}},series:[{name:"count",colorByPoint:!0,data:g}]})}}function noPermissionMessage(a){document.getElementById(a).innerHTML="<p class='noPermission'>No data available</p>"}function noPermissionMessageMultiple(a){for(let b=0;b<a.length;b++)document.getElementById(a[b]).innerHTML="<p class='noPermission'>No data available</p>"}function highChartSeriesObjectMaker(a,b){for(var c={},d=[],e=0;e<a.length;e++)c={},c.name=a[e],c.y=b[e],d.push(c);return d}function changeClass(a){document.getElementById(a).className="active"}