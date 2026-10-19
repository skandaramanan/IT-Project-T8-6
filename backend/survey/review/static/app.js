'use strict';
const $ = (id) => document.getElementById(id);
let regions = [], queue = null, current = null, signedIn = false, busy = false, zoom = 1;
let pending = null, pendingUndo = null, lastSaved = null, scanReady = false, scanSerial = 0;
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) { const error=new Error(data.error?.message || 'Request failed. Your input is retained.');error.status=response.status;error.code=data.error?.code;throw error; }
  return data;
}
function message(text, error=false) { $('message').textContent=text; $('message').className=error?'error':''; }
function hasUnsavedCorrection() { return !!current && $('correction').value!==(current.field.value ?? ''); }
function setBusy(value) {
  busy=value;
  for (const control of document.querySelectorAll('button,select,input,textarea')) control.disabled=value;
  if (!value) {
    for (const control of document.querySelectorAll('[data-action]')) control.disabled=!signedIn || !scanReady || !current?.allowed_actions.includes(control.dataset.action);
    $('undo').disabled=!signedIn || !scanReady || !current?.undo_decision_id;
    $('exit').disabled=!signedIn;
    $('sync-now').disabled=!signedIn;
    $('correction').disabled=!signedIn || !scanReady || !current?.allowed_actions.includes('correct');
    if(hasUnsavedCorrection()) document.querySelector('[data-action="accept"]').disabled=true;
  }
  $('session-reminder').hidden=signedIn;
}
function showSync(data) {
  const labels={uploaded:'Uploaded (CI status separate)',waiting_to_upload:'Waiting to upload · saved locally',uploading:'Uploading · saved locally',upload_failed:'Upload failed; local changes retained'};
  $('sync').textContent=labels[data.state] || data.state;
  $('sync').title=data.error?.message || '';
}
async function refreshSync() { try {showSync(await api('/api/sync/status'));} catch(e) {$('sync').textContent='Backend unavailable; upload status unknown';} }
function fillBatches() {
  const entry=regions.find(r=>r.region===$('region').value);
  $('batch').replaceChildren(new Option('All supplied batches',''),...(entry?.batches || []).map(b=>new Option(b,b)));
}
function query() { return new URLSearchParams({region:$('region').value,batch:$('batch').value || ''}); }
async function refreshQueue(preferred=null, retainInput=false) {
  queue=await api('/api/queue?'+query());
  $('progress').textContent=`${queue.resolved} of ${queue.total} flagged items resolved · ${queue.unresolved} unresolved`;
  $('diagnostics').textContent=queue.diagnostics.map(d=>`${d.code}: ${d.message}`).join('\n');
  $('items').replaceChildren();
  for (const item of queue.items) {
    const button=document.createElement('button');
    button.textContent=`${item.label} · ${item.review_state}`;
    button.onclick=()=>{if(!busy) run(()=>openItem(item.id));};
    button.dataset.item=item.id;
    $('items').append(button);
  }
  const id=preferred || queue.items.find(i=>!i.resolved)?.id || queue.items[0]?.id;
  if (id) await openItem(id,retainInput); else { current=null; $('field').hidden=true; $('scan').hidden=true; }
  if (queue.complete) message('Batch complete: all supplied flagged items have supported decisions.');
}
async function openItem(id,retainInput=false) {
  current=await api('/api/review-items/'+id);
  message('');
  $('field').hidden=false;
  $('label').textContent=current.label;
  $('identity').textContent=current.record_id+' · '+current.review_state;
  $('value').textContent=current.field.value ?? 'No readable value';
  $('details').textContent=`${current.field.status} · ${current.field.label || 'No decoded label'} · confidence ${current.field.confidence ?? 'unknown'}`;
  $('reason').textContent=current.reason;
  $('source').textContent=`${current.source.pdf} · original page ${current.source.page}`;
  $('warnings').replaceChildren();
  for (const text of [...current.warnings,...current.diagnostics.map(d=>d.message)]) {const li=document.createElement('li');li.textContent=text;$('warnings').append(li);}
  const oldControl=$('correction');
  const control=document.createElement(current.field_kind==='text'?'textarea':'input');
  control.id='correction';control.setAttribute('aria-describedby','correction-help');
  control.maxLength=current.field_kind==='text'?10000:64;
  if(current.field_kind==='text') control.rows=5;
  else {control.pattern='[0-9]{1,64}';control.inputMode='numeric';control.autocomplete='off';}
  control.value=retainInput?oldControl.value:(current.field.value ?? '');
  control.oninput=()=>setBusy(busy);
  oldControl.replaceWith(control);
  scanReady=false;
  const serial=++scanSerial;
  const scan=document.createElement('img');scan.id='scan';scan.alt='Original card scan';scan.style.width=`${zoom*100}%`;
  scan.hidden=!!current.diagnostics.length;
  $('scan-status').textContent=scan.hidden?'Original scan unavailable.':'Loading original card…';
  scan.onload=()=>{if(serial!==scanSerial)return;scanReady=true;$('scan-status').textContent='';setBusy(busy);};
  scan.onerror=()=>{if(serial!==scanSerial)return;scanReady=false;$('scan-status').textContent='Original scan failed to load. Reload the item before reviewing.';setBusy(busy);};
  $('scan').replaceWith(scan);
  if(!scan.hidden) scan.src=current.scan_url;
  $('history').replaceChildren();
  for (const event of current.field.review?.history || []) {
    const p=document.createElement('p');
    p.textContent=`${event.action} by ${event.reviewer} · ${new Date(event.timestamp).toLocaleString()} · ${event.before.value ?? event.before.status} → ${event.after.value ?? event.after.status}`;
    $('history').append(p);
  }
  for (const button of $('items').children) button.classList.toggle('selected',button.dataset.item===id);
  setBusy(busy);
}
async function run(work) {
  if (busy) return;
  setBusy(true);
  try {await work();} catch(e) {message(e.code==='no_op'?'Already saved. To amend the value, enter the exact value and choose Save correction.':e.message,e.code!=='no_op');} finally {setBusy(false);}
}
function requestBody(action,value,target=null,version=current.version) {
  const key=JSON.stringify([current.id,action,value,target,version]);
  if (pending?.key!==key) pending={key,body:{expected_version:version,request_id:crypto.randomUUID()}};
  return {...pending.body,...(action==='undo'?{}:{action,...(value===undefined?{}:{value})})};
}
async function decide(action) {
  if (!signedIn || !current.allowed_actions.includes(action)) return;
  if(action==='accept' && hasUnsavedCorrection()) {message('Choose Save correction to save the entered amendment.');return;}
  const value=action==='correct'?$('correction').value:undefined;
  pendingUndo=null;
  const body=requestBody(action,value);
  const result=await api(`/api/review-items/${current.id}/decisions`,body);
  pending=null;message('');
  lastSaved={id:result.item.id,decision:result.decision.id};
  $('saved').replaceChildren(document.createTextNode('Saved locally: '+action));
  const undo=document.createElement('button');undo.textContent='Undo last saved decision';undo.onclick=()=>run(()=>undoSaved(lastSaved.id,lastSaved.decision));$('saved').append(undo);
  showSync(result.sync);
  await refreshQueue();
}
async function undoSaved(itemId,decisionId) {
  if(pendingUndo?.itemId!==itemId || pendingUndo?.decisionId!==decisionId) {
    await openItem(itemId,true);
    pendingUndo={itemId,decisionId,body:requestBody('undo',undefined,decisionId)};
  }
  let result;
  try {result=await api(`/api/decisions/${decisionId}/undo`,pendingUndo.body);}
  catch(error) {
    if(error.status>=400 && error.status<500) {
      pendingUndo=null;pending=null;
      if(error.status===409) {try {await openItem(itemId,true);} catch {} }
    }
    throw error;
  }
  pendingUndo=null;pending=null;lastSaved=null;message('');
  $('saved').textContent='Undo saved locally. Audit history retained.';
  showSync(result.sync);
  await refreshQueue(itemId);
}
$('session').onsubmit=e=>{e.preventDefault();run(async()=>{const data=await api('/api/session',{name:$('name').value});signedIn=true;$('reviewer').textContent=data.reviewer;pending=null;pendingUndo=null;message('Reviewer name set. Decisions save as you make them.');});};
$('set-reviewer').onclick=()=>{$('name').scrollIntoView({block:'center'});$('name').focus();};
$('region').onchange=()=>{if(!busy) fillBatches();};
$('load').onclick=()=>run(()=>refreshQueue());
$('decision').onsubmit=e=>{e.preventDefault();run(()=>decide('correct'));};
$('correction').oninput=()=>setBusy(busy);
for (const button of document.querySelectorAll('[data-action]:not([type="submit"])')) button.onclick=()=>run(()=>decide(button.dataset.action));
$('reload').onclick=()=>run(async()=>{await openItem(current.id,true);message('Current item reloaded; entered correction retained.');});
$('undo').onclick=()=>run(()=>undoSaved(current.id,current.undo_decision_id));
$('sync-now').onclick=()=>run(async()=>{showSync(await api('/api/sync',{}));});
$('exit').onclick=()=>run(async()=>{const data=await api('/api/sync',{});showSync(data);if(data.pending || data.state!=='uploaded'){message('Local decisions are retained. Sharing could not be confirmed. Keep reviewing or acknowledge before closing.',true);$('acknowledge').hidden=false;}else{message('All changes uploaded. You may close this tab and stop the backend with Ctrl+C.');}});
$('acknowledge').onclick=()=>message('Pending changes remain saved on this computer. You may close this tab; reopen the tool to retry sharing.');
function changeZoom(delta) {zoom=Math.max(.25,Math.min(4,zoom+delta));$('scan').style.width=`${zoom*100}%`;$('zoom-level').textContent=Math.round(zoom*100)+'%';}
$('zoom-in').onclick=()=>changeZoom(.25);$('zoom-out').onclick=()=>changeZoom(-.25);
(async()=>{try {const health=await api('/api/health');if(!health.ready) throw new Error(health.diagnostics.map(d=>d.message).join('\n'));regions=(await api('/api/regions')).regions;$('region').replaceChildren(...regions.map(r=>new Option(r.region,r.region)));fillBatches();await refreshQueue();await refreshSync();}catch(e){message(e.message,true);}setBusy(false);})();
setInterval(()=>{if(!busy) refreshSync();},10000);
