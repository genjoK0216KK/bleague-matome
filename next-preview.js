/* A stopped scheduler must not leave a started or stale selection labelled pregame. */
(()=>{const check=()=>document.querySelectorAll('[data-preview-valid-until]').forEach(box=>{
 const deadline=Date.parse(box.dataset.previewValidUntil);
 if(!Number.isFinite(deadline)||Date.now()<deadline||box.dataset.previewExpired)return;
 box.dataset.previewExpired='true';
 box.querySelectorAll('.preview-selection,.fixture-date,.next-fixtures').forEach(e=>e.hidden=true);
 const phase=box.querySelector('.phase-label');if(phase)phase.textContent='次戦情報 ／ 再確認待ち';
 const note=document.createElement('p');note.className='schedule-warning';note.setAttribute('role','status');
 note.textContent='試合開始時刻または資料の有効期限を過ぎたため、選手表を非表示にしています。次の更新まで公式日程をご確認ください。';
 (box.querySelector('h1,h2')||box).insertAdjacentElement('afterend',note);
 const link=box.querySelector('.primary-action');if(link)link.textContent='日程と更新状況を見る →';
});check();setInterval(check,60000);})();
