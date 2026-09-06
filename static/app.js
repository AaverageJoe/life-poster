// Poll display state and keep the side panel + preview fresh.
(function () {
  const $ = id => document.getElementById(id);
  const preview = $('preview');
  let lastShown = 0;

  async function tick() {
    try {
      const r = await fetch('/api/state', { cache: 'no-store' });
      if (!r.ok) return;
      const s = await r.json();
      if ($('s-mode')) $('s-mode').textContent = s.mode;
      if ($('s-device')) $('s-device').textContent = s.device;
      if ($('s-busy')) $('s-busy').textContent = s.busy ? 'refreshing…' : 'idle';
      if ($('s-source')) $('s-source').textContent = s.last_source || '—';
      if (preview && s.last_shown_at && s.last_shown_at !== lastShown) {
        lastShown = s.last_shown_at;
        preview.src = '/api/preview.png?t=' + Date.now();
      }
    } catch (e) { /* offline: ignore */ }
  }

  setInterval(tick, 3000);
  tick();
})();
