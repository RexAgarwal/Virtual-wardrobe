(function(){
var APP=__APP__,TOKEN=__TOKEN__;
function q(s){return document.querySelector(s)}
function meta(n){var e=q('meta[property="'+n+'"],meta[name="'+n+'"],meta[itemprop="'+n+'"]');return e&&e.content?e.content:''}
function txt(s){var e=q(s);return e?(e.getAttribute('content')||e.textContent||'').replace(/\s+/g,' ').trim():''}
var f={name:'',price:'',currency:'',image:''};
function first(v){if(Array.isArray(v))return first(v[0]);if(v&&typeof v==='object')return v.url||v.contentUrl||'';return v||''}
function walk(n){
if(Array.isArray(n)){n.forEach(walk);return}
if(!n||typeof n!=='object')return;
var t=n['@type'];
if(t==='Product'||(Array.isArray(t)&&t.indexOf('Product')>-1)){
f.name=f.name||n.name||'';
f.image=f.image||first(n.image);
var o=Array.isArray(n.offers)?n.offers[0]:n.offers;
if(o){f.price=f.price||o.price||o.lowPrice||'';f.currency=f.currency||o.priceCurrency||''}
}
['@graph','mainEntity'].forEach(function(k){if(n[k])walk(n[k])});
}
Array.prototype.forEach.call(document.querySelectorAll('script[type="application/ld+json"]'),function(s){try{walk(JSON.parse(s.textContent))}catch(e){}});
function amazonPrice(){
var sels=['.priceToPay .a-offscreen','.apex-pricetopay-value .a-offscreen','#corePrice_feature_div .a-price:not(.a-text-price) .a-offscreen','#corePrice_feature_div .a-offscreen'];
for(var i=0;i<sels.length;i++){
var els=document.querySelectorAll(sels[i]);
for(var j=0;j<els.length;j++){var t=(els[j].textContent||'').replace(/\s+/g,' ').trim();if(/\d/.test(t))return t}
}
var p=q('.priceToPay,.apex-pricetopay-value');
if(p){
var sy=p.querySelector('.a-price-symbol'),w=p.querySelector('.a-price-whole'),fr=p.querySelector('.a-price-fraction');
if(w){return (sy?sy.textContent:'')+w.textContent.replace(/[^\d,]/g,'')+(fr?'.'+fr.textContent.replace(/\D/g,''):'')}
}
return '';
}
if(q('#productTitle')){
f.name=f.name||txt('#productTitle');
f.price=f.price||amazonPrice();
var li=q('#landingImage,#imgBlkFront');
if(li&&!f.image){
var big=li.getAttribute('data-old-hires');
if(!big){try{big=Object.keys(JSON.parse(li.getAttribute('data-a-dynamic-image')||'{}')).pop()}catch(e){}}
f.image=big||li.src;
}
}
f.name=f.name||meta('og:title')||meta('twitter:title')||document.title;
f.image=f.image||meta('og:image')||meta('twitter:image');
f.price=f.price||meta('product:price:amount')||meta('og:price:amount');
f.currency=f.currency||meta('product:price:currency')||meta('og:price:currency');
var form=document.createElement('form');
form.method='POST';form.action=APP+'/watchlist/import/';form.target='_blank';form.style.display='none';
var data={token:TOKEN,url:location.href,name:f.name,price:String(f.price||''),currency:f.currency,image:f.image};
Object.keys(data).forEach(function(k){var i=document.createElement('input');i.type='hidden';i.name=k;i.value=data[k]||'';form.appendChild(i)});
document.body.appendChild(form);
form.submit();
})();
