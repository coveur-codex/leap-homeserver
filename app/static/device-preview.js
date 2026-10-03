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
