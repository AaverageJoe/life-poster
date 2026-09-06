(function () {
  const $ = id => document.getElementById(id);
  const pad = $('pad');
  const ctx = pad.getContext('2d', { willReadFrequently: true });
  const msg = $('drawmsg');

  // white background so exported PNG matches the panel
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, pad.width, pad.height);

  let color = '#000000';
  let size = 8;
  let erasing = false;
  let drawing = false;
  let last = null;
  const undo = [];

  function snapshot() {
    if (undo.length > 20) undo.shift();
    undo.push(ctx.getImageData(0, 0, pad.width, pad.height));
  }

  function pos(e) {
    const r = pad.getBoundingClientRect();
    return {
      x: (e.clientX - r.left) * (pad.width / r.width),
      y: (e.clientY - r.top) * (pad.height / r.height)
    };
  }

  function stroke(a, b) {
    ctx.strokeStyle = erasing ? '#ffffff' : color;
    ctx.lineWidth = erasing ? size * 2 : size;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }

  pad.addEventListener('pointerdown', e => {
    pad.setPointerCapture(e.pointerId);
    snapshot();
    drawing = true;
    last = pos(e);
    stroke(last, { x: last.x + 0.01, y: last.y });
  });
  pad.addEventListener('pointermove', e => {
    if (!drawing) return;
    const p = pos(e);
    stroke(last, p);
    last = p;
  });
  function end() {
    if (!drawing) return;
    drawing = false;
    if ($('autopreview').checked) sendPreview();
  }
  pad.addEventListener('pointerup', end);
  pad.addEventListener('pointercancel', end);
  pad.addEventListener('pointerleave', end);

  $('palette').addEventListener('click', e => {
    const sw = e.target.closest('.sw');
    if (!sw) return;
    color = sw.dataset.color;
    erasing = false;
    document.querySelectorAll('.sw').forEach(s => s.classList.toggle('sel', s === sw));
    $('eraser').classList.remove('sel');
  });
  $('size').addEventListener('input', e => { size = +e.target.value; });
  $('eraser').addEventListener('click', () => {
    erasing = !erasing;
    $('eraser').classList.toggle('sel', erasing);
  });
  $('undo').addEventListener('click', () => {
    const img = undo.pop();
    if (img) ctx.putImageData(img, 0, 0);
  });
  $('clear').addEventListener('click', () => {
    snapshot();
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, pad.width, pad.height);
  });

  let previewTimer = null;
  function sendPreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      msg.textContent = 'rendering preview…';
      try {
        const r = await fetch('/draw/preview', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image: pad.toDataURL('image/png') })
        });
        const blob = await r.blob();
        $('preview').src = URL.createObjectURL(blob);
        msg.textContent = 'preview updated (not sent to panel)';
      } catch (e) { msg.textContent = 'preview failed'; }
    }, 350);
  }
  $('previewbtn').addEventListener('click', sendPreview);

  $('pushbtn').addEventListener('click', async () => {
    if (!confirm('Send this drawing to the e-ink panel? (~35 second refresh)')) return;
    msg.textContent = 'pushing to panel…';
    $('pushbtn').disabled = true;
    try {
      const r = await fetch('/draw/push', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: pad.toDataURL('image/png') })
      });
      msg.textContent = r.ok ? 'sent — the panel is refreshing now' : 'push failed';
    } catch (e) {
      msg.textContent = 'push failed: ' + e;
    } finally {
      $('pushbtn').disabled = false;
    }
  });
})();
