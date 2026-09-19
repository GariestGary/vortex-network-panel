async function copyConfig(name){const r=await fetch('/devices/'+encodeURIComponent(name)+'/config');await navigator.clipboard.writeText(await r.text());alert('Client JSON copied to clipboard.');}

async function copySubscriptionToken(name,button){const original=button.textContent;try{const response=await fetch('/devices/'+encodeURIComponent(name)+'/subscription-token',{credentials:'same-origin'});if(!response.ok)throw new Error('Unavailable');const payload=await response.json();await navigator.clipboard.writeText(payload.token);button.textContent='Copied';setTimeout(()=>button.textContent=original,1500);}catch{button.textContent='Unavailable';setTimeout(()=>button.textContent=original,1500);}}

function normalizeDeviceName(input){input.value=input.value.toUpperCase().replace(/\s+/g,'-');}