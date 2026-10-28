(() => {
  const root = document.querySelector('[data-game-status-url]');
  const connection = document.getElementById('game-status-connection');
  if (!root || !connection) return;
  async function refresh() {
    if (!document.hidden) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 5000);
      try {
        const response = await fetch(root.dataset.gameStatusUrl, {
          cache: 'no-store', signal: controller.signal,
        });
        if (!response.ok) throw new Error('Status nicht verfügbar');
        // HTML is rendered by the same escaped Jinja template as the initial page.
        root.innerHTML = await response.text();
        connection.textContent = 'Automatische Aktualisierung alle fünf Sekunden.';
      } catch (_) {
        connection.textContent = 'Verbindung unterbrochen. Der letzte Stand bleibt sichtbar; erneuter Versuch folgt.';
      } finally {
        clearTimeout(timeout);
      }
    }
    setTimeout(refresh, 5000); // One request at a time, including slow servers.
  }
  setTimeout(refresh, 5000);
})();
