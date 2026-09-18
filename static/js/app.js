const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
const num=v=>Number(String(v||0).replace(/[^0-9-]/g,''))||0, won=v=>Math.round(v).toLocaleString('ko-KR')+'원';
function addDays(s,n){if(!s)return'';const d=new Date(s+'T00:00:00');d.setDate(d.getDate()+n);return d.toISOString().slice(0,10)}
function addMonths(s,n){if(!s)return'';const d=new Date(s+'T00:00:00'),day=d.getDate();d.setDate(1);d.setMonth(d.getMonth()+n);const last=new Date(d.getFullYear(),d.getMonth()+1,0).getDate();d.setDate(Math.min(day,last));return d.toISOString().slice(0,10)}
function ruleDate(date,rule){if(rule.startsWith('D+'))return addDays(date,+rule.slice(2));if(rule.startsWith('M+'))return addMonths(date,+rule.slice(2));return''}
function refreshDates(){const d=$('#openingDate');if(!d)return;const plan=$('#planDue');if(plan)plan.value=addDays(d.value,183);$$('.addon-row').forEach(r=>{const rule=$('.addon-rule',r),due=$('.addon-due',r);if(rule&&due)due.value=ruleDate(d.value,rule.value)})}
function refreshMoney(){if(!$('#rebate'))return;const base=num($('#rebate').value)+num($('#verbal').value)-num($('#deduct').value)-num($('#support').value), transfer=$('#openingType')&&$('#openingType').value==='번호이동'?800:0, settlement=base-transfer, tax=Math.round(settlement*.133), sim=$('#simPaymentType')&&$('#simPaymentType').value==='선납'?7700:0, margin=settlement-tax-num($('#payback').value)-sim;if($('#transferFeeOut'))$('#transferFeeOut').value=won(transfer);$('#settlementOut').textContent=won(settlement);$('#taxOut').textContent=won(tax);$('#marginOut').textContent=won(margin)}
document.addEventListener('input',e=>{if(e.target.matches('.money-input'))refreshMoney();if(e.target.matches('#openingDate'))refreshDates()});document.addEventListener('change',e=>{if(e.target.matches('.addon-rule'))refreshDates();if(e.target.matches('#openingType,#simPaymentType'))refreshMoney()});
document.addEventListener('click',async e=>{if(e.target.matches('[data-menu]'))document.body.classList.toggle('menu-open');if(e.target.id==='addAddon'){const box=$('#addons'),row=$('.addon-row',box).cloneNode(true);$('input[name="addon_name[]"]',row).value='';box.append(row);refreshDates()}if(e.target.matches('.remove-addon')){const rows=$$('.addon-row');if(rows.length>1)e.target.closest('.addon-row').remove()}if(e.target.id==='stockLookup'){const serial=$('#serial').value.trim(),state=$('#stockState');if(!serial)return;state.textContent='조회 중...';try{const r=await fetch('/api/inventory/'+encodeURIComponent(serial));const x=await r.json();if(!x.ok)throw 0;$('#device').value=x.model;$('#storage').value=x.capacity;$('#color').value=x.color;$('#manufacturer').value=x.manufacturer;$('#partnerId').value=x.partner_id||'';$('#device').dispatchEvent(new Event('input',{bubbles:true}));state.textContent=`${x.status} · ${x.partner||'거래처 없음'} · 재고 자동연동 완료`;state.classList.add('ok')}catch{state.textContent='해당 일련번호를 찾지 못했습니다. 직접 입력하거나 재고등록을 확인하세요.';state.classList.remove('ok')}}});refreshDates();refreshMoney();


// Global customer search: press "/" from any screen to focus.
document.addEventListener('keydown',e=>{
  const tag=(document.activeElement&&document.activeElement.tagName)||'';
  if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(tag)){
    const input=document.getElementById('global-customer-search');
    if(input){e.preventDefault();input.focus();input.select()}
  }
});

// Keep the sidebar compact: only one work category is expanded at a time.
document.querySelectorAll('.unified-nav .nav-section').forEach(section=>{
  section.addEventListener('toggle',()=>{
    if(!section.open)return;
    document.querySelectorAll('.unified-nav .nav-section').forEach(other=>{
      if(other!==section)other.open=false;
    });
  });
});
