(() => {
  const form = document.querySelector('#document-capture-form');
  if (!form) return;
  const inputs = [...form.querySelectorAll('input[type=file]')];
  const preview = document.querySelector('#document-preview');
  const image = document.querySelector('#document-image-preview');
  const pdf = document.querySelector('#document-pdf-info');
  const info = document.querySelector('#document-file-info');
  const message = document.querySelector('#document-capture-message');
  const save = document.querySelector('#document-save');
  let objectUrl;
  const clearPreview = () => {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = undefined;
    image.removeAttribute('src'); image.hidden = true;
    preview.hidden = true; pdf.hidden = true;
  };
  for (const input of inputs) input.addEventListener('change', () => {
    if (!input.files.length) return;
    for (const other of inputs) if (other !== input) other.value = '';
    clearPreview(); message.textContent = '';
    const file = input.files[0];
    const supported = ['application/pdf', 'image/jpeg', 'image/png', 'image/webp'];
    if (!supported.includes(file.type) || !file.size || file.size > 10 * 1024 * 1024) {
      input.value = '';
      message.textContent = '10MB 이하의 PDF, JPG, PNG, WEBP 파일을 선택해 주세요. HEIC 사진은 JPG로 변환해 주세요.';
      return;
    }
    info.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)}MB`;
    preview.hidden = false;
    if (file.type === 'application/pdf') pdf.hidden = false;
    else {
      objectUrl = URL.createObjectURL(file); image.src = objectUrl; image.hidden = false;
    }
  });
  document.querySelector('#document-clear').addEventListener('click', () => {
    inputs.forEach(input => { input.value = ''; }); clearPreview(); message.textContent = '';
  });
  form.addEventListener('submit', event => {
    if (!inputs.some(input => input.files.length)) {
      event.preventDefault(); message.textContent = '촬영하거나 파일을 선택한 뒤 저장해 주세요.'; return;
    }
    save.disabled = true; save.textContent = '서류 저장 중…';
  });
  window.addEventListener('pageshow', () => { save.disabled = false; save.textContent = '이 고객에게 서류 저장'; });
  window.addEventListener('pagehide', clearPreview);
})();
