"""Official IL overview with explicit retrieval status and minimal public fields."""
import json
from datetime import datetime, timezone
from pathlib import Path
try:
    from . import official_data as official, preview_data as data, match_articles as articles, stats
except ImportError:
    import official_data as official
    import preview_data as data
    import match_articles as articles
    import stats

URL = official.BASE + '/news/injury.html'
STALE_HOURS = 12
esc = stats.esc


def _jst(value):
    return datetime.fromisoformat(value).astimezone(data.JST).strftime('%Y-%m-%d %H:%M JST') if value else None


def status_html(state, failed):
    """取得状態・最終成功・最新の確認・原典・対象を分けて表示する。不明は不明と書く。"""
    last_ok = _jst(state.get('last_success_at') or state.get('retrieved_at'))
    attempt = _jst(state.get('last_attempt_at'))
    if failed and last_ok:
        status = '最新の取得に失敗（前回取得の一覧を表示中・現在の状況は未確認）'
    elif failed:
        status = '取得できていません（一覧は未取得）'
    else:
        status = '取得できた一覧を表示中'
    scope = state.get('scope') or {}
    leagues = '・'.join(scope.get('leagues') or []) or '不明'
    rows = (('取得状態', status), ('最終成功（表示中の一覧の取得日時）', last_ok or '未取得'),
            ('最新の確認（取得を試みた日時）', attempt or '未確認'),
            ('原典', None), ('対象リーグ（一覧の記載）', leagues), ('シーズン', scope.get('season') or '不明（原典に記載なし）'))
    body = '<dl class="il-status" id="il-status">'
    for label, value in rows:
        body += '<dt>' + esc(label) + '</dt><dd>' + (articles.link(URL, 'B.LEAGUE公式インジュアリーリスト') if value is None else esc(value)) + '</dd>'
    return body + '</dl>'


def render(state, now, *, failed=False, offline=False):
    records = state.get('records', [])
    active = [r for r in records if r['active']]
    removed = [r for r in records if not r['active']][:5]
    fetched = state.get('last_success_at') or state.get('retrieved_at')
    age = (now - datetime.fromisoformat(fetched)).total_seconds() / 3600 if fetched else None
    fetched_label = _jst(fetched) or '未取得'
    notice = records[0]['notice_date'] if records else '未確認'
    body = '<div class="breadcrumb"><a href="index.html">ホーム</a> ／ IL・復帰情報</div><h1>インジュアリーリスト・復帰情報</h1>'
    body += '<p class="source">最終取得：' + esc(fetched_label) + ' ／ <a href="' + URL + '">公式IL</a></p>'
    body += status_html(state, failed)
    warning = '最新取得に失敗しました。前回取得の情報です。公式ページで現在の状況をご確認ください。' if failed else ''
    if age is None or age > STALE_HOURS:
        warning += ' 最終取得から12時間超、または取得時刻未確認です。古い情報の可能性があります。'
    if offline:
        warning += ' 保存した公式データによるローカル検証版です。'
    body += '<div class="note il-warning" id="il-freshness" data-retrieved="' + esc(fetched or '') + '"' + ('' if warning else ' hidden') + '>' + esc(warning) + '</div>'
    body += '<h2>取得時点のIL登録中 <span class="il-count">' + str(len(active)) + '人</span></h2>'
    if not records:
        body += '<p>公式一覧を取得できていません。登録者がいないという意味ではありません。</p>'
    body += '<div class="il-grid">'
    for row in active:
        same = lambda r: r['team'] == row['team'] and r['name'] == row['name']
        history = any(same(r) and not r['active'] for r in records)
        badge = 'IL登録中（取得時点・抹消履歴あり）' if history else 'IL登録中（取得時点）'
        body += '<section class="il-card"><span class="il-badge">' + badge + '</span><h3>' + esc(row['name']) + '</h3><p>' + esc(row['team']) + ' ／ ' + esc(row['league']) + '</p>'
        body += '<dl><dt>リスト登録日</dt><dd>' + esc(row['registered_date']) + '</dd><dt>公示日</dt><dd>' + esc(row['announced_date']) + '</dd><dt>抹消日</dt><dd>公示なし</dd><dt>再登録不可期日</dt><dd>' + esc(row['unavailable_until']) + '</dd></dl></section>'
    body += '</div><details><summary>IL・抹消情報の見方</summary><p>IL登録は当日の欠場発表とは別の公示です。IL抹消は実戦復帰・次戦出場の確定ではありません。再登録不可期日を過ぎても、抹消公示がない選手は登録中です。傷病の詳細・診断の推定は掲載しません。</p></details><h2>抹消・再登録の確認</h2><p>公式掲載順の抹消履歴から5件。日付に年の表記がないため、当年・今季の復帰とは断定しません。IL抹消後の選手登録日・実戦復帰はこの公示だけでは確認できません。</p><div class="il-grid">'
    for row in removed:
        registered_again = any(r['active'] and r['name'] == row['name'] and r['team'] == row['team'] for r in records)
        status = '抹消履歴あり／現在は再びIL登録中' if registered_again else 'IL抹消／選手再登録・出場は未確認'
        body += '<section class="il-card"><span class="il-badge il-return">' + status + '</span><h3>' + esc(row['name']) + '</h3><p>' + esc(row['team']) + '</p><dl><dt>IL抹消日</dt><dd>' + esc(row['removed_date']) + '</dd><dt>元のリスト登録日</dt><dd>' + esc(row['registered_date']) + '</dd></dl></section>'
    if not removed:
        body += '<p>表示できる抹消履歴はありません。復帰者なしとは断定しません。</p>'
    body += '</div><p class="source">出典：' + articles.link(URL, 'B.LEAGUE公式インジュアリーリスト') + '。クラブ・リーグ・月日は公示時点の原表記です。</p>'
    body += '''<script>(function(){var el=document.getElementById('il-freshness');function check(){var t=Date.parse(el.dataset.retrieved);if(!Number.isFinite(t)||Date.now()-t>12*3600000){el.hidden=false;if(!el.textContent.includes('12時間'))el.textContent+=' 最終取得から12時間超、または取得時刻未確認です。公式ページをご確認ください。';}}check();setInterval(check,60000);})();</script>'''
    html = stats.page('インジュアリーリスト・復帰情報', '公式IL登録・抹消の公示と取得時刻を確認。', 'injury.html', body)
    if offline:
        html = html.replace('</head>', '<meta name="robots" content="noindex,nofollow"></head>')
    return html.replace('<article class="article">', '<article class="article match-article">')


def generate(client, output, state_path, now=None, capture=None):
    """公式ILを取得して injury.json と injury.html を作る。失敗しても前回の一覧は消さず、
    状態（失敗・最新の確認日時・エラーの種類）を記録する。capture を渡すと、成功時だけ
    取得した原文を一時ファイルに保存する（同じ回の後続工程が同じ一覧を使い、再取得しないため）。"""
    now = now or datetime.now(timezone.utc)
    output, state_path = Path(output), Path(state_path)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get('retrieved_at') and not state.get('last_success_at'):
        state['last_success_at'] = state['retrieved_at']        # 旧形式の保存データ
    state['last_attempt_at'] = now.astimezone(timezone.utc).isoformat()
    error = None
    seen = len(getattr(client, 'failures', []))
    try:
        body = client.get(URL)
        records = official.injury_records(body)
        retrieved = next(s['retrieved_at'] for s in client.sources if s['url'] == URL)
        state.update(source=URL, retrieved_at=retrieved, last_success_at=retrieved, records=records,
                     status='ok', last_error=None,
                     scope={'leagues': sorted({r['league'] for r in records if r.get('league')}), 'season': None})
        if capture:
            Path(capture).write_text(json.dumps({'url': URL, 'retrieved_at': retrieved, 'body': body},
                                                ensure_ascii=False), encoding='utf-8')
    except (ValueError, official.requests.RequestException) as exc:
        error = str(exc)
        fetches = list(getattr(client, 'failures', [])[seen:])
        detail = fetches[-1] if fetches else {}
        state.update(source=URL, status='failed', records=state.get('records', []),
                     last_error={'type': detail.get('type') or type(exc).__name__,
                                 'http_status': detail.get('http_status'), 'url': URL,
                                 'category': detail.get('category') or 'parse'})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'injury.html').write_text(render(state, now, failed=bool(error), offline=client.offline), encoding='utf-8')
    return error
