(function () {
  const openLink = document.querySelector('[data-company-create-open]');
  const dialog = document.getElementById('company-create-dialog');
  const form = document.getElementById('company-create-form');

  if (!openLink || !dialog || !form) return;

  const input = document.getElementById('company-website-url');
  const submitButton = document.getElementById('company-create-submit');
  const submitLabel = document.getElementById('company-create-submit-label');
  const errorBox = document.getElementById('company-create-error');
  const loadingPanel = document.getElementById('company-create-loading');
  const progressMessage = document.getElementById('company-create-progress');
  const inputGroup = form.querySelector('.field-group');
  const actions = form.querySelector('.company-create-dialog__actions');
  const closeButtons = dialog.querySelectorAll('[data-company-create-close]');
  const defaultSubmitLabel = submitLabel.textContent;
  const progressMessages = [
    'Connecting to the website…',
    'Finding the company’s key details…',
    'Looking for logos and social links…',
    'Bringing the brand information together…',
  ];
  let progressTimer;
  let isSubmitting = false;

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
  }

  openLink.addEventListener('click', function (event) {
    event.preventDefault();
    dialog.showModal();
    input.focus();
  });

  closeButtons.forEach((button) => {
    button.addEventListener('click', () => {
      if (!isSubmitting) dialog.close();
    });
  });

  dialog.addEventListener('cancel', function (event) {
    if (isSubmitting) event.preventDefault();
  });

  dialog.addEventListener('close', function () {
    clearInterval(progressTimer);
    form.reset();
    errorBox.hidden = true;
    loadingPanel.hidden = true;
    inputGroup.hidden = false;
    actions.hidden = false;
    isSubmitting = false;
    closeButtons.forEach((button) => { button.disabled = false; });
    submitButton.disabled = false;
    submitLabel.textContent = defaultSubmitLabel;
  });

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    errorBox.hidden = true;
    inputGroup.hidden = true;
    actions.hidden = true;
    loadingPanel.hidden = false;
    progressMessage.textContent = progressMessages[0];
    isSubmitting = true;
    closeButtons.forEach((button) => { button.disabled = true; });
    submitButton.disabled = true;
    submitLabel.textContent = 'Working…';
    let progressIndex = 0;
    progressTimer = window.setInterval(() => {
      progressIndex = (progressIndex + 1) % progressMessages.length;
      progressMessage.textContent = progressMessages[progressIndex];
    }, 3200);

    try {
      const response = await fetch('/api/companies/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCookie('csrftoken'),
        },
        credentials: 'same-origin',
        body: JSON.stringify({ website_url: input.value.trim() }),
      });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Extraction failed. Please check the URL and try again.');
      }
      if (!data.id) {
        throw new Error('The company was created, but its details could not be opened.');
      }

      window.location.href = `/admin/api/company/${encodeURIComponent(data.id)}/change/`;
    } catch (error) {
      clearInterval(progressTimer);
      isSubmitting = false;
      loadingPanel.hidden = true;
      inputGroup.hidden = false;
      actions.hidden = false;
      closeButtons.forEach((button) => { button.disabled = false; });
      errorBox.textContent = error.message;
      errorBox.hidden = false;
      submitButton.disabled = false;
      submitLabel.textContent = defaultSubmitLabel;
    }
  });
})();
