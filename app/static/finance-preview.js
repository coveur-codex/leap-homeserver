/* Mirrors FinanceNavigation and FinanceUi.cpp at the native 342 × 142 size. */
document.querySelectorAll('[data-finance-preview]').forEach(canvas => {
  const card = canvas.closest('[data-preview-card]');
  const data = JSON.parse(card.querySelector('[data-finance-data]').textContent);
  const rows = data.securities || [];
  const ctx = canvas.getContext('2d');
  let selected = 0, detailSelected = 0, detail = false, visible = false;
  let nextRotation = performance.now() + 10000;
  const C = {bg:'#101c29', panel:'#181c39', muted:'#9ca6ad', green:'#40fc80', red:'#f06868', white:'#ffffff'};
  const number = value => {
    if (!Number.isFinite(value) || value <= 0) return '--';
    for (const [limit, suffix] of [[1e12,'T'],[1e9,'B'],[1e6,'M']]) if (value >= limit) return (value / limit).toFixed(1) + suffix;
    return value.toFixed(value >= 100000 ? 0 : value < .01 ? 5 : 2);
  };
  const text = (value, x, y, width = 154, size = 1, color = C.white) => {
    const cells = Math.floor(width / (6 * size));
    let s = String(value ?? '');
    if (s.length > cells) s = s.slice(0, cells - 1) + '.';
    ctx.fillStyle = color; ctx.font = `${8 * size}px monospace`; ctx.textBaseline = 'top';
    ctx.fillText(s, x - 86, y);
  };
  const status = q => {
    const age = Date.now() / 1000 - data.generatedAt;
    if (q.stale || !data.generatedAt || age < 0 || age > (q.market === 'closed' ? 1200 : 600)) return '! Veraltet';
    if (q.delayed) return 'Verzögert';
    return q.market === 'closed' ? 'Geschlossen' : q.market === 'unknown' ? 'Handel unklar' : '';
  };
  const color = q => q.changePercent > .00005 ? C.green : q.changePercent < -.00005 ? C.red : C.muted;
  const moon = (x,y) => {
    ctx.fillStyle=C.muted; ctx.beginPath(); ctx.arc(x-86,y,4,0,Math.PI*2); ctx.fill();
    ctx.fillStyle=C.bg; ctx.beginPath(); ctx.arc(x-83,y-2,4,0,Math.PI*2); ctx.fill();
  };
  const change = (q,x,y,width) => {
    const value=q.changePercent;
    text(value == null ? '– -- %' : `${value > .00005 ? '↑' : value < -.00005 ? '↓' : '–'} ${value >= 0 ? '+' : ''}${value.toFixed(2)}%`,x,y,width,1,color(q));
  };
  const line = (x,y,x2,y2,c) => {
    ctx.strokeStyle=c; ctx.beginPath(); ctx.moveTo(x-86,y); ctx.lineTo(x2-86,y2); ctx.stroke();
  };
  const render = () => {
    ctx.fillStyle=C.bg; ctx.fillRect(0,0,342,142);
    if (!rows.length) {
      text('Finanzen',96,28,316); text('Wertpapiere am Homeserver hinzufügen.',96,48,316,1,C.muted);
    } else if (!detail) {
      const page=Math.floor(selected/3), first=page*3;
      rows.slice(first,first+3).forEach((q,j) => {
        const x=86+j*114;
        ctx.strokeStyle=first+j===selected ? C.white : C.panel;
        ctx.strokeRect(x-84+0.5,3.5,110,114);
        text(q.symbol,x+7,10,99);
        if(q.market==='closed') moon(x+101,15);
        if(!q.available) {text('Kein Kurs',x+7,42,100,1,C.muted);text('Server prüfen',x+7,64,100,1,C.muted);return;}
        text(number(q.price),x+7,32,100,2);text(q.currency,x+7,52,100,1,C.muted);
        change(q,x+7,70,98);text(q.quoteTime,x+7,88,100,1,C.muted);text(status(q),x+7,102,100,1,C.muted);
      });
      text('Mitte: Details',94,121,200,1,C.muted);
      text(`${page+1}/${Math.ceil(rows.length/3)}`,391,121,37,1,C.muted);
    } else {
      const q=rows[detailSelected];
      text(q.symbol,94,6,145);if(q.market==='closed')moon(246,10);
      if(!q.available){text(q.error || 'Kein Kurs verfügbar',94,30,320,1,C.muted);}
      else {
        text(number(q.price),94,23,158,2);text(q.currency,94,42,158,1,C.muted);change(q,94,55,155);
        text(`${q.quoteTime || ''} ${q.timezone || ''}`,265,6,155,1,C.muted);text(status(q),265,19,155,1,C.muted);
        const words=(q.news?.title || 'Keine Nachricht verfügbar').split(/\s+/);let lines=[''];
        words.forEach(word => {
          while(word.length>26){ if(lines.at(-1))lines.push('');lines[lines.length-1]=word.slice(0,26);word=word.slice(26);lines.push(''); }
          if((lines.at(-1)+' '+word).trim().length>26)lines.push(word);else lines[lines.length-1]=(lines.at(-1)+' '+word).trim();
        });
        lines.slice(0,4).forEach((s,i)=>text(i===3 && lines.length>4 ? s.slice(0,25)+'.' : s,94,72+i*9,157));
        text(q.news?.source,94,112,157,1,C.muted);text((q.news?.time || '')+(q.newsStale?' !':''),94,122,157,1,C.muted);
        line(257,30,257,126,C.panel);text('H '+number(q.high),265,34,155,1,C.muted);text('T '+number(q.low),265,112,155,1,C.muted);
        const pts=(q.points||[]).filter(p=>p[0]>0 && Number.isFinite(p[1]) && p[1]>0);
        if(!pts.length)text('Keine Intradaydaten',265,74,155,1,C.muted);
        else {
          let lo=Math.min(...pts.map(p=>p[1])),hi=Math.max(...pts.map(p=>p[1]));
          const pad=hi>lo?(hi-lo)*.08:Math.max(.01,hi*.001);lo-=pad;hi+=pad;
          const first=pts[0][0],last=pts.at(-1)[0];
          [49,77,105].forEach(y=>line(265,y,419,y,C.panel));
          let prev=null;
          pts.forEach(([t,p,segment])=>{
            const x=last>first?265+(t-first)/(last-first)*153:342;
            const y=105-(p-lo)/(hi-lo)*56;
            if(prev && t>prev.t && (segment != null ? segment===prev.segment : t-prev.t<=(q.gapSeconds||900)))line(prev.x,prev.y,x,y,color(q));
            ctx.fillStyle=color(q);ctx.beginPath();ctx.arc(x-86,y,1,0,Math.PI*2);ctx.fill();prev={x,y,t,segment};
          });
          text(q.chartMode==='collected'?'Gesammelte Kurse':'Intraday',265,123,155,1,C.muted);
        }
      }
    }
    ctx.fillStyle=C.panel;ctx.fillRect(0,132,342,10);
    text('L: Seiten / Menü   R: Wählen / OK',94,134,326,1,C.muted);
  };
  const key = k => {
    if(!rows.length)return;
    const move=delta=>{if(detail)detailSelected=(detailSelected+rows.length+delta)%rows.length;else selected=(selected+rows.length+delta)%rows.length;};
    if(detail){
      if(k==='ArrowUp')move(-1);if(k==='ArrowDown')move(1);
      if(['ArrowLeft','Enter','Escape'].includes(k))detail=false;
    }else{
      if(k==='ArrowLeft')move(-1);if(k==='ArrowRight')move(1);
      if(k==='Enter'){detailSelected=selected;detail=true;}
    }
    nextRotation=performance.now()+40000;render();
  };
  canvas.addEventListener('keydown',event=>{
    if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Enter','Escape'].includes(event.key)){event.preventDefault();key(event.key);}
  });
  canvas.addEventListener('click',event=>{
    if(detail){key('Enter');return;}
    const index=Math.floor((event.clientX-canvas.getBoundingClientRect().left)/canvas.getBoundingClientRect().width*3);
    const target=Math.floor(selected/3)*3+index;
    if(target<rows.length){selected=target;nextRotation=performance.now()+40000;render();canvas.focus();}
  });
  document.querySelectorAll('[data-finance-key]').forEach(button=>button.addEventListener('click',()=>key(button.dataset.financeKey)));
  setInterval(()=>{
    const active=!card.hidden;
    if(active && !visible)nextRotation=performance.now()+10000;
    visible=active;
    if(active && !detail && rows.length>3 && performance.now()>=nextRotation){selected=((Math.floor(selected/3)+1)%Math.ceil(rows.length/3))*3;nextRotation=performance.now()+10000;}
    if(active)render();
  },250);
  render();
});
