async function copyConfig(name){const r=await fetch('/devices/'+encodeURIComponent(name)+'/config');await navigator.clipboard.writeText(await r.text());alert('Client JSON copied to clipboard.');}

const subscriptionBaseUrl=document.querySelector('meta[name="vortex-public-subscription-url"]')?.content;
function subscriptionUrl(token){if(!subscriptionBaseUrl)throw new Error('Subscription URL is unavailable');return subscriptionBaseUrl+'/s/'+encodeURIComponent(token);}
function remoteProfileLink(url,name){return 'sing-box://import-remote-profile?url='+encodeURIComponent(url)+'#'+encodeURIComponent(name);}
async function subscriptionUrlFor(name){const response=await fetch('/devices/'+encodeURIComponent(name)+'/subscription-token',{credentials:'same-origin'});if(!response.ok)throw new Error('Unavailable');const payload=await response.json();return subscriptionUrl(payload.token);}
function buttonNotice(button,text){const original=button.textContent;button.textContent=text;setTimeout(()=>button.textContent=original,1500);}
async function copySubscriptionUrl(name,button){try{await navigator.clipboard.writeText(await subscriptionUrlFor(name));buttonNotice(button,'Copied');}catch{buttonNotice(button,'Unavailable');}}
async function addToSingBox(name,button){try{const url=await subscriptionUrlFor(name);window.location.href=remoteProfileLink(url,'VORTEX '+name);}catch{buttonNotice(button,'Unavailable');}}

function normalizeDeviceName(input){input.value=input.value.toUpperCase().replace(/\s+/g,'-');}