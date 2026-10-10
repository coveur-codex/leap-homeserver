document.querySelectorAll("[data-news-carousel]").forEach((carousel) => {
  const slides = [...carousel.querySelectorAll("[data-news-slide]")];
  const counter = carousel.querySelector(".slide-count");
  let current = 0;

  const show = (next) => {
    current = (next + slides.length) % slides.length;
    slides.forEach((slide, index) => {
      const active = index === current;
      slide.hidden = !active;
      slide.classList.toggle("active", active);
    });
    if (counter) counter.textContent = `${current + 1} / ${slides.length}`;
  };

  carousel.querySelector("[data-news-prev]")?.addEventListener("click", () => show(current - 1));
  carousel.querySelector("[data-news-next]")?.addEventListener("click", () => show(current + 1));
});

document.querySelectorAll(".leap-preview").forEach((preview) => {
  let cards = [...preview.querySelectorAll("[data-preview-card]")];
  const allCards = [...cards];
  if (!cards.length) return;
  const label = preview.querySelector("[data-card-label]");
  const counter = preview.querySelector("[data-card-count]");
  let current = 0;
  const show = (next) => {
    current = (next + cards.length) % cards.length;
    cards.forEach((card, index) => {
      card.hidden = index !== current;
      card.classList.toggle("active", index === current);
    });
    if (label) label.textContent = cards[current].dataset.previewCard;
    if (counter) counter.textContent = `${current + 1} / ${cards.length}`;
  };
  preview.querySelector("[data-card-prev]")?.addEventListener("click", () => show(current - 1));
  preview.querySelector("[data-card-next]")?.addEventListener("click", () => show(current + 1));
  document.querySelector('[data-communication-toggle]')?.addEventListener('change', (event) => {
    const enabled = event.target.checked;
    allCards.forEach(card => { card.hidden = true; });
    cards = allCards.filter(card => enabled || card.dataset.previewCard !== 'KOMMUNIKATION');
    const nav = preview.querySelector('.preview-nav');
    if (nav) nav.hidden = cards.length < 2;
    if (cards.length) show(0);
    else { if (label) label.textContent = 'LEER'; if (counter) counter.textContent = '0 / 0'; }
  });
  show(0);
});

document.querySelectorAll('select[name="knowledge_source"]').forEach((input) => {
  input.addEventListener("change", () => {
    const label = document.querySelector("[data-knowledge-source-label]");
    if (label) label.textContent = input.value === "miniklexikon" ? "MiniKlexikon" : "Klexikon";
  });
});

// A local display example only; no chat traffic or history is sent to the server.
document.querySelectorAll('[data-message-choice]').forEach(button => {
  button.addEventListener('click', () => {
    document.querySelector('[data-communication-message]').textContent = button.textContent;
  });
});

// Asset/layout preview. Pet needs and Snake rounds remain local to the device.
document.querySelectorAll('.games-card').forEach(card => {
  const assets = JSON.parse(card.querySelector('[data-pet-assets]').textContent);
  const menu = card.querySelector('[data-games-menu]');
  const pet = card.querySelector('[data-pet-preview]');
  const snake = card.querySelector('[data-snake-preview]');
  const dragon = card.querySelector('[data-dragon-preview]');
  const image = card.querySelector('[data-pet-image]');
  const fallback = card.querySelector('[data-pet-fallback]');
  let animation = 'idle', frame = 0, lastFrame = 0, actionUntil = 0;
  card.querySelectorAll('[data-game-open]').forEach(button => button.addEventListener('click', () => {
    menu.hidden = true;
    pet.hidden = button.dataset.gameOpen !== 'pet';
    snake.hidden = button.dataset.gameOpen !== 'snake';
    dragon.hidden = button.dataset.gameOpen !== 'dragon';
    animation = 'idle'; actionUntil = 0; frame = 0;
  }));
  card.querySelectorAll('[data-game-back]').forEach(button => button.addEventListener('click', () => {
    menu.hidden = false; pet.hidden = snake.hidden = dragon.hidden = true;
  }));
  card.querySelectorAll('[data-pet-action]').forEach(button => button.addEventListener('click', () => {
    animation = ['eating', 'playing', 'happy', 'sleeping'][Number(button.dataset.petAction)];
    actionUntil = Date.now() + 3000; frame = 0; lastFrame = 0;
  }));
  image.addEventListener('error', () => { image.hidden = true; fallback.hidden = false; });
  setInterval(() => {
    if (pet.hidden || card.hidden) return;
    const now = Date.now();
    if (actionUntil && now >= actionUntil) { animation = 'idle'; actionUntil = 0; frame = 0; }
    const hour = Number(new Intl.DateTimeFormat('en', {hour: 'numeric', hourCycle: 'h23', timeZone: 'Europe/Berlin'}).format(new Date()));
    const background = assets.backgrounds[hour < 7 || hour >= 20 ? 'night' : 'day'];
    card.querySelector('[data-pet-scene]').style.backgroundImage = background ? `url("${background}")` : '';
    const current = assets.animations[animation] || assets.animations.idle;
    if (current?.frames.length && now - lastFrame >= Math.max(250, current.frameDurationMs || 400)) {
      image.src = current.frames[frame++ % current.frames.length];
      image.hidden = false; fallback.hidden = true; lastFrame = now;
    }
  }, 100);
});

// Same assets and bounded procedural effects as the device; no generated effect images.
document.querySelectorAll('[data-chill-preview]').forEach(canvas => {
  const card = canvas.closest('.chill-card');
  const ctx = canvas.getContext('2d');
  const scene = canvas.dataset.scene;
  const slider = card.querySelector('[data-chill-slider]');
  const sprites = [...card.querySelectorAll('[data-chill-sprite]')];
  const particles = Array.from({length: 72}, () => ({x: Math.random()*428, y: Math.random()*142, d: .25+Math.random()*.75, phase: Math.random()*6.28}));
  let previous = 0, time = 0;
  const sprite = (img, x, y, w, h) => { if (img.complete && img.naturalWidth) ctx.drawImage(img, x, y, w, h); };
  const draw = now => {
    requestAnimationFrame(draw);
    if (card.hidden || document.hidden) { previous = now; return; }
    const dt = Math.min((now-previous)/1000, .2); previous = now; time += dt;
    const level = Number(slider.value);
    ctx.fillStyle = scene === 'fire' ? '#100000' : scene === 'snow' ? '#081029' : '#000008';
    ctx.fillRect(0,0,428,142);
    if (scene === 'space' && sprites.length && time%40 >= 8) {
      const img = sprites[Math.floor(time/40)%sprites.length], w=Number(img.dataset.width), h=Number(img.dataset.height);
      sprite(img,428-(time%40-8)/32*(428+w),18,w,h);
    } else if (scene !== 'space') sprites.forEach(img => {
      let w=Number(img.dataset.width), h=Number(img.dataset.height), x=Number(img.dataset.x), y=Number(img.dataset.y);
      if (img.dataset.role === 'foreground') w=428;
      if (img.dataset.role === 'animation') { const scale=.55+level*.0045; x+=w*(1-scale)/2; y+=h*(1-scale); w*=scale; h*=scale; }
      sprite(img,x,y,w,h);
    });
    const count = scene === 'space' ? 56 : level ? scene === 'snow' ? 4+Math.floor(level*.68) : 1+Math.floor(level*.11) : 0;
    particles.slice(0,count).forEach(p => {
      if (scene === 'space') { p.x-=dt*level*.26*p.d; if(p.x < -2) { p.x=430; p.y=Math.random()*142; } }
      if (scene === 'snow') { p.y+=dt*(7+level*.12)*p.d; p.x+=dt*Math.sin(time*.7+p.phase)*(2+level*.025)*p.d; if(p.y>144) {p.y=-2; p.x=Math.random()*428;} }
      if (scene === 'fire') { if(p.y<28 || p.x<182 || p.x>246) {p.x=192+Math.random()*44; p.y=102+Math.random()*12;} p.y-=dt*(7+level*.09)*p.d; p.x+=dt*Math.sin(time+p.phase)*2; }
      ctx.fillStyle=scene==='fire' ? p.y>75 ? '#ffba40' : '#945520' : p.d>.7 ? '#efefef' : '#8c8c88';
      ctx.beginPath();ctx.arc(p.x,p.y,p.d>.8 && scene!=='fire' ? 1.2 : .6,0,Math.PI*2);ctx.fill();
    });
    ctx.strokeStyle='#8c8c88';ctx.beginPath();ctx.moveTo(12,8);ctx.lineTo(6,14);ctx.lineTo(12,20);ctx.stroke();
  };
  requestAnimationFrame(draw);
});

// Procedural control/graphics demo; it does not read or overwrite device scores.
document.querySelectorAll('[data-dragon-canvas]').forEach(canvas => {
  const panel = canvas.closest('[data-dragon-preview]');
  const card = canvas.closest('.games-card');
  const ctx = canvas.getContext('2d');
  const jump = card.querySelector('[data-dragon-jump]');
  const duck = card.querySelector('[data-dragon-duck]');
  const fire = card.querySelector('[data-dragon-fire]');
  let previous = 0, time = 0, distance = 0, lift = 0, velocity = 0, down = false, flame = 0, cooldown = 0;
  const rect = (x,y,w,h,c) => { ctx.fillStyle=c; ctx.fillRect(x,y,w,h); };
  const circle = (x,y,r,c) => { ctx.fillStyle=c; ctx.beginPath(); ctx.arc(x,y,r,0,Math.PI*2); ctx.fill(); };
  const triangle = (x,y,w,h,c) => { ctx.fillStyle=c; ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x-w,y+h);ctx.lineTo(x+w,y+h);ctx.fill(); };
  jump.addEventListener('click', () => { if (!lift) velocity=-180; });
  fire.addEventListener('click', () => { if (!cooldown) { flame=.42; cooldown=.95; } });
  duck.addEventListener('pointerdown', event => { down=true; duck.setPointerCapture(event.pointerId); });
  ['pointerup','pointercancel','lostpointercapture','blur'].forEach(type => duck.addEventListener(type, () => { down=false; }));
  duck.addEventListener('keydown', event => { if (event.key===' ' || event.key==='Enter') { event.preventDefault(); down=true; } });
  duck.addEventListener('keyup', () => { down=false; });
  const draw = now => {
    requestAnimationFrame(draw);
    if (panel.hidden || card.hidden || document.hidden) { previous=now; down=false; return; }
    const dt = previous ? Math.min((now-previous)/1000,.1) : 0; previous=now; time+=dt; distance+=60*dt;
    flame=Math.max(0,flame-dt); cooldown=Math.max(0,cooldown-dt);
    if (lift>0 || velocity<0) { lift-=velocity*dt+112.5*dt*dt; velocity+=225*dt; if (lift<=0) {lift=0;velocity=0;} }
    const crouch=down && !lift && velocity>=0;
    rect(0,0,342,142,'#a5dfff'); circle(284,37,12,'#fff36b');
    for (let x=-(distance*.12%140);x<380;x+=140) { circle(x,39,7,'#eff3ef');circle(x+10,35,10,'#eff3ef');circle(x+22,39,7,'#eff3ef'); }
    for (let x=-(distance*.23%130);x<440;x+=130) {triangle(x+44,45,71,65,'#7bb3bd');triangle(x+44,45,11,12,'#def3e7');}
    const castle=250-distance*.32%390;
    rect(castle,73,39,35,'#528e84');rect(castle-6,68,12,40,'#528e84');rect(castle+33,65,12,43,'#528e84');
    for(let i=0;i<4;i++) rect(castle-6+i*13,62,6,12,'#528e84');
    for(let x=18-distance*.48%95;x<365;x+=95) {rect(x-2,82,5,34,'#634129');triangle(x,63,15,24,'#528e84');triangle(x,75,22,28,'#528e84');}
    rect(0,116,342,26,'#8c6d31');rect(0,116,342,4,'#8cc64a');
    for(let x=-(distance%37);x<350;x+=37) rect(x,124,7,2,'#735129');
    const ox=342-distance%510;
    rect(ox,101,22,15,'#8c8e8c');rect(ox+4,98,14,4,'#bdbabd');
    for(let i=0;i<3;i++) {rect(ox+230+i*9,95,7,21,'#a56531');triangle(ox+233+i*9,92,3,5,'#de964a');}
    rect(ox+230,103,26,4,'#734521');circle(ox+95,68,5,'#fffb00');
    const x=44, feet=116-lift, y=feet-(crouch?15:28), green='#63ba5a', edge='#215931';
    triangle(x-9,feet-13-(Math.floor(time*9)%2),7,10,edge);rect(x-10,feet-9,19,5,green);
    circle(x+13,feet-(crouch?7:12),crouch?7:11,edge);circle(x+13,feet-(crouch?7:12),crouch?6:10,green);
    rect(x+7,feet-8,15,6,'#c6ebad');circle(x+24,y+(crouch?7:9),crouch?7:9,edge);circle(x+24,y+(crouch?7:9),crouch?6:8,green);
    rect(x+24,y+10,10,6,edge);rect(x+24,y+10,9,4,'#8cce73');triangle(x+19,y-3,2,7,'#ffefde');triangle(x+27,y-2,2,6,'#ffefde');
    circle(x+27,y+6,3,'white');rect(x+28,y+5,2,3,'#102010');rect(x+27,y+14,5,1,edge);rect(x+23,y+11,2,2,'#ffb6de');
    if(!crouch) {triangle(x+9,feet-25-Math.floor(time*8)%3,6,15,edge);triangle(x+9,feet-23-Math.floor(time*8)%3,4,12,'#adffff');}
    const stride=lift?0:Math.floor(time*12)%2?3:-2;
    rect(x+5+stride,feet-4,6,4,edge);rect(x+19-stride,feet-4,6,4,edge);
    if(flame) { circle(91,y+16,8,'#ff7700');circle(119,y+16,9,'#ffaa00');circle(127+Math.floor(time*30)%5,y+14,5,'#ffdd44');rect(74,y+13,52,6,'#ffdd44'); }
    rect(0,0,342,19,'#18304a');ctx.fillStyle='#bfffa5';ctx.font='10px monospace';ctx.fillText('Drachenrennen · Vorschau',6,13);
    ctx.fillStyle='white';ctx.fillText(cooldown?'Feuer...':'Feuer OK',277,13);
    rect(0,132,342,10,'#18304a');ctx.font='8px monospace';ctx.fillText('HOCH Sprung  RUNTER Ducken  MITTE Feuer',6,140);
  };
  requestAnimationFrame(draw);
});

document.querySelector("[data-accent-color]")?.addEventListener("input", event => { document.querySelector(".leap-preview")?.style.setProperty("--device-accent", event.target.value); });
