function toast(message,type='success'){const region=document.getElementById('toast-region');if(!region)return;const item=document.createElement('div');item.className='toast '+type;item.textContent=message;region.append(item);setTimeout(()=>item.remove(),3600)}
function setBusy(button,busy,label){if(!button)return;button.disabled=busy;if(busy){button.dataset.label=button.textContent;button.textContent=label||'Working…'}else button.textContent=button.dataset.label||button.textContent}
let blockingOverlayDepth=0,blockingOverlayTimer,blockingOverlayAnimation,blockingOverlayInert=[];
function blockingOverlay(){return document.getElementById('blocking-overlay')}
function setPageInert(active){const overlay=blockingOverlay();if(!overlay)return;if(active){blockingOverlayInert=[];[...document.body.children].filter(node=>node!==overlay).forEach(node=>{blockingOverlayInert.push([node,node.inert]);node.inert=true})}else{blockingOverlayInert.forEach(([node,wasInert])=>node.inert=wasInert);blockingOverlayInert=[]}}
function showBlockingOverlay(){const overlay=blockingOverlay();if(!overlay)return;clearTimeout(blockingOverlayTimer);if(blockingOverlayDepth++>0)return;setPageInert(true);document.body.classList.add('page-blocked');overlay.hidden=false;overlay.setAttribute('aria-hidden','false');requestAnimationFrame(()=>{overlay.classList.add('is-visible');overlay.focus({preventScroll:true})});blockingOverlayAnimation?.play()}
function hideBlockingOverlay(){const overlay=blockingOverlay();if(!overlay||blockingOverlayDepth===0)return;if(--blockingOverlayDepth>0)return;overlay.classList.remove('is-visible');overlay.setAttribute('aria-hidden','true');document.body.classList.remove('page-blocked');setPageInert(false);blockingOverlayTimer=setTimeout(()=>{if(!blockingOverlayDepth)overlay.hidden=true},240)}
window.withBlockingOverlay=async task=>{showBlockingOverlay();try{return await task()}finally{hideBlockingOverlay()}};
document.addEventListener('DOMContentLoaded',()=>{const menu=document.querySelector('[data-menu-toggle]');const close=()=>{document.body.classList.remove('nav-open');menu?.setAttribute('aria-expanded','false')};menu?.addEventListener('click',()=>{document.body.classList.toggle('nav-open');menu.setAttribute('aria-expanded',String(document.body.classList.contains('nav-open')))});document.querySelectorAll('[data-menu-close]').forEach(x=>x.addEventListener('click',close));document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>{const submit=form.querySelector('button[type="submit"],button:not([type])');if(submit&&!form.onsubmit)setBusy(submit,true,'Saving…');if(form.matches('[data-blocking-action]'))queueMicrotask(()=>{if(!event.defaultPrevented)showBlockingOverlay()})}));const animation=document.getElementById('blocking-overlay-animation');if(animation&&window.lottie)blockingOverlayAnimation=window.lottie.loadAnimation({container:animation,renderer:'svg',loop:true,autoplay:false,path:'/static/vendor/loading-spinner.json'});initEditor()});
async function copyConfig(name){try{const r=await fetch('/devices/'+encodeURIComponent(name)+'/config');if(!r.ok)throw Error();await navigator.clipboard.writeText(await r.text());toast('Client JSON copied to clipboard.')}catch{toast('Unable to copy client config.','error')}}
const subscriptionBaseUrl=document.querySelector('meta[name="vortex-public-subscription-url"]')?.content;function subscriptionUrl(token){if(!subscriptionBaseUrl)throw new Error('Subscription URL is unavailable');return subscriptionBaseUrl+'/s/'+encodeURIComponent(token)}function remoteProfileLink(url,name){return 'sing-box://import-remote-profile?url='+encodeURIComponent(url)+'#'+encodeURIComponent(name)}async function subscriptionUrlFor(name){const response=await fetch('/devices/'+encodeURIComponent(name)+'/subscription-token',{credentials:'same-origin'});if(!response.ok)throw new Error('Unavailable');return subscriptionUrl((await response.json()).token)}function buttonNotice(button,text){const original=button.textContent;button.textContent=text;setTimeout(()=>button.textContent=original,1500)}async function copySubscriptionUrl(name,button){try{await navigator.clipboard.writeText(await subscriptionUrlFor(name));buttonNotice(button,'Copied');toast('Subscription URL copied.')}catch{buttonNotice(button,'Unavailable');toast('Subscription URL is unavailable.','error')}}async function addToSingBox(name,button){try{window.location.href=remoteProfileLink(await subscriptionUrlFor(name),'VORTEX '+name)}catch{buttonNotice(button,'Unavailable');toast('Subscription URL is unavailable.','error')}}function normalizeDeviceName(input){input.value=input.value.toUpperCase().replace(/\s+/g,'-')}
function clientTemplateElements(){return {template:document.getElementById('client-template'),revision:document.getElementById('client-template-revision'),result:document.getElementById('client-template-result')}}async function clientTemplateRequest(url,body){const csrf=document.querySelector('meta[name="vortex-csrf"]')?.content;const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':csrf},body:new URLSearchParams(body)});let data={};try{data=await response.json()}catch{}if(!response.ok)throw new Error(data.detail||data.message||'Request failed');return data}function templateResult(data){const {result}=clientTemplateElements();result.textContent=data.message;result.className=data.valid?'notice':'error';toast(data.message,data.valid?'success':'error')}async function validateClientTemplate(){const {template}=clientTemplateElements();try{templateResult(await clientTemplateRequest('/settings/client-config/validate',{template:editorValue()}))}catch(error){templateResult({valid:false,message:error.message})}}async function saveClientTemplate(){const {template,revision}=clientTemplateElements();if(!confirm('Save this client base config? New subscription requests will use it immediately.'))return;try{const data=await clientTemplateRequest('/settings/client-config/save',{template:editorValue(),expected_revision:revision.value});templateResult(data);if(data.valid){revision.value=data.revision;setTimeout(()=>location.reload(),700)}}catch(error){templateResult({valid:false,message:error.message})}}async function restoreClientTemplate(versionId){const {revision}=clientTemplateElements();if(!confirm('Restore this version? The current template will be saved as a previous version first.'))return;try{const data=await clientTemplateRequest('/settings/client-config/restore/'+encodeURIComponent(versionId),{expected_revision:revision.value});templateResult(data);if(data.valid)setTimeout(()=>location.reload(),700)}catch(error){templateResult({valid:false,message:error.message})}}
let clientConfigEditor = null;
let editorFullscreen = false;
function editorValue() { return clientConfigEditor ? clientConfigEditor.getValue() : document.getElementById("client-template")?.value || ""; }
function initEditor() {
  const textarea = document.getElementById("client-template");
  if (!textarea || !window.VortexCodeMirror) return;
  clientConfigEditor = window.VortexCodeMirror.create(textarea);
  const syntaxFeedback = () => {
    const result = document.getElementById("client-template-result");
    try {
      JSON.parse(editorValue());
      if (result?.dataset.syntaxError) { result.textContent = ""; result.className = "muted"; delete result.dataset.syntaxError; }
    } catch (error) {
      if (result) { result.textContent = "JSON syntax error: " + error.message; result.className = "error"; result.dataset.syntaxError = "true"; }
    }
  };
  clientConfigEditor.dom.addEventListener("input", syntaxFeedback);
  const panel = document.querySelector("[data-editor-panel]");
  const fullscreenButton = document.getElementById("fullscreen-json");
  const setFullscreen = (active) => {
    editorFullscreen = active;
    panel?.classList.toggle("editor-fullscreen", active);
    document.body.classList.toggle("editor-fullscreen-active", active);
    fullscreenButton.textContent = active ? "Exit fullscreen" : "Fullscreen";
    fullscreenButton.setAttribute("aria-pressed", String(active));
    setTimeout(() => { clientConfigEditor.requestMeasure(); if (!active) clientConfigEditor.focus(); }, 0);
  };
  fullscreenButton?.addEventListener("click", () => setFullscreen(!editorFullscreen));
  document.addEventListener("keydown", (event) => {
    if (editorFullscreen && event.key === "Escape") {
      event.preventDefault(); event.stopPropagation(); setFullscreen(false);
    }
  }, true);
  document.getElementById("format-json")?.addEventListener("click", () => {
    try { clientConfigEditor.setValue(JSON.stringify(JSON.parse(editorValue()), null, 2) + "\n"); toast("JSON formatted."); }
    catch (error) { toast("Invalid JSON: " + error.message, "error"); }
  });
  document.getElementById("copy-json")?.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(editorValue()); toast("JSON copied to clipboard."); }
    catch { toast("Unable to copy JSON.", "error"); }
  });
}
