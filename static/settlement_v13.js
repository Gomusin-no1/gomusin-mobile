'use strict';
const DATA = JSON.parse(document.getElementById('settlement-data').textContent);
const ST = {match:{cls:'ok',label:'일치'}, more:{cls:'more',label:'더 받음'}, less:{cls:'less',label:'덜 받음'}};
let vi = 0, fStatus = '', openKey = null;
const $ = s => document.querySelector(s);
const won = v => (v==null||v==='-') ? '-' : Number(v).toLocaleString('ko-KR');
const sgn = v => (v>0?'+':'') + Number(v).toLocaleString('ko-KR');
const esc = s => String(s==null?'':s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function tabs(){
  $('#tabs').innerHTML = DATA.map((v,i)=>`<button class="tab ${i===vi?'on':''}" data-i="${i}">${esc(v.label)} <span style="opacity:.6">${v.month}</span></button>`).join('');
  document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{vi=+b.dataset.i; fStatus=''; openKey=null; render();});
}
function cards(){
  const s = DATA[vi].summary;
  const c = [
    {k:'', cls:'', t:'총액 차이', v:sgn(s.total_diff)+'원', sub:`매칭 ${s.matched}건 · 정산서 ${won(s.vendor_total)} / 판매일보 ${won(s.sales_total)}`},
    {k:'match', cls:'ok', t:'일치', v:s.match+'건', sub:'금액이 정확히 맞음'},
    {k:'more', cls:'more', t:'정산서가 더 줌', v:s.more+'건', sub:sgn(s.more_amount)+'원'},
    {k:'less', cls:'less', t:'정산서가 덜 줌', v:s.less+'건', sub:sgn(s.less_amount)+'원 · 확인 필요'},
  ];
  $('#cards').innerHTML = c.map(x=>`<button type="button" class="card ${x.cls} ${fStatus===x.k&&x.k?'sel':''}" data-k="${x.k}"><div class="k">${x.t}</div><div class="v">${x.v}</div><div class="s">${x.sub}</div></button>`).join('');
  document.querySelectorAll('.card').forEach(el=>el.onclick=()=>{fStatus = (fStatus===el.dataset.k)?'':el.dataset.k; openKey=null; render();});
}
function stores(){
  const set = [...new Set([...DATA[vi].items,...DATA[vi].unmatched_sales].map(x=>x.store))];
  const sel = $('#fStore'), cur = sel.value;
  sel.innerHTML = '<option value="">전체 매장</option>' + set.map(s=>`<option ${s===cur?'selected':''}>${esc(s)}</option>`).join('');
}
const ORDER = {less:0, more:1, match:2};
function rows(){
  const q = $('#fq').value.trim(), st = $('#fStore').value;
  let items = DATA[vi].items.map((x,i)=>({...x,_i:i}))
    .filter(x=>!fStatus || x.status===fStatus)
    .filter(x=>!st || x.store===st)
    .filter(x=>!q || [x.name,x.seller,x.phone,x.device].join(' ').includes(q));
  items.sort((a,b)=>ORDER[a.status]-ORDER[b.status] || a.date.localeCompare(b.date));
  let h = `<div class="row head"><div>상태</div><div>고객</div><div class="c-store">매장 · 판매자</div><div class="c-date">개통일</div><div class="num c-sales">판매일보</div><div class="num c-vendor">정산서</div><div class="num">차이</div></div>`;
  if(!items.length) h += `<div class="empty">조건에 맞는 건이 없습니다.</div>`;
  for(const x of items){
    const s = ST[x.status], key = vi+'-'+x._i, open = key===openKey;
    h += `<div class="row ${s.cls} ${open?'open':''}" data-key="${key}" tabindex="0" role="button" aria-expanded="${open}" aria-controls="d-${key}">
      <div class="st"><span class="badge"><span class="dot"></span>${s.label}</span>${x.flag?'<small>매칭 확인</small>':''}</div>
      <div class="who"><b>${esc(x.name)}</b><small>${esc(x.kind)}</small></div>
      <div class="c-store">${esc(x.store)}<small style="display:block;color:var(--sub);font-size:12px">${esc(x.seller||'')}</small></div>
      <div class="c-date">${esc(x.date)}</div>
      <div class="num c-sales">${won(x.sales_cmp)}</div>
      <div class="num c-vendor">${won(x.vendor_cmp)}</div>
      <div class="num diff ${s.cls}"><b>${x.diff===0?'0':sgn(x.diff)}</b></div>
    </div>
    <div class="detail ${open?'show':''}" id="d-${key}">${open?detail(x):''}</div>`;
  }
  $('#table').innerHTML = h;
  document.querySelectorAll('.row[data-key]').forEach(el=>{ const toggle=()=>{const key=el.dataset.key; openKey = (openKey===key)?null:key; rows(); document.querySelector('[data-key=\"'+key+'\"]')?.focus({preventScroll:true});}; el.onclick=toggle; el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle();}}; });
}
function detail(x){
  const s = ST[x.status];
  const big = x.status==='match' ? '맞습니다' : (x.status==='more' ? `정산서가 ${won(Math.abs(x.diff))}원 더 줬어요` : `정산서가 ${won(Math.abs(x.diff))}원 덜 줬어요`);
  let causes = '';
  if(x.causes && x.causes.length){
    causes = x.causes.map(c=>{
      const cls = (c.category==='매칭' || c.amount===0) ? 'info' : (c.amount>0 ? 'more' : '');
      return `<div class="cause ${cls}"><span class="tag">${esc(c.category)}${c.confident?'':' · 추정'}</span>${esc(c.text)}</div>`;
    }).join('');
  } else causes = `<div class="cause info" style="border-color:var(--ok);background:var(--ok-bg)"><span class="tag">일치</span>판매일보와 정산서 금액이 같습니다.</div>`;
  const icon = {ok:'✓', warn:'!', bad:'✕'};
  const checks = (x.checks||[]).map(c=>`<div class="check"><span class="ic ${c.status}">${icon[c.status]}</span><b>${esc(c.name)}</b><span>${esc(c.text)}</span></div>`).join('');

  // 항목별 대조
  let rowsH = '';
  if(x.rebate_vendor!=null){
    const ok = !x.rebate_diff;
    rowsH += `<tr class="${ok?'r-ok':'r-bad'}"><td>리베이트(R/B) ${won(x.rebate_sale)}</td><td>리베이트 ${won(x.rebate_vendor)}</td><td class="n">${ok?'':sgn(x.rebate_diff)}</td><td class="res">${ok?'맞음':'다름'}</td></tr>`;
  }
  const mm = x.memo_match;
  if(mm){
    for(const p of mm.pairs) rowsH += `<tr class="r-ok"><td>${esc(p[0].join(' + '))}</td><td>${esc(p[1].join(' + '))}</td><td class="n">${sgn(p[2])}</td><td class="res">맞음</td></tr>`;
    for(const v of mm.vendor_only) rowsH += `<tr class="${v.amount>0?'r-plus':'r-bad'}"><td>—</td><td>${esc(v.label)}</td><td class="n">${sgn(v.amount)}</td><td class="res">정산서에만</td></tr>`;
    for(const m of mm.memo_only) rowsH += `<tr class="${m.amount>0?'r-bad':'r-plus'}"><td>${esc(m.text)}</td><td>—</td><td class="n">${sgn(m.amount)}</td><td class="res">판매일보에만</td></tr>`;
  } else {
    for(const v of (x.vendor_items||[])) rowsH += `<tr><td></td><td>${esc(v.label)}</td><td class="n">${sgn(v.amount)}</td><td class="res"></td></tr>`;
  }
  const table = `<table class="cmp"><thead><tr><th>판매일보(메모)</th><th>정산서</th><th style="text-align:right">금액</th><th>결과</th></tr></thead><tbody>${rowsH||'<tr><td colspan="4">항목 없음</td></tr>'}</tbody></table>
    ${mm?'':`<div class="ref">판매일보 메모 금액 합계가 구두·차감금액과 달라 항목별로 짝짓지 못했습니다. 아래 메모를 참고하세요.</div>`}`;
  return `
  <div class="verdict ${s.cls}"><span class="big">${big}</span>
    <span class="meta">판매일보 ${won(x.sales_cmp)}원 · 정산서 ${won(x.vendor_cmp)}원 · ${esc(x.store)} ${esc(x.seller||'')} · ${esc(x.device)} · ${esc(x.phone)}</span></div>
  <div class="grid2">
    <div class="box"><h4>예상 원인</h4>${causes}</div>
    <div class="box"><h4>점검 (부가 유치 · 개통 조건)</h4>${checks}</div>
  </div>
  <div class="box" style="margin-top:12px"><h4>항목별 대조 — 맞는 것과 다른 것</h4><div class="scroll">${table}</div></div>
  <div class="grid2" style="margin-top:12px">
    <div class="box"><h4>판매일보 메모</h4><div class="memo">${esc(x.sale_memo)||'메모 없음'}</div></div>
    <div class="box"><h4>차액 계산에서 뺀 항목 (참고)</h4><div class="ref" style="margin:0">판매일보: ${esc(x.excluded_sale)}<br>정산서: ${esc(x.excluded_vendor)}</div></div>
  </div>`;
}
function extra(){
  const v = DATA[vi], st = $('#fStore').value;
  const sales = v.unmatched_sales.filter(x=>!st || x.store===st);
  let h = '';
  if(st && v.unmatched_vendor.length) h += '<p class=\"lead\">아래 정산서 미매칭·매장 단위 항목은 소속 매장이 확정되지 않아 전체를 표시합니다.</p>';
  if(sales.length){
    h += `<h3>판매일보에만 있는 건 (${sales.length})</h3><div class="scroll"><table class="mini"><tr><th>매장</th><th>판매자</th><th>개통일</th><th>고객</th><th>기종</th><th style="text-align:right">판매일보 금액</th><th>추정 사유</th></tr>` +
      sales.map(s=>`<tr><td>${esc(s.store)}</td><td>${esc(s.seller||'')}</td><td>${esc(s.date)}</td><td>${esc(s.name)}</td><td>${esc(s.device)}</td><td style="text-align:right">${won(s.sales_cmp)}</td><td>${esc(s.reason)}</td></tr>`).join('') + `</table></div>`;
  }
  if(v.unmatched_vendor.length){
    h += `<h3 style="margin-top:18px">정산서에만 있는 줄 · 매장 단위 항목 (${v.unmatched_vendor.length})</h3><div class="scroll"><table class="mini"><tr>${v.uv_headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr>` +
      v.unmatched_vendor.map(r=>`<tr>${r.map(c=>`<td>${typeof c==='number'?won(c):esc(c)}</td>`).join('')}</tr>`).join('') + `</table></div>`;
  }
  $('#extra').innerHTML = h;
}
function render(){ tabs(); cards(); stores(); rows(); extra(); }
$('#fStore').onchange = ()=>{openKey=null; rows(); extra();};
$('#fq').oninput = ()=>{openKey=null; rows();};
render();
