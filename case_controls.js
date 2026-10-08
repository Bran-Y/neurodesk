function render({model, el}) {
  el.innerHTML = `<div style="max-width:850px">
    <label>Existing case: <select aria-label="Existing case"><option value="">Select a saved case...</option></select></label><br>
    <label>Config: <input aria-label="Config:" style="width:70%;margin:8px 0"></label><br>
    <label>References: <select aria-label="References:"><option value="config">Use saved configuration</option><option value="PD">PD + Potvin (no AD comparison)</option><option value="all">All available references</option></select></label>
    <p>Choose a case, then Generate reports. Reference selection is not a diagnosis.</p>
    <label><input type="checkbox"> I confirm the selected modality and authorise processing</label>
    <p><button data-action="status">Check status</button> <button data-action="process">Start processing</button> <button data-action="report">Generate reports</button> <button data-reconnect>Reconnect controls</button></p>
    <p role="status" style="font-weight:600"></p></div>`;
  const path = el.querySelector('input[aria-label="Config:"]');
  const cases = el.querySelector('select[aria-label="Existing case"]');
  const reference = el.querySelector('select[aria-label="References:"]');
  const consent = el.querySelector('input[type=checkbox]');
  const status = el.querySelector('[role=status]');
  const buttons = [...el.querySelectorAll('[data-action]')];
  for (const value of model.get('cases')) {
    const option = document.createElement('option');
    option.value = value; option.textContent = value.split('/')[1]; cases.append(option);
  }
  path.value = model.get('config');
  let online = false, pending = null, ping = null, lastReply = 0, timeout = null;
  let completedSelection = null;
  const results = () => el.closest('.case-switch-workflow')?.querySelector('.case-switch-results');
  const hide = () => { const node=results(); if(node) node.style.display='none'; };
  const enable = () => { buttons.forEach(b => b.disabled = !online || !!pending); };
  const id = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  function probe() { ping=id(); model.send({type:'ping',id:ping}); }
  function changed() {
    completedSelection=null; hide(); consent.checked=false;
    status.textContent='Case selection changed. Previous report hidden; click Generate reports.';
  }
  path.addEventListener('input', changed);
  reference.addEventListener('change', changed);
  cases.addEventListener('change', () => { if(cases.value) {path.value=cases.value; changed();} });
  function configChanged() { path.value=model.get('config'); cases.value=path.value; changed(); }
  model.on('change:config', configChanged);
  function receive(msg) {
    if(msg.type==='ready' && msg.id===ping) {
      online=true; lastReply=Date.now(); enable();
      // Restore only the verified selection after a transient busy-kernel timeout.
      if(!pending && completedSelection && path.value.trim()===completedSelection.config && reference.value===completedSelection.reference) {
        const node=results(); if(node) node.style.display='';
      }
      if(!pending && (status.textContent.startsWith('Connecting') || status.textContent.startsWith('Controls disconnected'))) status.textContent='Connected to live kernel. Select a case and generate its report.';
    }
    if(!pending || msg.id!==pending.id) return;
    if(msg.type==='accepted') {
      status.textContent=`Backend confirmed ${msg.config}. Running...`;
    }
    if(msg.type==='done') {
      clearTimeout(timeout);
      const unchanged=path.value.trim()===pending.config && reference.value===pending.reference;
      pending=null; lastReply=Date.now(); online=true; enable();
      if(msg.ok && unchanged) {
        completedSelection={config:msg.config,reference:reference.value};
        const node=results(); if(node) node.style.display='';
        status.textContent=`Completed for ${msg.config}`;
      } else {
        hide(); status.textContent=msg.ok ? 'Selection changed during processing. Generate a new report.' : `Failed: ${msg.error}`;
      }
      probe();
    }
  }
  model.on('msg:custom',receive);
  buttons.forEach(button => button.addEventListener('click', () => {
    if(!online || pending) return;
    completedSelection=null; hide(); pending={id:id(),config:path.value.trim(),reference:reference.value}; enable();
    status.textContent=`Waiting for backend confirmation: ${pending.config}`;
    model.send({type:'action',...pending,action:button.dataset.action,consent:consent.checked});
    timeout=setTimeout(() => {
      status.textContent='No completion received. The request may still be running; do not resubmit. Rerun the entry cell to reconnect.';
      online=false; enable(); hide();
    },180000);
  }));
  el.querySelector('[data-reconnect]').addEventListener('click', () => {
    status.textContent='Connecting to kernel...'; online=false; enable(); probe();
  });
  hide(); enable(); status.textContent='Connecting to kernel...'; probe();
  const timer=setInterval(() => {
    if(pending) return;
    if(Date.now()-lastReply>20000) {
      online=false; enable(); hide();
      status.textContent='Controls disconnected. Click Reconnect controls; if it persists, rerun the entry cell. Old report hidden.';
    }
    probe();
  },7000);
  return () => { clearInterval(timer); clearTimeout(timeout); model.off('msg:custom',receive); model.off('change:config',configChanged); };
}
export default {render};
