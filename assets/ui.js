/* Offline workspace controls. Native fields retain values, validation and form submission.
   Login markup, styles and controls are intentionally excluded. */
(() => {
  'use strict';
  const controls = new Set();
  const enhanced = new WeakMap();
  let active = null, sequence = 0, scheduled = false;
  const icon = name => {
    const paths = {chevron:'<path d="m6 9 6 6 6-6"/>',calendar:'<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4M17 3v4M3 11h18"/>',
      check:'<path d="m5 12 4 4L19 6"/>',left:'<path d="m15 6-6 6 6 6"/>',right:'<path d="m9 6 6 6-6 6"/>',upload:'<path d="M12 16V3m-4 4 4-4 4 4M4 16v4h16v-4"/>'};
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+paths[name]+'</svg>';
  };
  function button(label, className) {
    const node=document.createElement('button');node.type='button';node.className=className;
    if(label)node.setAttribute('aria-label',label);
    return node;
  }
  function labelFor(field) {
    if(field.getAttribute('aria-label'))return field.getAttribute('aria-label');
    const label=field.labels?.[0]||field.closest('label');
    return label ? [...label.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).filter(Boolean).join(' ')||label.querySelector('.field-label')?.textContent||'Choose an option' : field.name||'Choose an option';
  }
  function text(node,value) {if(node.textContent!==value)node.textContent=value;}
  function updateValidity(control,show=false) {
    if(control.field.validity.valid){control.wrap.classList.remove('ui-control-invalid');control.trigger.removeAttribute('aria-invalid');control.error?.remove();control.error=null;}
    else if(show){
      control.wrap.classList.add('ui-control-invalid');control.trigger.setAttribute('aria-invalid','true');
      if(!control.error){control.error=document.createElement('small');control.error.className='ui-validation';control.error.setAttribute('role','alert');control.wrap.append(control.error);}
      text(control.error,control.field.validationMessage||'Choose a value for this field.');
    }
  }
  function wrapControl(field,type) {
    const wrap=document.createElement('span');wrap.className='ui-control ui-'+type;
    if(field.hasAttribute('data-assignment-department'))wrap.classList.add('ui-assignment-department');
    if(field.name==='assignedStaff')wrap.classList.add('ui-assignment-staff');
    field.before(wrap);wrap.append(field);field.classList.add('ui-native');field.tabIndex=-1;field.setAttribute('aria-hidden','true');
    const trigger=button(labelFor(field),'ui-control-trigger');
    trigger.setAttribute('aria-haspopup',type==='select'?'listbox':'dialog');trigger.setAttribute('aria-expanded','false');
    const caption=document.createElement('span');caption.className='ui-control-caption';
    const symbol=document.createElement('span');symbol.className='ui-control-symbol';symbol.innerHTML=icon(type==='select'?'chevron':'calendar');
    trigger.append(caption,symbol);wrap.append(trigger);
    const control={field,wrap,trigger,caption,type,error:null};controls.add(control);enhanced.set(field,control);
    field.addEventListener('invalid',e=>{e.preventDefault();updateValidity(control,true);trigger.focus();});
    field.addEventListener('change',()=>sync(control));field.addEventListener('input',()=>sync(control));
    return control;
  }
  function sync(control) {
    const {field,trigger,wrap,caption,type}=control;
    if(type==='file'){
      const files=[...field.files];text(caption,files.length===1?files[0].name:files.length?files.length+' files selected':'No file selected');
      wrap.classList.toggle('ui-file-selected',files.length>0);wrap.classList.toggle('ui-disabled',field.disabled);return;
    }
    if(trigger.disabled!==field.disabled)trigger.disabled=field.disabled;
    if(wrap.hidden!==field.hidden)wrap.hidden=field.hidden;
    if((field.disabled||field.hidden)&&active?.control===control)close(false);
    trigger.setAttribute('aria-required',String(field.required));trigger.setAttribute('aria-label',labelFor(field));
    text(caption,type==='select'?(field.selectedOptions[0]?.label||'Choose an option'):dateLabel(field.value));
    wrap.classList.toggle('ui-placeholder',!field.value);updateValidity(control);
  }
  function close(restore=true) {
    if(!active)return;
    const previous=active;active=null;
    previous.control.trigger.setAttribute('aria-expanded','false');previous.control.wrap.classList.remove('ui-open');
    if(typeof previous.node.hidePopover==='function'){try{previous.node.hidePopover();}catch{/* Already closed or the browser uses the fallback. */}}
    previous.node.remove();
    if(restore&&previous.control.trigger.isConnected)previous.control.trigger.focus({preventScroll:true});
  }
  function position() {
    if(!active)return;
    const {node,control}=active,r=control.trigger.getBoundingClientRect(),vw=document.documentElement.clientWidth,vh=window.innerHeight;
    const width=Math.min(control.type==='date'?320:Math.max(r.width,260),vw-24);
    const above=r.top-16,below=vh-r.bottom-16,up=below<(control.type==='date'?380:260)&&above>below;
    node.style.width=width+'px';node.style.left=Math.max(12,Math.min(r.left,vw-width-12))+'px';
    node.style.maxHeight=Math.max(140,Math.min(control.type==='date'?400:380,up?above:below))+'px';
    node.style.top=up?'auto':(r.bottom+8)+'px';node.style.bottom=up?(vh-r.top+8)+'px':'auto';
  }
  function popup(control) {
    close(false);
    const node=document.createElement('div');node.id='ncsc-picker-'+(++sequence);node.className='ui-popover ui-'+control.type+'-popover';
    node.setAttribute('popover','manual');(control.field.closest('dialog')||document.body).append(node);
    control.trigger.setAttribute('aria-controls',node.id);control.trigger.setAttribute('aria-expanded','true');control.wrap.classList.add('ui-open');
    active={control,node};
    if(typeof node.showPopover==='function'){try{node.showPopover();}catch{node.removeAttribute('popover');}}
    else node.removeAttribute('popover');
    position();return node;
  }
  function commit(control,value) {
    const id=control.field.id;control.field.value=value;
    control.field.dispatchEvent(new Event('input',{bubbles:true}));control.field.dispatchEvent(new Event('change',{bubbles:true}));
    close(false);sync(control);
    queueMicrotask(()=>{
      if(!control.field.isConnected)refresh();
      const next=control.field.isConnected?control:enhanced.get(id&&document.getElementById(id));
      if(next?.trigger.isConnected)next.trigger.focus({preventScroll:true});
    });
  }
  function selectControl(field) {
    const control=wrapControl(field,'select');
    function open() {
      if(field.disabled)return;
      if(active?.control===control){close();return;}
      const node=popup(control),list=document.createElement('div');list.id=node.id+'-list';list.className='ui-options';list.setAttribute('role','listbox');list.setAttribute('aria-label',labelFor(field));list.tabIndex=0;
      let visible=[],index=0,query='',search=null,typeahead='',lastTyped=0;
      if(field.options.length>7){
        const box=document.createElement('div');box.className='ui-picker-search';search=document.createElement('input');search.type='search';search.placeholder='Search choices…';search.setAttribute('aria-label','Search '+labelFor(field));box.append(search);node.append(box);
        search.addEventListener('input',()=>{query=search.value.toLocaleLowerCase();render();});
        search.addEventListener('keydown',e=>{if(e.key==='ArrowDown'){e.preventDefault();list.focus({preventScroll:true});highlight(0);}else if(e.key==='Enter'){e.preventDefault();if(visible[index])choose(visible[index]);}});
      }
      node.append(list);
      function highlight(next) {
        if(!visible.length)return;
        index=Math.max(0,Math.min(next,visible.length-1));
        list.querySelectorAll('[role=option]').forEach((option,i)=>option.classList.toggle('ui-option-active',i===index));
        const option=list.querySelectorAll('[role=option]')[index];list.setAttribute('aria-activedescendant',option.id);
        if(typeof option.scrollIntoView==='function')option.scrollIntoView({block:'nearest'});
      }
      function choose(option){if(!option.disabled)commit(control,option.value);}
      function render() {
        list.replaceChildren();visible=[...field.options].filter(o=>!o.hidden&&!o.disabled&&!o.parentElement.disabled&&o.label.toLocaleLowerCase().includes(query));
        let group='';
        visible.forEach((option,i)=>{
          const name=option.parentElement.tagName==='OPTGROUP'?option.parentElement.label:'';
          if(name&&group!==name){const heading=document.createElement('div');heading.className='ui-option-group';text(heading,name);list.append(heading);}group=name;
          const row=button('', 'ui-option');row.id=node.id+'-option-'+i;row.tabIndex=-1;row.setAttribute('role','option');row.setAttribute('aria-selected',String(option.selected));
          const label=document.createElement('span');text(label,option.label);const mark=document.createElement('span');mark.className='ui-option-check';mark.innerHTML=option.selected?icon('check'):'';row.append(label,mark);row.addEventListener('click',()=>choose(option));list.append(row);
        });
        if(!visible.length){const empty=document.createElement('p');empty.className='ui-picker-empty';empty.setAttribute('role','status');text(empty,'No matching choices');list.append(empty);list.removeAttribute('aria-activedescendant');}
        highlight(Math.max(0,visible.findIndex(o=>o.selected)));position();
      }
      list.addEventListener('keydown',e=>{
        if(['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(e.key))e.preventDefault();
        if(e.key==='ArrowDown')highlight(index+1);else if(e.key==='ArrowUp')highlight(index-1);
        else if(e.key==='Home')highlight(0);else if(e.key==='End')highlight(visible.length-1);
        else if(['Enter',' '].includes(e.key)&&visible[index])choose(visible[index]);
        else if(e.key.length===1&&!e.ctrlKey&&!e.metaKey){const stamp=Date.now();typeahead=(stamp-lastTyped>650?'':typeahead)+e.key.toLocaleLowerCase();lastTyped=stamp;const match=visible.findIndex(o=>o.label.toLocaleLowerCase().startsWith(typeahead));if(match>=0)highlight(match);}
      });
      render();(search||list).focus({preventScroll:true});
    }
    control.trigger.addEventListener('click',e=>{e.preventDefault();open();});
    control.trigger.addEventListener('keydown',e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();open();}});
    sync(control);
  }
  function makeDate(year,month,day=1) {const date=new Date(0);date.setFullYear(year,month,day);date.setHours(12,0,0,0);return date;}
  function iso(date) {return String(date.getFullYear()).padStart(4,'0')+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0');}
  function dateLabel(value) {return value?new Intl.DateTimeFormat('en-PH',{day:'numeric',month:'short',year:'numeric'}).format(new Date(value+'T12:00:00')):'Choose date';}
  function dateControl(field) {
    const control=wrapControl(field,'date');
    function open() {
      if(field.disabled)return;
      if(active?.control===control){close();return;}
      const node=popup(control);node.setAttribute('role','dialog');node.setAttribute('aria-label','Choose '+labelFor(field));
      const today=new Date(),initial=field.value?new Date(field.value+'T12:00:00'):today;
      let year=initial.getFullYear(),month=initial.getMonth(),mode='days';
      const canChoose=value=>{
        if(field.min&&value<field.min||field.max&&value>field.max)return false;
        const step=Number(field.step)||1,base=field.min||field.defaultValue||'1970-01-01';
        return field.step==='any'||Math.abs((Date.parse(value)-Date.parse(base))/86400000)%step===0;
      };
      function moveMonth(delta){const next=makeDate(year,month+delta);if(next.getFullYear()<1||next.getFullYear()>9999)return;year=next.getFullYear();month=next.getMonth();render();}
      function render(focusValue) {
        node.replaceChildren();const head=document.createElement('div');head.className='ui-calendar-head';
        const previous=button(mode==='days'?'Previous month':'Previous year','ui-calendar-arrow'),next=button(mode==='days'?'Next month':'Next year','ui-calendar-arrow');previous.innerHTML=icon('left');next.innerHTML=icon('right');
        previous.disabled=year<=1&&(mode==='months'||month===0);next.disabled=year>=9999&&(mode==='months'||month===11);
        previous.onclick=()=>{if(mode==='days')moveMonth(-1);else {year--;render();}};next.onclick=()=>{if(mode==='days')moveMonth(1);else {year++;render();}};
        head.append(previous);
        if(mode==='days'){
          const period=button('Choose month and year','ui-calendar-period');text(period,new Intl.DateTimeFormat('en-PH',{month:'long',year:'numeric'}).format(makeDate(year,month)));period.onclick=()=>{mode='months';render();};head.append(period);
        }else {
          const input=document.createElement('input');input.type='number';input.min='1';input.max='9999';input.value=year;input.className='ui-calendar-year';input.setAttribute('aria-label','Calendar year');
          input.onchange=()=>{const value=Number(input.value);if(Number.isInteger(value)&&value>=1&&value<=9999){year=value;previous.disabled=year<=1;next.disabled=year>=9999;}else input.value=year;};head.append(input);
        }
        head.append(next);node.append(head);
        if(mode==='months'){
          const months=document.createElement('div');months.className='ui-calendar-months';
          for(let m=0;m<12;m++){const item=button('', 'ui-calendar-month');text(item,new Intl.DateTimeFormat('en-PH',{month:'short'}).format(makeDate(year,m)));item.setAttribute('aria-pressed',String(m===month));item.onclick=()=>{month=m;mode='days';render();};months.append(item);}node.append(months);
        }else {
          const weekdays=document.createElement('div');weekdays.className='ui-calendar-week';weekdays.setAttribute('aria-hidden','true');for(const day of ['Su','Mo','Tu','We','Th','Fr','Sa']){const item=document.createElement('span');text(item,day);weekdays.append(item);}node.append(weekdays);
          const days=document.createElement('div');days.className='ui-calendar-days';days.setAttribute('role','group');days.setAttribute('aria-label','Days in selected month');
          const start=makeDate(year,month,1-makeDate(year,month).getDay());
          for(let i=0;i<42;i++){
            const day=makeDate(start.getFullYear(),start.getMonth(),start.getDate()+i),value=iso(day),item=button(new Intl.DateTimeFormat('en-PH',{dateStyle:'full'}).format(day),'ui-calendar-day');text(item,String(day.getDate()));item.dataset.day=value;
            item.disabled=day.getFullYear()<1||day.getFullYear()>9999||!canChoose(value);item.setAttribute('aria-pressed',String(value===field.value));
            item.classList.toggle('ui-day-outside',day.getMonth()!==month);if(value===iso(today))item.setAttribute('aria-current','date');
            item.onclick=()=>commit(control,value);
            item.addEventListener('keydown',e=>{
              const delta={ArrowRight:1,ArrowLeft:-1,ArrowDown:7,ArrowUp:-7,Home:-day.getDay(),End:6-day.getDay()}[e.key];
              if(delta!==undefined){e.preventDefault();const target=makeDate(day.getFullYear(),day.getMonth(),day.getDate()+delta);if(target.getFullYear()<1||target.getFullYear()>9999)return;year=target.getFullYear();month=target.getMonth();render(iso(target));}
              else if(['PageUp','PageDown'].includes(e.key)){e.preventDefault();moveMonth(e.key==='PageUp'?-1:1);}
            });days.append(item);
          }node.append(days);
        }
        const footer=document.createElement('div');footer.className='ui-calendar-footer';
        const clear=button('', 'ui-calendar-text'),now=button('', 'ui-calendar-text');text(clear,'Clear');text(now,'Today');clear.onclick=()=>commit(control,'');now.disabled=!canChoose(iso(today));now.onclick=()=>commit(control,iso(today));footer.append(clear,now);node.append(footer);position();
        const focus=node.querySelector('[data-day="'+(focusValue||field.value||iso(today))+'"]:not(:disabled)')||node.querySelector('.ui-calendar-day:not(:disabled)')||node.querySelector('button:not(:disabled)');
        node.querySelectorAll('.ui-calendar-day').forEach(day=>day.tabIndex=day===focus?0:-1);focus?.focus({preventScroll:true});
      }
      render();
    }
    control.trigger.addEventListener('click',e=>{e.preventDefault();open();});
    control.trigger.addEventListener('keydown',e=>{if(e.key==='ArrowDown'){e.preventDefault();open();}});sync(control);
  }
  function fileControl(field) {
    const wrap=document.createElement('span');wrap.className='ui-file-control';field.before(wrap);wrap.append(field);field.classList.add('ui-file-native');
    const choose=document.createElement('span');choose.className='ui-file-choose';choose.innerHTML=icon('upload');const label=document.createElement('span');text(label,field.multiple?'Choose files':'Choose file');choose.append(label);
    const caption=document.createElement('span');caption.className='ui-file-caption';caption.setAttribute('aria-live','polite');wrap.append(choose,caption);
    const control={field,wrap,caption,type:'file'};controls.add(control);enhanced.set(field,control);field.addEventListener('change',()=>sync(control));sync(control);
  }
  function refresh() {
    scheduled=false;
    const workspace=Boolean(document.querySelector('.workspace')||document.body.classList.contains('printing-page'));
    document.body.toggleAttribute('data-workspace',workspace);
    for(const control of controls){if(!control.field.isConnected){if(active?.control===control)close(false);controls.delete(control);}else sync(control);}
    if(!workspace){close(false);return;}
    document.querySelectorAll('select:not([multiple]),input[type=date],input[type=file]:not([hidden])').forEach(field=>{
      if(enhanced.has(field)||field.closest('.login,.ui-popover'))return;
      if(field.tagName==='SELECT')selectControl(field);else if(field.type==='date')dateControl(field);else fileControl(field);
    });
  }
  const observer=new MutationObserver(records=>{
    if(records.every(r=>r.type==='attributes'&&!r.target.matches('select,option,optgroup,input')))return;
    if(!scheduled){scheduled=true;queueMicrotask(refresh);}
  });
  observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','required','hidden','selected','value','min','max','step']});
  document.addEventListener('pointerdown',e=>{if(active&&!active.node.contains(e.target)&&!active.control.wrap.contains(e.target))close(false);},true);
  document.addEventListener('keydown',e=>{
    if(!active)return;
    if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();}
    else if(e.key==='Tab'){
      if(active.control.type==='date'&&active.node.contains(e.target)){
        const stops=[...active.node.querySelectorAll('button:not(:disabled),input:not(:disabled)')].filter(node=>node.tabIndex>=0);
        if(e.shiftKey?e.target!==stops[0]:e.target!==stops.at(-1))return;
      }
      const trigger=active.control.trigger;close(false);trigger.focus({preventScroll:true});
    }
  },true);
  document.addEventListener('scroll',e=>{if(active&&!(e.target instanceof Node&&active.node.contains(e.target)))close(false);},true);
  window.addEventListener('resize',()=>close(false));window.addEventListener('beforeprint',()=>close(false));
  document.addEventListener('reset',()=>queueMicrotask(refresh));refresh();
})();
