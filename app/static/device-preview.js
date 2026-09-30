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
  const cards = [...preview.querySelectorAll("[data-preview-card]")];
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
  show(0);
});

document.querySelectorAll('input[name="knowledge_source"]').forEach((input) => {
  input.addEventListener("change", () => {
    const label = document.querySelector("[data-knowledge-source-label]");
    if (label) label.textContent = input.value === "miniklexikon" ? "MiniKlexikon" : "Klexikon";
  });
});
