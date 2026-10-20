// Pack independent cards into the available grid gaps, preserving DOM/tab order.
// CSS columns remain the fallback when ResizeObserver is unavailable.
document.querySelectorAll('.device-settings').forEach(settings => {
  if (typeof ResizeObserver === 'undefined') return;
  const cards = [...settings.children].filter(child => child.tagName === 'SECTION');
  let pending = false;
  const measure = () => {
    pending = false;
    const sizes = cards.map(card => Math.ceil(card.getBoundingClientRect().height + 16));
    cards.forEach((card, index) => {
      const value = String(sizes[index]);
      if (card.style.getPropertyValue('--settings-rows') !== value) {
        card.style.setProperty('--settings-rows', value);
      }
    });
  };
  const schedule = () => {
    if (!pending) { pending = true; requestAnimationFrame(measure); }
  };
  settings.classList.add('device-settings-packed');
  measure();
  const observer = new ResizeObserver(schedule);
  cards.forEach(card => observer.observe(card));
});
