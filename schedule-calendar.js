(() => {
  'use strict';
  const root = document.querySelector('.schedule-calendar');
  if (!root) return;
  const data = JSON.parse(document.getElementById('calendar-data').textContent);
  const labels = {BP:'B.PREMIER',B1:'B.ONE',BN:'B.NEXT'};
  const today = new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  let monthIndex = Math.max(0,data.months.findIndex(m=>m.month===today.slice(0,7)));
  let selected = today;
  const el = (tag,text,cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const outdated = snap => snap.status !== 'complete' || Date.now()-Date.parse(snap.checked_at)>36*3600000;
  function detail() {
    const box=root.querySelector('.calendar-detail');box.replaceChildren(el('h3',selected.replaceAll('-','/')+' の試合'));
    for(const [league,label] of Object.entries(labels)) {
      const snap=data.months[monthIndex].leagues[league];
      const group=el('section',undefined,'calendar-league');group.append(el('h4',label));
      const games=snap.days[selected]||[];
      if(outdated(snap))group.append(el('p','日程を再確認中です。掲載分は前回取得時点の情報です。','calendar-warning'));
      if(!games.length)group.append(el('p',outdated(snap)?'最新の試合有無は公式日程でご確認ください。':'試合予定なし'));
      for(const game of games) {
        const row=el('div',undefined,'calendar-game');
        const status={cancelled:'中止',postponed:'延期'}[game.status];
        row.append(el('span',status || (game.time||'開始時刻未定'),'calendar-time'));
        const link=el('a',game.home+' vs '+game.away);link.href=game.source;row.append(link);group.append(row);
      }
      box.append(group);
    }
    root.querySelectorAll('[data-date]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.date===selected)));
  }
  function draw() {
    const month=data.months[monthIndex];
    root.querySelector('#calendar-month').textContent=month.month.replace('-','年')+'月';
    const grid=root.querySelector('.calendar-days');grid.replaceChildren();
    const [y,m]=month.month.split('-').map(Number);const count=new Date(Date.UTC(y,m,0)).getUTCDate();
    const offset=new Date(Date.UTC(y,m-1,1)).getUTCDay();
    for(let i=0;i<offset;i++)grid.append(el('span'));
    for(let d=1;d<=count;d++) {
      const date=month.month+'-'+String(d).padStart(2,'0');
      const games=Object.values(month.leagues).flatMap(s=>s.days[date]||[]);
      const unknown=Object.values(month.leagues).some(outdated);
      const b=el('button');b.type='button';b.dataset.date=date;
      b.append(el('span',String(d)),el('small',(games.length?'●':'')+(unknown?' ?':'')));
      b.setAttribute('aria-label',date+(games.length?' 掲載'+games.length+'試合':'')+(unknown?' 一部未確認':(!games.length?' 試合予定なし':'')));
      if(date===today)b.setAttribute('aria-current','date');
      b.addEventListener('click',()=>{selected=date;detail();});grid.append(b);
    }
    if(!selected.startsWith(month.month))selected=month.month+'-01';
    root.querySelectorAll('[data-month-step]').forEach(b=>{const next=monthIndex+Number(b.dataset.monthStep);b.disabled=next<0||next>=data.months.length;});
    const sources=root.querySelector('.calendar-sources');sources.replaceChildren();
    for(const [league,snap] of Object.entries(month.leagues)) {
      const p=el('p');const a=el('a',labels[league]+' 公式日程');a.href=snap.source;p.append(a,document.createTextNode(' ／ 取得 '+new Date(snap.checked_at).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo'})+' JST'));sources.append(p);
    }
    detail();
  }
  root.querySelectorAll('[data-month-step]').forEach(b=>b.addEventListener('click',()=>{monthIndex+=Number(b.dataset.monthStep);draw();}));
  draw();
})();
