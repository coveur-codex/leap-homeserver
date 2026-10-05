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
  const image = card.querySelector('[data-pet-image]');
  const fallback = card.querySelector('[data-pet-fallback]');
  let animation = 'idle', frame = 0, lastFrame = 0, actionUntil = 0;
  card.querySelectorAll('[data-game-open]').forEach(button => button.addEventListener('click', () => {
    menu.hidden = true;
    pet.hidden = button.dataset.gameOpen !== 'pet';
    snake.hidden = button.dataset.gameOpen !== 'snake';
    animation = 'idle'; actionUntil = 0; frame = 0;
  }));
  card.querySelectorAll('[data-game-back]').forEach(button => button.addEventListener('click', () => {
    menu.hidden = false; pet.hidden = snake.hidden = true;
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
