document.querySelectorAll('.device-editor').forEach(editor => {
  const list = editor.querySelector('[data-page-list]');
  const buttons = [...editor.querySelectorAll('[data-page-select]')];
  const panels = [...editor.querySelectorAll('[data-page-panel]')];
  const placeholder = editor.querySelector('[data-page-placeholder]');
  const status = editor.querySelector('[data-page-order-status]');
  const storageKey = `device-page:${location.pathname}`;
  const select = id => {
    const button = buttons.find(button => button.dataset.pageSelect === id);
    panels.forEach(panel => { panel.hidden = !panel.dataset.pagePanel.split(' ').includes(id); });
    placeholder.hidden = Boolean(button);
    buttons.forEach(candidate => {
      const active = candidate === button;
      candidate.setAttribute('aria-expanded', String(active));
      candidate.closest('li')?.classList.toggle('selected', active);
      candidate.classList.toggle('selected', active);
    });
    try { sessionStorage.setItem(storageKey, button ? id : ''); } catch { /* Storage is optional. */ }
  };
  const selectAnchor = () => {
    const target = document.getElementById(location.hash.slice(1));
    const panel = target?.closest('[data-page-panel]');
    if (panel) select(panel.dataset.pagePanel.split(' ')[0]);
  };
  let saved = '';
  try { saved = sessionStorage.getItem(storageKey) || ''; } catch { /* Storage is optional. */ }
  select(saved);
  selectAnchor();
  window.addEventListener('hashchange', selectAnchor);
  buttons.forEach(button => button.addEventListener('click', () => {
    select(button.dataset.pageSelect);
    if (window.matchMedia('(max-width: 950px)').matches) {
      editor.querySelector('#page-settings').scrollIntoView({block: 'start'});
    }
  }));

  // Reveal invalid controls before the browser tries to focus them in a hidden panel.
  editor.addEventListener('invalid', event => {
    const first = [...event.target.form.elements].find(control => control.willValidate && !control.validity.valid);
    const panel = (first || event.target).closest('[data-page-panel]');
    if (panel) select(panel.dataset.pagePanel.split(' ')[0]);
  }, true);

  const announce = row => {
    const rows = [...list.children];
    status.textContent = `${row.querySelector('[data-page-select]').textContent.trim()}: Position ${rows.indexOf(row) + 1} von ${rows.length}.`;
  };
  [...list.children].forEach(row => {
    const handle = row.querySelector('[data-page-handle]');
    handle.hidden = false;
    handle.addEventListener('keydown', event => {
      if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'ArrowUp' && row.previousElementSibling) list.insertBefore(row, row.previousElementSibling);
      if (event.key === 'ArrowDown' && row.nextElementSibling) list.insertBefore(row.nextElementSibling, row);
      if (event.key === 'Home') list.prepend(row);
      if (event.key === 'End') list.append(row);
      handle.focus();
      announce(row);
    });
    let pointer = null;
    let originalOrder = [];
    handle.addEventListener('pointerdown', event => {
      if (!event.isPrimary || event.button !== 0) return;
      pointer = event.pointerId;
      originalOrder = [...list.children];
      handle.setPointerCapture(pointer);
      row.classList.add('dragging');
    });
    handle.addEventListener('pointermove', event => {
      if (event.pointerId !== pointer) return;
      const others = [...list.children].filter(candidate => candidate !== row);
      const next = others.find(candidate => {
        const rect = candidate.getBoundingClientRect();
        return event.clientY < rect.top + rect.height / 2;
      });
      list.insertBefore(row, next || null);
      handle.setPointerCapture(pointer);
      if (event.clientY < 60) window.scrollBy(0, -16);
      if (event.clientY > window.innerHeight - 60) window.scrollBy(0, 16);
    });
    const finish = cancelled => {
      if (pointer === null) return;
      pointer = null;
      if (cancelled) originalOrder.forEach(original => list.append(original));
      row.classList.remove('dragging');
      handle.focus({preventScroll: true});
      announce(row);
    };
    handle.addEventListener('pointerup', () => finish(false));
    handle.addEventListener('pointercancel', () => finish(true));
    handle.addEventListener('lostpointercapture', () => finish(false));
  });

  // Both existing save actions use the same room activation state.
  const roomToggle = list.querySelector('input[name="page_ids"][value="room"]');
  const roomEnabled = editor.querySelector('input[form="room-settings"][name="enabled"]');
  if (roomToggle && roomEnabled) {
    roomToggle.addEventListener('change', () => { roomEnabled.checked = roomToggle.checked; });
    roomEnabled.addEventListener('change', () => { roomToggle.checked = roomEnabled.checked; });
  }
});
