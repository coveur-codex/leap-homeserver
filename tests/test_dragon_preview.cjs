const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const button = () => ({events: {}, addEventListener(type, fn) { this.events[type] = fn; }, setPointerCapture() {}});
const jump = button(), duck = button(), fire = button();
const card = {hidden: false, querySelector: s => ({'[data-dragon-jump]':jump,'[data-dragon-duck]':duck,'[data-dragon-fire]':fire})[s]};
const panel = {hidden: false};
const rectangles = [], texts = [], circles = [];
const ctx = {
  fillRect(x,y,w,h) {rectangles.push({x,y,w,h,color:this.fillStyle});},
  fillText(text) {texts.push(text);}, beginPath() {}, arc(x,y,r) {circles.push({x,y,r,color:this.fillStyle});},
  fill() {}, moveTo() {}, lineTo() {}
};
const canvas = {closest: s => s==='.games-card'?card:panel, getContext: () => ctx};
let next;
vm.runInNewContext(fs.readFileSync('app/static/device-preview.js','utf8'), {
  document: {hidden:false, querySelectorAll: s => s==='[data-dragon-canvas]'?[canvas]:[]},
  requestAnimationFrame: fn => {next=fn;}
});
function frame(t) {rectangles.length=0; circles.length=0; texts.length=0; next(t);}
frame(1000); frame(1033);
assert(texts.includes('Drachenrennen · Vorschau') && texts.includes('Feuer OK'));
const head = () => circles.find(p => p.x===68 && p.color==='#215931').y;
const standing = head();
jump.events.click(); frame(1133); assert(head()<standing-10);
for(let t=1233;t<=2333;t+=100) frame(t);
assert(head()<standing-10); // Still airborne after the former 1.2-second jump.
for(let t=2433;t<=2633;t+=100) frame(t);
assert.equal(head(),standing);
duck.events.pointerdown({pointerId:1}); frame(2666); assert(head()>standing);
duck.events.lostpointercapture(); frame(2699); assert.equal(head(),standing);
duck.events.keydown({key:' ',preventDefault(){}}); frame(2732); assert(head()>standing);
duck.events.keyup(); frame(2765); assert.equal(head(),standing);
fire.events.click(); frame(2798); assert(texts.includes('Feuer...'));
assert(circles.some(p => p.x>120 && p.color==='#ffdd44'));
assert(circles.some(p => p.color==='#ff7700'));
fire.events.click(); frame(2898); frame(2998); frame(3098); assert(circles.some(p => p.color==='#ff7700'));
frame(3198); assert(!circles.some(p => p.color==='#ff7700'));
for(let t=3198;t<=3898;t+=100) frame(t);
assert(texts.includes('Feuer OK'));
panel.hidden=true; frame(100000); assert.equal(rectangles.length,0);
panel.hidden=false; frame(100033); assert.equal(head(),standing);
assert(rectangles.every(p => [p.x,p.y,p.w,p.h].every(Number.isFinite)));
console.log('PASS: Dragon preview jump/landing, held pointer/keyboard duck, release, fire cooldown and hidden-page pause');
