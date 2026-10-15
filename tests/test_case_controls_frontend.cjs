const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = {};
function element(key) {
  return elements[key] ??= {value:'', checked:false, style:{}, listeners:{},
    addEventListener(type, fn) {this.listeners[type]=fn;}, append() {}};
}
const results = element('results');
const buttons = ['status','process','report'].map(action => ({dataset:{action}, listeners:{},
  addEventListener(type, fn) {this.listeners[type]=fn;}}));
const el = {querySelector:element, querySelectorAll:()=>buttons,
  closest:()=>({querySelector:()=>results})};
const listeners = {}, sent = [];
let activity = {};
const model = {get:key=>key==='activity'?activity:key==='cases'?['cases/ONE/config.json']: 'cases/ONE/config.json',
  send:message=>sent.push(message), on:(type, fn)=>listeners[type]=fn, off(){}};
let now=100000, timer;
const context = vm.createContext({document:{createElement:()=>({})}, Date:{now:()=>now}, Math,
  setInterval:fn=>(timer=fn,1), clearInterval(){}, setTimeout:()=>1, clearTimeout(){}});
vm.runInContext(fs.readFileSync(__dirname+'/../src/case_controls.js','utf8').replace('export default {render};',''), context);
context.render({model,el});
const replyReady = () => listeners['msg:custom']({type:'ready',id:sent.at(-1).id});
replyReady();
now+=7000; timer();
const delayedProbe=sent.at(-1);
now+=7000; timer();
listeners['msg:custom']({type:'ready',id:delayedProbe.id});
assert.equal(buttons[2].disabled,false);
buttons[2].listeners.click();
const request=sent.at(-1);
listeners['msg:custom']({type:'done',id:request.id,config:request.config,ok:true});
assert.equal(results.style.display,'');
now+=21000; timer();
assert.equal(results.style.display,'');
now+=40000; timer();
assert.equal(results.style.display,'');
replyReady();
assert.equal(results.style.display,'');
element('input[aria-label="Config:"]').value='cases/TWO/config.json';
element('input[aria-label="Config:"]').listeners.input();
timer(); replyReady();
assert.equal(results.style.display,'none');
buttons[2].listeners.click();
const failed=sent.at(-1);
listeners['msg:custom']({type:'done',id:failed.id,config:failed.config,ok:false,error:'failure'});
replyReady();
assert.equal(results.style.display,'none');
activity={config:'cases/TWO/config.json',reference:'',state:'running',message:'Generating report'};
listeners['change:activity']();
assert.equal(buttons[2].disabled,true);
assert.equal(results.style.display,'');
now+=90000; timer();
assert.equal(results.style.display,'');
replyReady();
assert.equal(buttons[2].disabled,true);
activity={...activity,state:'complete',message:'Report ready'};
listeners['change:activity']();
assert.equal(buttons[2].disabled,false);
assert.equal(element('[role=status]').textContent,'Report ready');
element('input[aria-label="Config:"]').value='cases/THREE/config.json';
element('input[aria-label="Config:"]').listeners.input();
listeners['change:activity']();
assert.equal(results.style.display,'none');
context.render({model,el});
assert.equal(element('input[aria-label="Config:"]').value,'cases/TWO/config.json');
assert.equal(results.style.display,'');
console.log('PASS: slow generation, no timeout hiding, duplicate guards, selection isolation and view restoration');
