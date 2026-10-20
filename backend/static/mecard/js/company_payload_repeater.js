(function () {
  const payloadField = document.getElementById('id_payload');
  if (!payloadField) return;

  const formRow = payloadField.closest('.form-row');
  const repeater = document.createElement('div');
  repeater.className = 'payload-repeater';
  repeater.innerHTML = `
    <p>Map each placeholder to the data that should replace it.</p>
    <table>
      <thead><tr><th>Placeholder</th><th>Data</th><th></th></tr></thead>
      <tbody></tbody>
    </table>
    <button type="button" class="button payload-add-row">Add row</button>
    <p class="payload-repeater-error" role="alert" hidden></p>
  `;

  const rows = repeater.querySelector('tbody');
  const error = repeater.querySelector('.payload-repeater-error');

  function addRow(placeholder = '', data = '') {
    const row = document.createElement('tr');
    const placeholderCell = document.createElement('td');
    const dataCell = document.createElement('td');
    const actionCell = document.createElement('td');
    const placeholderInput = document.createElement('input');
    const dataInput = document.createElement('input');
    const removeButton = document.createElement('button');

    placeholderInput.type = 'text';
    placeholderInput.placeholder = 'placeholder';
    placeholderInput.value = placeholder.replace(/^\{\{/, '').replace(/\}\}$/, '');
    placeholderInput.setAttribute('aria-label', 'Placeholder');
    dataInput.type = 'text';
    dataInput.placeholder = 'Data';
    dataInput.value = data;
    dataInput.setAttribute('aria-label', 'Data');
    removeButton.type = 'button';
    removeButton.className = 'button';
    removeButton.textContent = 'Remove';
    removeButton.addEventListener('click', () => row.remove());

    placeholderCell.append(placeholderInput);
    dataCell.append(dataInput);
    actionCell.append(removeButton);
    row.append(placeholderCell, dataCell, actionCell);
    rows.append(row);
  }

  repeater.querySelector('.payload-add-row').addEventListener('click', () => addRow());

  let initialPayload = {};
  try {
    const parsed = JSON.parse(payloadField.value || '{}');
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      initialPayload = parsed;
    }
  } catch (_error) {
    error.textContent = 'Payload contains invalid JSON. Add rows to replace it with a valid placeholder map.';
    error.hidden = false;
  }

  Object.entries(initialPayload).forEach(([placeholder, data]) => {
    addRow(placeholder, data == null ? '' : String(data));
  });
  if (!rows.children.length) addRow();

  payloadField.hidden = true;
  if (formRow) {
    formRow.hidden = true;
    formRow.insertAdjacentElement('afterend', repeater);
  }
  else payloadField.insertAdjacentElement('afterend', repeater);

  const form = payloadField.form;
  if (form) {
    form.addEventListener('submit', () => {
      const payload = {};
      rows.querySelectorAll('tr').forEach((row) => {
        const [placeholderInput, dataInput] = row.querySelectorAll('input');
        const placeholder = placeholderInput.value.trim().replace(/^\{\{/, '').replace(/\}\}$/, '');
        if (placeholder) payload[placeholder] = dataInput.value;
      });
      payloadField.value = JSON.stringify(payload);
    });
  }
})();
