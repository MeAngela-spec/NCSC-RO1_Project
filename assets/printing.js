'use strict';
(async () => {
  const workspace=document.getElementById('printWorkspace');
  const control=document.getElementById('openPrint');
  const count=document.getElementById('printCount');
  const params=new URLSearchParams(location.search);
  let ready=false;
  const openPrint=()=>{
    if (!ready) return;
    window.focus();
    window.print();
  };
  control.onclick=openPrint;
  window.addEventListener('afterprint',()=>{
    control.textContent='Print again';
    count.textContent=count.dataset.readyText+' · Print dialog closed';
  });
  try {
    const ids=(params.get('ids')||'').split(',').filter(Boolean);
    const mode=params.get('mode')||'combined';
    if (!ids.length || ids.length>100) throw Error('Select between 1 and 100 documents to print.');
    document.querySelector('.printing-header strong').textContent=mode==='combined'?'Print selected document rows':'Print routing slip';
    const me=await(await fetch('/api/me')).json();
    if (!me.user) throw Error('Your session has expired. Return to the register and log in again.');
    const response=await fetch('/api/print-job',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':me.csrf},body:JSON.stringify({ids,mode})});
    if (!response.ok) throw Error((await response.json()).error || 'The routing slips could not be prepared.');
    const job=await response.json();
    if (!job.pages?.length) throw Error('No printable pages were generated.');
    const size=job.pages[0];
    const style=document.createElement('style');
    style.textContent='@page{size:'+size.width_mm+'mm '+size.height_mm+'mm;margin:0}';
    document.head.append(style);
    const pages=document.createElement('div');pages.className='print-pages';
    const loads=[];
    for (const page of job.pages) {
      const sheet=document.createElement('section');sheet.className='print-sheet';
      sheet.style.setProperty('--sheet-width',page.width_mm+'mm');sheet.style.setProperty('--sheet-height',page.height_mm+'mm');
      const image=document.createElement('img');image.alt='NCSC routing slip · Page '+(page.index+1);image.loading='eager';
      loads.push(new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(Error('A print page could not load. Return to the register and try Print slip again.'));}));
      image.src=page.url;sheet.append(image);pages.append(sheet);
    }
    workspace.replaceChildren(pages);
    await Promise.all(loads);
    await Promise.all([...pages.querySelectorAll('img')].map(img=>img.decode()));
    count.dataset.readyText=ids.length+' document'+(ids.length===1?'':'s')+' · '+job.pages.length+' page'+(job.pages.length===1?'':'s')+' · Original NCSC template';
    count.textContent=count.dataset.readyText;
    ready=true;control.hidden=false;
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    openPrint();
  } catch(error) {
    workspace.innerHTML='';
    const panel=document.createElement('div');panel.className='print-loading';
    const title=document.createElement('h1');title.textContent='Printing needs attention';
    const message=document.createElement('p');message.className='error';message.setAttribute('role','alert');message.textContent=error.message;
    const retry=document.createElement('button');retry.className='btn primary';retry.textContent='Try again';retry.onclick=()=>location.reload();
    panel.append(title,message,retry);workspace.append(panel);
  }
})();
