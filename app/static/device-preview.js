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
