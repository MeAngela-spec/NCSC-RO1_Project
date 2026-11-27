'use strict';
(async () => {
  const workspace=document.getElementById('printWorkspace');
  const control=document.getElementById('openPrint');
  const count=document.getElementById('printCount');
  const params=new URLSearchParams(location.search);
  const ids=(params.get('ids')||'').split(',').filter(Boolean);
  const mode=params.get('mode')||'combined';
  const shared=mode==='combined'&&ids.length>1;
  const edit=document.createElement('button');edit.className='btn';edit.textContent='Edit slip details';edit.hidden=true;control.after(edit);
  let ready=false, csrf='', draft=null;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fields=[['subject','Document subject',500],['from','From',120],['to','Assigned / routed to',200],['date','Date',80],['time','Time',80],['note','Routing notes / actions',3000],['sign','Signature / initials',120],['received','Received by',200]];
  async function request(path,body) {
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});
    const result=await response.json();if(!response.ok)throw Error(result.error||'The slip could not be prepared.');return result;
  }
  const openPrint=()=>{if(ready){window.focus();window.print();}};
  control.onclick=openPrint;
  window.addEventListener('afterprint',()=>{control.textContent='Print again';count.textContent=count.dataset.readyText+' · Print dialog closed';});
  function editor() {
    ready=false;control.hidden=true;edit.hidden=true;
    document.querySelector('.printing-header strong').textContent='Edit shared routing slip';
    count.textContent=ids.length+' selected documents · Print-only changes';
    workspace.innerHTML='<section class="shared-slip-editor"><div class="shared-slip-heading"><h1>Review shared slip details</h1><p>Changes below apply only to this printout. Saved records, reference numbers and the official NCSC template stay intact.</p></div><form id="sharedSlipForm" class="stack"><label>Slip title / subject<input name="sharedSubject" required maxlength="200" value="'+esc(draft.subject)+'"></label>'+draft.rows.map((row,index)=>
      '<fieldset class="slip-row-fields"><legend>Document '+(index+1)+' · '+esc(row.reference)+'</legend><div class="grid">'+fields.map(([key,label,limit])=>'<label '+(['subject','note'].includes(key)?'class="full"':'')+'>'+label+(['subject','note'].includes(key)?'<textarea name="row'+index+'_'+key+'" maxlength="'+limit+'" '+(key==='subject'?'required':'')+'>'+esc(row[key])+'</textarea>':'<input name="row'+index+'_'+key+'" maxlength="'+limit+'" value="'+esc(row[key])+'" '+(key==='date'?'placeholder="YYYY-MM-DD or original date"':key==='time'?'placeholder="e.g. 09:00 AM"':'')+'>')+'</label>').join('')+'</div></fieldset>').join('')+'<div id="slipError" class="error" role="alert" hidden></div><div class="shared-slip-actions"><span>References are included automatically in each printed row.</span><button class="btn primary" type="submit">Print shared slip</button></div></form></section>';
    document.getElementById('sharedSlipForm').onsubmit=async e=>{
      e.preventDefault();const submit=e.submitter;submit.disabled=true;submit.textContent='Preparing printout…';document.getElementById('slipError').hidden=true;
      draft={subject:e.target.elements.sharedSubject.value,rows:draft.rows.map((row,index)=>({id:row.id,version:row.version,reference:row.reference,...Object.fromEntries(fields.map(([key])=>[key,e.target.elements['row'+index+'_'+key].value]))}))};
      try {await prepare();}catch(error){const el=document.getElementById('slipError');if(el){el.hidden=false;el.textContent=error.message;submit.disabled=false;submit.textContent='Print shared slip';}else failure(error);}
    };
  }
  edit.onclick=editor;
  async function prepare() {
    const payload={ids,mode};
    if(shared)payload.draft={subject:draft.subject,rows:draft.rows.map(({reference,...row})=>row)};
    const job=await request('/api/print-job',payload);
    if(!job.pages?.length)throw Error('No printable pages were generated.');
    const pages=document.createElement('div');pages.className='print-pages';
    const loads=[];
    for(const page of job.pages){
      const sheet=document.createElement('section');sheet.className='print-sheet';sheet.style.setProperty('--sheet-width',page.width_mm+'mm');sheet.style.setProperty('--sheet-height',page.height_mm+'mm');
      const image=document.createElement('img');image.alt='NCSC routing slip · Page '+(page.index+1);image.loading='eager';
      loads.push(new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(Error('A print page could not load. Review document access and try again.'));}));
      image.src=page.url;sheet.append(image);pages.append(sheet);
    }
    await Promise.all(loads);await Promise.all([...pages.querySelectorAll('img')].map(img=>img.decode()));
    let style=document.getElementById('printPageSize');if(!style){style=document.createElement('style');style.id='printPageSize';document.head.append(style);}
    style.textContent='@page{size:'+job.pages[0].width_mm+'mm '+job.pages[0].height_mm+'mm;margin:0}';
    workspace.replaceChildren(pages);
    count.dataset.readyText=ids.length+' document'+(ids.length===1?'':'s')+' · '+job.pages.length+' page'+(job.pages.length===1?'':'s')+' · Original NCSC template';count.textContent=count.dataset.readyText;
    document.querySelector('.printing-header strong').textContent=shared?'Print shared routing slip':'Print routing slip';
    ready=true;control.hidden=false;edit.hidden=!shared;
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));openPrint();
  }
  function failure(error){
    workspace.innerHTML='<div class="print-loading"><h1>Printing needs attention</h1><p class="error" role="alert">'+esc(error.message)+'</p><button class="btn primary" id="retryPrint">Try again</button></div>';
    document.getElementById('retryPrint').onclick=()=>location.reload();
  }
  try {
    if(!ids.length||ids.length>100)throw Error('Select between 1 and 100 documents to print.');
    const me=await(await fetch('/api/me')).json();if(!me.user)throw Error('Your session has expired. Return to the register and log in again.');csrf=me.csrf;
    if(shared){draft=await request('/api/slip-draft',{ids});editor();}else await prepare();
  }catch(error){failure(error);}
})();
