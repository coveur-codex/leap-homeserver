(() => {
  const storageKey = 'leap-theme';
  const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
  const validTheme = value => ['light', 'dark', 'system'].includes(value) ? value : 'light';
  let preference = 'light';

  try {
    preference = validTheme(localStorage.getItem(storageKey));
  } catch (_) {
    // The selector remains usable when browser storage is unavailable.
  }

  function applyTheme() {
    document.documentElement.dataset.theme = preference === 'system'
      ? (systemTheme.matches ? 'dark' : 'light')
      : preference;
  }

  // Run before the stylesheet loads to avoid flashing the light theme.
  applyTheme();
  systemTheme.addEventListener('change', applyTheme);

  document.addEventListener('DOMContentLoaded', () => {
    const selector = document.getElementById('theme-select');
    selector.value = preference;
    selector.closest('label').hidden = false;
    selector.addEventListener('change', () => {
      preference = validTheme(selector.value);
      applyTheme();
      try {
        localStorage.setItem(storageKey, preference);
      } catch (_) {
        // Keep the current selection even if it cannot be persisted.
      }
    });

    window.addEventListener('storage', event => {
      if (event.key === storageKey || event.key === null) {
        try {
          preference = validTheme(localStorage.getItem(storageKey));
          selector.value = preference;
          applyTheme();
        } catch (_) {
          // Keep the current theme if storage access was revoked.
        }
      }
    });
  });
})();
