async function copyConfig(name){const r=await fetch('/devices/'+encodeURIComponent(name)+'/config');await navigator.clipboard.writeText(await r.text());alert('Client JSON copied to clipboard.');}

function normalizeDeviceName(input){input.value=input.value.toUpperCase().replace(/\s+/g,'-');}
