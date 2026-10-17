(() => {
  const dialog = document.getElementById('card-preview-dialog');
  const title = document.getElementById('card-preview-title');
  const status = document.getElementById('card-preview-status');
  const stage = document.getElementById('card-preview-stage');
  const frame = document.getElementById('card-preview-frame');
  if (!dialog || !title || !status || !stage || !frame) return;

  const nativeWidth = 480;
  let aspectRatio = 1.6;
  let resizeObserver;

  function fitPreview() {
    const stageWidth = Math.min(nativeWidth, stage.clientWidth || nativeWidth);
    stage.style.height = `${Math.round(stageWidth / aspectRatio)}px`;
    frame.style.width = `${nativeWidth}px`;
    frame.style.height = `${Math.round(nativeWidth / aspectRatio)}px`;
    frame.style.transform = `scale(${stageWidth / nativeWidth})`;
  }

  function closePreview() {
    if (dialog.open) dialog.close();
    frame.removeAttribute('src');
    stage.hidden = true;
    status.textContent = '';
    resizeObserver?.disconnect();
  }

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('.card-preview-trigger');
    if (!trigger) return;

    event.preventDefault();
    title.textContent = trigger.dataset.cardName || 'Card preview';
    status.textContent = 'Preparing preview…';
    stage.hidden = true;
    frame.removeAttribute('src');
    dialog.showModal();

    const ratioParts = (trigger.dataset.aspectRatio || '1.6:1').split(':').map(Number);
    aspectRatio = ratioParts.length === 2 && ratioParts[0] > 0 && ratioParts[1] > 0
      ? ratioParts[0] / ratioParts[1]
      : 1.6;
    frame.onload = () => {
      if (dialog.open) status.textContent = '';
    };
    frame.onerror = () => {
      if (dialog.open) status.textContent = 'Could not load this card design. Please try again.';
    };
    stage.hidden = false;
    status.textContent = 'Loading card design…';
    fitPreview();
    resizeObserver?.disconnect();
    resizeObserver = new ResizeObserver(fitPreview);
    resizeObserver.observe(stage);
    frame.src = trigger.dataset.previewUrl;
  });

  dialog.addEventListener('click', (event) => {
    if (event.target === dialog || event.target.closest('[data-card-preview-close]')) {
      closePreview();
    }
  });
  dialog.addEventListener('close', closePreview);
})();
