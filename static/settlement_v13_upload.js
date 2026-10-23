'use strict';
const form = document.getElementById('upload-form');
form.addEventListener('submit', (event) => {
  const sales = [...form.querySelectorAll('input[name^="sales_"]')].filter(x => x.files.length);
  const vendors = [...form.querySelectorAll('input[name^="vendor_"]')].filter(x => x.files.length);
  let error = '';
  if (!sales.length || !vendors.length) error = '판매일보와 거래처 정산서를 각각 최소 한 개 선택하세요.';
  if (sales.some(x => !form.elements[x.name.replace('sales_', 'branch_')].value)) error = '판매일보에 해당하는 실제 지점을 선택하세요.';
  const files = [...sales, ...vendors].flatMap(x => [...x.files]);
  if (files.some(x => x.size > 10 * 1024 * 1024)) error = '파일당 최대 10MB입니다.';
  if (files.reduce((n, x) => n + x.size, 0) > 40 * 1024 * 1024 - 65536) error = '파일 합계는 40MB 미만이어야 합니다.';
  if (error) { event.preventDefault(); document.getElementById('upload-status').textContent = error; return; }
  document.getElementById('compare-button').disabled = true;
  document.getElementById('upload-status').textContent = '정산 대조 중입니다. 완료되면 결과가 열립니다.';
});
window.addEventListener('pageshow', () => { document.getElementById('compare-button').disabled = false; });
