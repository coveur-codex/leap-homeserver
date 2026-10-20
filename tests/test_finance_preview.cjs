const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
for(const count of [0,1,2,3,4,6,7]){
  let now=0,tick;const texts=[],rects=[];const handlers={};
  const rows=Array.from({length:count},(_,i)=>({symbol:`S${i}`,available:true,price:123.45,currency:'USD',quoteTime:'20.10. 15:30',market:i%2?'closed':'open',stale:false,changePercent:i%3-1,high:125,low:120,points:[[1,121,0],[300,122,0],[6000,123,1]],chartMode:'collected',news:i%2?null:{title:'This is an unusually long relevant company headline that should wrap across several readable lines',source:'Source',time:'20.10. 15:00'}}));
  const card={hidden:false,querySelector:()=>({textContent:JSON.stringify({generatedAt:1000,securities:rows})})};
  const ctx={fillRect(x,y,w,h){rects.push([x,y,w,h]);},strokeRect(){},fillText(s){texts.push(s);},beginPath(){},arc(){},fill(){},moveTo(){},lineTo(){},stroke(){}};
  const canvas={closest:()=>card,getContext:()=>ctx,addEventListener:(e,fn)=>handlers[e]=fn};
  vm.runInNewContext(fs.readFileSync('app/static/finance-preview.js','utf8'),{document:{querySelectorAll:q=>q==='[data-finance-preview]'?[canvas]:[]},performance:{now:()=>now},Date:{now:()=>1000000},setInterval:fn=>tick=fn});
  const frame=t=>{now=t;texts.length=0;tick();};
  const key=key=>{texts.length=0;handlers.keydown({key,preventDefault(){}});};
  frame(0);frame(9999);assert(!texts.includes('S3'));
  frame(10000);assert.equal(texts.includes('S3'),count>3);
  if(!count)continue;
  frame(10001);key('ArrowLeft'); // wrap from selected (3 or 0)
  key('Enter');assert(texts.includes('Gesammelte Kurse'));
  const overview= count>3 ? 2 : count-1;
  assert(texts.includes(`S${overview}`));
  key('ArrowDown');assert(texts.includes(`S${(overview+1)%count}`));
  frame(90000);assert(texts.includes('Gesammelte Kurse'));
  key('Enter');assert(!texts.includes('Gesammelte Kurse'));
  const expected=`${Math.floor(overview/3)+1}/${Math.ceil(count/3)}`;
  assert(texts.includes(expected));
  frame(120000);assert(texts.includes(expected)); // pause elapsed, no next tick yet
  frame(129999);assert(texts.includes(expected));
  frame(130000);assert(texts.includes(count>3 ? `${(Math.floor(overview/3)+1)%Math.ceil(count/3)+1}/${Math.ceil(count/3)}` : expected));
  assert(rects.every(r=>r.every(Number.isFinite)));
}
console.log('PASS: finance preview 0/1/2/3/4/6/7, rotation, manual pause, selection, details and return');
