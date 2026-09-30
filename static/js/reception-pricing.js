/* Shared, deterministic catalogue matching. No sample prices or network access. */
(function(root){
'use strict';
const norm=x=>String(x??'').normalize('NFKC').toLowerCase().replace(/[\s_-]+/g,'');
const capacity=x=>norm(x).replace(/gb$/,'g').replace(/tb$/,'t');
const day=x=>typeof x==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(x)&&!isNaN(Date.parse(x))&&new Date(x+'T00:00:00Z').toISOString().slice(0,10)===x;
const money=x=>Number.isSafeInteger(x)&&x>=0&&x<=100000000;
function valid(r,kind){
 return r&&['SKT','KT','LG U+'].includes(r.carrier)&&['model','capacity','source','from','to'].every(k=>typeof r[k]==='string'&&r[k].trim()&&r[k].length<=200)&&day(r.from)&&day(r.to)&&r.from<=r.to&&
 (kind==='price'?money(r.price):['network','joinType','plan','contract'].every(k=>typeof r[k]==='string'&&r[k].length<=200)&&['신규가입','번호이동','기기변경'].includes(r.joinType)&&['12','24'].includes(r.contract)&&r.plan.trim()&&money(r.subsidy)&&money(r.price)&&r.subsidy<=r.price);
}
function clean(r,kind){const keys=kind==='price'?['carrier','model','capacity','source','from','to','price']:['carrier','model','capacity','source','from','to','price','subsidy','network','joinType','plan','contract'];return Object.fromEntries(keys.map(k=>[k,r[k]]));}
function decode(data){
 if(!data||![1,2].includes(data.version)||!Array.isArray(data.rates)||data.rates.length>5000)throw Error('기준표 형식 오류');
 const prices=data.version===2?data.prices:[];
 if(!Array.isArray(prices)||prices.length>5000||!prices.every(r=>valid(r,'price'))||!data.rates.every(r=>valid(r,'rate')))throw Error('금액·기간·출처를 확인해주세요.');
 return {version:2,prices:prices.map(r=>clean(r,'price')),rates:data.rates.map(r=>clean(r,'rate'))};
}
function latest(rows,field){if(!rows.length)return null;let from=rows.map(r=>r.from).sort().at(-1);let found=rows.filter(r=>r.from===from);if(new Set(found.map(r=>r[field])).size>1)return {conflict:true};return found[0];}
function resolve(data,c){
 const match=r=>r.carrier===c.carrier&&norm(r.model)===norm(c.model)&&capacity(r.capacity)===capacity(c.capacity)&&r.from<=c.date&&r.to>=c.date;
 // Explicit device prices take precedence over prices attached to a subsidy row.
 const explicit=data.prices.filter(match);const legacy=data.rates.filter(match);
 const price=latest(explicit.length?explicit:legacy,'price');
 const subsidy=latest(legacy.filter(r=>['network','joinType','plan','contract'].every(k=>norm(r[k])===norm(c[k]))),'subsidy');
 return {price,subsidy};
}
const api={norm,capacity,valid,decode,resolve};if(typeof module==='object'&&module.exports)module.exports=api;else root.ReceptionPricing=api;
})(typeof globalThis==='object'?globalThis:this);
