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


def render(state, now, *, failed=False, offline=False):
    records = state.get('records', [])
    active = [r for r in records if r['active']]
    removed = [r for r in records if not r['active']][:5]
    fetched = state.get('retrieved_at')
    age = (now - datetime.fromisoformat(fetched)).total_seconds() / 3600 if fetched else None
    fetched_label = datetime.fromisoformat(fetched).astimezone(data.JST).strftime('%Y-%m-%d %H:%M JST') if fetched else '未取得'
    notice = records[0]['notice_date'] if records else '未確認'
    body = '<div class="breadcrumb"><a href="index.html">ホーム</a> ／ IL・復帰情報</div><h1>インジュアリーリスト・復帰情報</h1>'
    body += '<p class="lead">公式ILの登録中の選手と、抹消の公示を分けて確認できます。</p>'
    body += '<div class="note"><strong>最終取得：' + esc(fetched_label) + '</strong><br>公式ページの公示日：' + esc(notice) + '<br>取得予定：毎日 07:00 / 12:00 / 21:00 / 23:00（日本時間）。実行・公開の遅延があります。瞬時更新ではありません。</div>'
    warning = '最新取得に失敗しました。前回取得の情報です。公式ページで現在の状況をご確認ください。' if failed else ''
    if age is None or age > STALE_HOURS:
        warning += ' 最終取得から12時間超、または取得時刻未確認です。古い情報の可能性があります。'
    if offline:
        warning += ' 保存した公式データによるローカル検証版です。'
    body += '<div class="note il-warning" id="il-freshness" data-retrieved="' + esc(fetched or '') + '"' + ('' if warning else ' hidden') + '>' + esc(warning) + '</div>'
    body += '<p>' + articles.link(URL, '最新の公式IL公示を開く') + '</p>'
    body += '<p>IL抹消は実戦復帰・次戦出場の確定ではありません。再登録不可期日を過ぎても、抹消公示がない選手は登録中です。傷病の詳細・診断の推定は掲載しません。</p>'
    body += '<h2>取得時点のIL登録中 <span class="il-count">' + str(len(active)) + '人</span></h2>'
    if not records:
        body += '<p>公式一覧を取得できていません。登録者がいないという意味ではありません。</p>'
    body += '<div class="il-grid">'
    for row in active:
        same = lambda r: r['team'] == row['team'] and r['name'] == row['name']
        history = any(same(r) and not r['active'] for r in records)
        badge = '現在IL登録中（抹消履歴あり）' if history else 'IL登録中'
        body += '<section class="il-card"><span class="il-badge">' + badge + '</span><h3>' + esc(row['name']) + '</h3><p>' + esc(row['team']) + ' ／ ' + esc(row['league']) + '</p>'
        body += '<dl><dt>リスト登録日</dt><dd>' + esc(row['registered_date']) + '</dd><dt>公示日</dt><dd>' + esc(row['announced_date']) + '</dd><dt>抹消日</dt><dd>公示なし</dd><dt>再登録不可期日</dt><dd>' + esc(row['unavailable_until']) + '</dd></dl></section>'
    body += '</div><h2>抹消・再登録の確認</h2><p>公式掲載順の抹消履歴から5件。日付に年の表記がないため、当年・今季の復帰とは断定しません。IL抹消後の選手登録日・実戦復帰はこの公示だけでは確認できません。</p><div class="il-grid">'
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


def generate(client, output, state_path, now=None):
    now = now or datetime.now(timezone.utc)
    output, state_path = Path(output), Path(state_path)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    error = None
    try:
        records = official.injury_records(client.get(URL))
        retrieved = next(s['retrieved_at'] for s in client.sources if s['url'] == URL)
        state = {'source': URL, 'retrieved_at': retrieved, 'records': records}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    except (ValueError, official.requests.RequestException) as exc:
        error = str(exc)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'injury.html').write_text(render(state, now, failed=bool(error), offline=client.offline), encoding='utf-8')
    return error
