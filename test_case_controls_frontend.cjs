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
const model = {get:key=>key==='cases'?['cases/ONE/config.json']: 'cases/ONE/config.json',
  send:message=>sent.push(message), on:(type, fn)=>listeners[type]=fn, off(){}};
let now=100000, timer;
const context = vm.createContext({document:{createElement:()=>({})}, Date:{now:()=>now}, Math,
  setInterval:fn=>(timer=fn,1), clearInterval(){}, setTimeout:()=>1, clearTimeout(){}});
vm.runInContext(fs.readFileSync(__dirname+'/case_controls.js','utf8').replace('export default {render};',''), context);
context.render({model,el});
const replyReady = () => listeners['msg:custom']({type:'ready',id:sent.at(-1).id});
replyReady();
buttons[2].listeners.click();
const request=sent.at(-1);
listeners['msg:custom']({type:'done',id:request.id,config:request.config,ok:true});
assert.equal(results.style.display,'');
now+=21000; timer();
assert.equal(results.style.display,'none');
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
console.log('PASS: transient heartbeat recovery; changed selection and failed requests stay hidden');
