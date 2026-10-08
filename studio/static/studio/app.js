'use strict';
document.querySelectorAll('[data-confirm]').forEach(button=>button.addEventListener('click',event=>{if(!window.confirm(button.dataset.confirm))event.preventDefault();}));
document.querySelectorAll('[data-back]').forEach(button=>button.addEventListener('click',()=>window.history.back()));
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{const calendar=document.getElementById('calendar-entries');if(calendar)calendar.className=button.dataset.view==='grid'?'calendar-grid':'calendar-list';}));
// Retain queue filters after a GET navigation.
const params=new URLSearchParams(window.location.search);
document.querySelectorAll('.filterbar select').forEach(select=>{if(params.has(select.name))select.value=params.get(select.name);});
