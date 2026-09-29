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
