"""トップページの本文（10/21 本人承認の並び）。

並び順：
  1. ランキング（既存データをそのまま表示。計算・定義は変えない）
  2. 当サイトの独自記事（分析・予測・解説。外部リンクは混ぜない）
  3. 公式・外部の更新（公式発信／外部メディア／他社まとめ を分けて表示）
  4. 試合の結果・予定（補助）

ランキングは次の優先で 1 つだけ出す（スマホで独自記事が遠くならないように）。
  - 次の開催日の「出場予定選手（登録選手）のベスト5・サブ5」（今季平均 EFF）が有効なら、それ
  - そうでなければ、当日の EFF・ポジション別 TOP3 が確定している直近の日
どちらも既存の生成データ（next-preview.json / article-games-*.json）を既存の描画関数で
表示するだけで、再集計や別取得はしない。
"""
from datetime import datetime
from html import escape
from pathlib import Path

from . import browse_ui, day_articles, next_preview, official_data, preview_data, result_status

OWN_LIMIT = 6        # 独自記事の件数
OFFICIAL_LIMIT = 5   # 公式発信の件数
MEDIA_LIMIT = 3      # 外部メディアの件数
MATOME_LIMIT = 3     # 他社まとめの件数
OFFICIAL_SOURCES = ("B.LEAGUE公式",)


# ---------------------------------------------------------------- 1. ランキング

def latest_game_day(root, now):
    """当日 EFF・ポジション別 TOP3 が 1 リーグでも確定している直近の日。"""
    for row in browse_ui.summaries(root, now):
        leagues = row.get('game_day_rankings', {}).get('leagues', {})
        if any(v.get('positions') for v in leagues.values()):
            return row
    return None


def game_day_leaders(row):
    """当日 EFF・ポジション別 TOP3（保存済み）のうち、各ポジションの 1 位だけを表示する。
    順位は保存データの rank をそのまま使い、同率 1 位は全員出す。再集計はしない。"""
    date = row['date']
    href = 'article-games-' + date.replace('-', '') + '.html#game-eff'
    body = ('<p class="phase-label result-label">ランキング ／ 試合結果・当日の EFF</p>'
            '<h2>当日のEFF・ポジション別1位 <small>対象日 ' + escape(date) + '</small></h2>'
            '<p class="note">実際に出場した選手の公式試合スタッツによる当日の EFF です。2位・3位は試合結果ページに載せています。</p>')
    for league, result in row.get('game_day_rankings', {}).get('leagues', {}).items():
        name = official_data.LEAGUES[league][3] if league in official_data.LEAGUES else league
        if result.get('error') or not result.get('positions'):
            body += '<h3>' + escape(name) + '</h3><p class="note">' + escape(result.get('error') or '確認中') + '</p>'
            continue
        body += ('<h3>' + escape(name) + '</h3><div class="tablewrap" tabindex="0" aria-label="' + escape(name)
                 + ' 当日EFF ポジション別1位"><table class="leaders"><thead><tr><th scope="col">位置</th>'
                 '<th scope="col">選手・所属</th><th scope="col">EFF</th></tr></thead><tbody>')
        for position, players in result['positions'].items():
            tops = [p for p in players if p.get('rank') == 1]
            if not tops:
                body += '<tr><td>' + escape(position) + '</td><td colspan="2">対象の出場選手なし</td></tr>'
                continue
            for p in tops:
                body += ('<tr><td>' + escape(position) + '</td><td><strong>' + escape(p['name']) + '</strong>'
                         '<small>' + escape(p['team']) + '</small></td><td>' + escape(str(p['eff'])) + '</td></tr>')
        body += '</tbody></table></div>'
    return body + ('<a class="day-detail" href="' + href + '">' + date[5:].replace('-', '/')
                   + ' の結果と当日EFF TOP3 →</a>')


def ranking(root, now=None):
    now = now or datetime.now(preview_data.JST)
    preview = next_preview.load(root, now)
    if preview and preview.get('lineups'):
        leagues = ' ／ '.join(official_data.LEAGUES[k][3] for k in official_data.LEAGUES
                             if any(g['competition'] == k for g in preview['games']))
        body = ('<section class="home-ranking preview-heading" id="ranking" data-preview-valid-until="'
                + next_preview.valid_until(preview).isoformat() + '">'
                '<p class="phase-label">ランキング ／ 試合前・今季平均 EFF</p>'
                '<h2>' + next_preview.TITLE + '</h2>'
                '<p class="fixture-date">' + ('確認できた次の開催日' if preview.get('errors') else '次の開催日')
                + ' <strong>' + escape(preview['date']) + '</strong>・' + escape(leagues) + '</p>'
                '<p class="note">登録選手から選出しています。試合当日の出場を確約するものではありません。</p>'
                + day_articles.lineup_html(preview, heading=False)
                + '<a class="primary-action" href="next-games.html">対象の試合と選出ルールを見る →</a>')
        recent = latest_game_day(root, now)
        if recent:
            body += ('<a class="day-detail" href="article-games-' + recent['date'].replace('-', '')
                     + '.html#game-eff">直近 ' + recent['date'][5:].replace('-', '/') + ' の当日EFF・TOP3 →</a>')
        return body + '</section>'

    recent = latest_game_day(root, now)
    if recent:
        return ('<section class="home-ranking" id="ranking">' + game_day_leaders(recent)
                + '<a class="day-detail" href="next-games.html">次の試合のベスト5・サブ5（更新待ちの場合あり） →</a>'
                + '</section>')

    return ('<section class="home-ranking" id="ranking"><p class="phase-label">ランキング</p>'
            '<h2>ランキングは確認中です</h2>'
            '<a class="day-detail" href="next-games.html">次の試合のベスト5・サブ5 →</a>'
            '<a class="day-detail" href="cat-data.html">順位・日程 →</a></section>')


# ------------------------------------------------------------ 2. 独自記事

def own_kind(article):
    """記事の種類（表示用ラベル）。記事ファイル自身の情報だけで決める。"""
    href, extra = article['href'], article.get('extra', '')
    if '予測' in extra or '予想' in extra or href.startswith(('article-forecast-', 'article-prediction-')):
        return '予測'
    if href.startswith('article-stats-') or 'ランキング' in extra or '比較' in extra:
        return '分析'
    return '解説・まとめ'


def is_own_article(article):
    """結果・予定の自動ページ（補助導線）を除いた、当サイト作成の記事。"""
    return not article['href'].startswith(('article-games-', 'article-results-', 'article-preview-'))


def own_articles(articles, limit=OWN_LIMIT):
    rows = [a for a in articles if is_own_article(a)][:limit]
    body = ('<section class="home-own" id="own-articles"><div class="sec-h"><h2>当サイトの独自記事</h2>'
            '<a class="more" href="articles.html">記事一覧 ›</a></div>'
            '<p class="section-note">当サイトが公式記録や報道を確認して作成した記事です。外部サイトの記事は含めません。</p>')
    if not rows:
        return body + '<p class="note">独自記事はまだありません。</p></section>'
    body += '<div class="own-grid">'
    for a in rows:
        desc = a.get('desc', '')
        if len(desc) > 70:
            desc = desc[:70].rstrip() + '…'
        body += ('<a class="own-card" href="' + escape(a['href']) + '">'
                 '<span class="own-kind">' + own_kind(a) + '</span>'
                 '<h3>' + escape(a['title']) + '</h3>'
                 + ('<p>' + escape(desc) + '</p>' if desc and desc != a['title'] else '')
                 + '<span class="own-date">' + escape(a['date']) + '</span></a>')
    return body + '</div></section>'


# --------------------------------------------------- 3. 公式・外部の更新

def _update_row(item, kind):
    meta = escape(item.get('date', '').replace('-', '.'))
    src = escape(item.get('source', ''))
    return ('<li><a href="' + escape(item['url']) + '" target="_blank" rel="noopener nofollow">'
            + escape(item.get('title', '')) + '</a>'
            '<span class="upd-meta">' + kind + '・' + src + '・' + meta + '</span></li>')


def updates_feed(news, matome, x_list_url=''):
    official = [n for n in news if n.get('source') in OFFICIAL_SOURCES][:OFFICIAL_LIMIT]
    media = [n for n in news if n.get('source') not in OFFICIAL_SOURCES][:MEDIA_LIMIT]
    others = list(matome)[:MATOME_LIMIT]
    body = ('<section class="home-updates" id="updates"><div class="sec-h"><h2>公式・外部の更新</h2></div>'
            '<p class="section-note">外部サイトへのリンクです。当サイトの記事ではありません。</p>')
    if x_list_url:
        body += ('<div class="upd-group"><h3>クラブ公式X</h3>'
                 '<a class="twitter-timeline" data-lang="ja" data-tweet-limit="5" data-chrome="noheader nofooter" '
                 'data-dnt="true" href="' + escape(x_list_url) + '">クラブ公式Xのポストを見る</a>'
                 '<script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>'
                 '<a class="day-detail" href="x.html">もっと見る ›</a></div>')
    groups = (
        ('公式発信', 'B.LEAGUE公式サイトのお知らせ', official, 'news.html'),
        ('外部メディア', 'バスケ専門メディアの新着', media, 'news.html'),
        ('他社まとめ', '他サイトのまとめ記事', others, 'matome.html'),
    )
    for kind, heading, rows, more in groups:
        if not rows:
            continue
        body += ('<div class="upd-group"><h3>' + heading + ' <small>' + kind + '</small></h3><ul class="upd-list">'
                 + ''.join(_update_row(r, kind) for r in rows) + '</ul>'
                 '<a class="day-detail" href="' + more + '">' + kind + 'をもっと見る ›</a></div>')
    return body + '</section>'


# ------------------------------------------------- 提案：今日のバスケまとめ（未承認）
# 10/22 本人フィードバック「自社記事という名前はダサい」「当日EFFポジションランキングは意味が
# わからない、今日の記事まとめの方が良い」への変更案。HOME_VARIANT で切り替える。
#   'current' : 公開中の並び（ランキング → 独自記事 → 公式更新 → 試合）
#   'A'       : 今日のバスケまとめ → バスケ深掘り（記事）→ 公式更新 → 実績EFFは折りたたみ
#   'B'       : 今日のバスケまとめ → 編集部の記事 → 実績EFFは1行リンク → 公式更新 → 試合
#   'C'       : 今日のバスケまとめ（最新記事の見出し・要点・読むリンク → 試合1行 → 取得失敗1行＋詳細展開）
#               → 最近の記事 → 前日以前の試合・実績EFF（折りたたみ）→ 公式更新
HOME_VARIANT = 'C'  # 10/22 04:10 本人承認「公開して」により案Cを公開（旧の並びは 'current' で再現可）
OWN_NAMES = {'A': 'バスケ深掘り', 'B': '編集部の記事'}
WEEKDAYS = '月火水木金土日'
TODAY_ARTICLES = 3


def _jp_date(day):
    return f'{day.month}月{day.day}日（{WEEKDAYS[day.weekday()]}）'


def today_block(root, now, rows):
    """今日の対象日・試合数・各試合の状態。保存済みの公式データだけを使い、注目度は推測しない。"""
    today = now.date().isoformat()
    row = next((r for r in rows if r['date'] == today), None)
    body = ('<section class="home-today" id="today"><p class="phase-label">今日のバスケまとめ</p>'
            '<h2>' + _jp_date(now.date()) + '</h2>')
    if row is None:
        body += '<p class="today-lead">今日の日程を確認中です。</p>'
    elif not row['games']:
        body += '<p class="today-lead">今日は B.LEAGUE の試合はありません。</p>'
    else:
        counts = '・'.join(official_data.LEAGUES[k][3] + ' ' + str(n) + '試合'
                           for k in official_data.LEAGUES
                           for n in [sum(g['competition'] == k for g in row['games'])] if n)
        body += '<p class="today-lead">' + escape(counts) + '</p>'
        body += browse_ui.fetch_note(row)
        failed = bool(row.get('fetch_status'))
        body += ''.join(browse_ui.match_row(g, today, now, failed) for g in row['games'][:4])
        more = len(row['games']) - 4
        body += ('<a class="day-detail" href="' + day_articles.filename(today) + '">'
                 + ('ほか ' + str(more) + ' 試合・' if more > 0 else '') + '今日の試合の詳細 ›</a>')
    body += past_pending(root, rows, now)
    recent = next((r for r in rows if r['date'] < today
                   and any(preview_data.is_verified_final(g) for g in r['games'])), None)
    if recent:
        body += ('<a class="day-detail" href="' + day_articles.filename(recent['date']) + '">直近の試合結果（'
                 + recent['date'][5:].replace('-', '/') + '）›</a>')
    return body + '</section>'


def past_pending(root, rows, now):
    """前日以前で未確定の試合がある日：対象日・状態・最終確認時刻・表示内容の取得時刻（不明なら不明）。
    過去の日付は「今日」と書かない。"""
    out = ''
    for row in rows:
        day = datetime.fromisoformat(row['date']).date()
        if not (0 < (now.date() - day).days <= browse_ui.PENDING_DAYS):
            continue
        waiting = [g for g in row['games'] if not preview_data.is_verified_final(g)
                   and g.get('status') not in ('cancelled', 'postponed')]
        if not waiting:
            continue
        entry = result_status.load(root).get(row['date'], {})
        failed = entry.get('state') == 'fetch_failed'
        label = ('前日 ' if (now.date() - day).days == 1 else '') + _jp_date(day)
        state = ('公式サイトから取得できていません（' + escape(entry.get('failing_since') or '時刻不明') + ' から）'
                 if failed else '公式記録の確定待ち')
        out += ('<div class="past-pending"><p><strong>' + label + 'の ' + str(len(waiting)) + ' 試合</strong>：'
                + state + '</p><dl class="past-times">'
                '<dt>最後に公式サイトを確認できた時刻</dt><dd>' + escape(entry.get('last_checked_at') or '不明') + '</dd>'
                '<dt>表示中の内容の取得時刻</dt><dd>' + escape(entry.get('content_as_of') or '不明') + '</dd></dl>'
                '<a class="day-detail" href="' + day_articles.filename(row['date']) + '">'
                + row['date'][5:].replace('-', '/') + ' の試合を見る ›</a></div>')
    return out


def articles_block(articles, now, name):
    """今日の記事と最近の記事を分ける。過去の記事を「今日」として見せない。"""
    today = now.strftime('%Y.%m.%d')
    own = [a for a in articles if is_own_article(a)]
    todays = [a for a in own if a['date'] == today][:TODAY_ARTICLES]
    recent = [a for a in own if a['date'] != today][:TODAY_ARTICLES]

    def card(a):
        return ('<a class="own-card own-card-short" href="' + escape(a['href']) + '">'
                '<span class="own-kind">' + own_kind(a) + '</span><h3>' + escape(a['title']) + '</h3>'
                '<span class="own-date">' + escape(a['date']) + '</span></a>')
    body = ('<section class="home-own" id="own-articles"><div class="sec-h"><h2>' + escape(name) + '</h2>'
            '<a class="more" href="articles.html">記事一覧 ›</a></div>')
    body += '<h3 class="own-sub">今日の記事</h3>'
    if todays:
        body += '<div class="own-grid">' + ''.join(card(a) for a in todays) + '</div>'
    else:
        body += '<p class="own-empty">今日の記事は準備中です（8時・12時・19時ごろ更新）。</p>'
    if recent:
        body += '<h3 class="own-sub">最近の記事</h3><div class="own-grid">' + ''.join(card(a) for a in recent) + '</div>'
    return body + '</section>'


def eff_folded(root, now):
    """実績EFF（対象日を明記）を折りたたみで下位に置く。中身は公開中と同じ表。"""
    row = latest_game_day(root, now)
    if not row:
        return ''
    label = row['date'][5:].replace('-', '/')
    return ('<details class="home-eff-fold home-ranking" id="ranking"><summary>' + label
            + ' の試合で活躍した選手（ポジション別・当日EFF 1位）</summary>'
            + game_day_leaders(row) + '</details>')


def eff_link(root, now):
    row = latest_game_day(root, now)
    if not row:
        return ''
    label = row['date'][5:].replace('-', '/')
    return ('<p class="home-eff-link" id="ranking"><a class="day-detail" href="' + day_articles.filename(row['date'])
            + '#game-eff">' + label + ' の試合で活躍した選手（当日EFF・ポジション別）›</a></p>')


# ---------------------------------------------------------------- 案C
LEAD_SUMMARY = 60   # 要点の最大文字数


def _article_day(article):
    return datetime.strptime(article['date'], '%Y.%m.%d').date()


def article_thumb(article):
    """トップに出す記事の画像 (src, 幅, 高さ)。本人 10/29「サムネがトップに載ってないとインパクトない」。
    自動生成サムネ（承認済みの絵柄・本文と同じ版）を優先し、無ければ記事のサムネ（thumbgen の SVG・480×300）。"""
    thumb = article.get('thumb') or ''
    if thumb.startswith('thumbs/auto/'):
        return thumb, 1280, 720
    if thumb.startswith('thumb-') and thumb.endswith('.svg') and '/' not in thumb:
        return thumb, 480, 300
    return None


def lead_article(articles, now):
    """先頭の記事。今日の記事が無ければ最新記事を実日付つきで出す（今日の記事とは書かない）。"""
    own = [a for a in articles if is_own_article(a)]
    if not own:
        return '<p class="lead-empty">記事はまだありません。</p>'
    a = own[0]
    day = _article_day(a)
    label = '今日の記事' if day == now.date() else '最新記事・' + _jp_date(day)
    desc = (a.get('desc') or '').strip()
    if len(desc) > LEAD_SUMMARY:
        desc = desc[:LEAD_SUMMARY].rstrip() + '…'
    thumb = article_thumb(a)
    image = ('<a class="lead-thumb" href="' + escape(a['href']) + '" tabindex="-1" aria-hidden="true">'
             '<img src="' + escape(thumb[0]) + '" alt="" width="' + str(thumb[1]) + '" height="' + str(thumb[2]) + '"></a>'
             if thumb else '')
    return ('<article class="lead-article' + (' has-thumb' if image else '') + '">' + image
            + '<p class="lead-label">' + label + '</p>'
            '<h3><a href="' + escape(a['href']) + '">' + escape(a['title']) + '</a></h3>'
            + ('<p class="lead-desc">' + escape(desc) + '</p>' if desc and desc != a['title'] else '')
            + '<a class="read-link" href="' + escape(a['href']) + '">記事を読む ›</a></article>')


def games_line(root, now, rows):
    """今日の試合を1行で。取得できていない日も推測せず、保存済みの予定だけを数える。"""
    today = now.date().isoformat()
    row = next((r for r in rows if r['date'] == today), None)
    if row is None:
        text = '今日の試合：日程を確認中'
    elif not row['games']:
        text = '今日の試合：なし'
    else:
        times = sorted({datetime.fromisoformat(g['starts_at']).astimezone(preview_data.JST).strftime('%H:%M')
                        for g in row['games'] if g.get('starts_at')})
        text = ('今日の試合：' + str(len(row['games'])) + '試合'
                + ('・' + '／'.join(times) + ' 開始' if times else ''))
    link = ('<a class="games-link" href="' + day_articles.filename(today) + '">試合の詳細 ›</a>'
            if row is not None else '')
    link += '<a class="games-link" href="next-games.html">今季平均EFFのベスト5・サブ5 ›</a>'
    return '<div class="games-line"><p>' + escape(text) + '</p>' + link + '</div>'


def fetch_alert(root, now, rows):
    """取得失敗は常に見える1行。対象日・最終確認・表示内容の取得時刻は展開で確認する。"""
    failed = [r for r in rows if r.get('fetch_status')
              and 0 <= (now.date() - datetime.fromisoformat(r['date']).date()).days <= browse_ui.PENDING_DAYS]
    if not failed:
        return ''
    items = ''
    for r in failed:
        f = r['fetch_status']
        items += ('<li><strong>' + _jp_date(datetime.fromisoformat(r['date']).date()) + '</strong>'
                  '<dl><dt>取得できていない</dt><dd>' + escape(f.get('failing_since') or '不明') + ' から</dd>'
                  '<dt>最後に公式サイトを確認できた時刻</dt><dd>' + escape(f.get('last_checked_at') or '不明') + '</dd>'
                  '<dt>表示中の内容の取得時刻</dt><dd>' + escape(f.get('content_as_of') or '不明') + '</dd></dl>'
                  '<a class="day-detail" href="' + day_articles.filename(r['date']) + '">この日の試合 ›</a></li>')
    return ('<details class="fetch-alert"><summary>公式サイトから試合情報を取得できていません'
            '<span class="fetch-alert-more">詳細</span></summary><ul>' + items + '</ul>'
            '<p>確定した結果は各試合の公式ページでご確認ください。</p></details>')


def today_block_c(root, articles, now, rows):
    return ('<section class="home-today home-today-c" id="today">'
            '<h2>今日のバスケまとめ<span class="today-date">' + _jp_date(now.date()) + '</span></h2>'
            + lead_article(articles, now) + games_line(root, now, rows) + fetch_alert(root, now, rows)
            + '</section>')


def recent_articles_c(articles, now, skip=1, limit=4):
    own = [a for a in articles if is_own_article(a)][skip:skip + limit]
    if not own:
        return ''
    body = ('<section class="home-own home-own-c" id="own-articles"><div class="sec-h"><h2>最近の記事</h2>'
            '<a class="more" href="articles.html">記事一覧 ›</a></div><ul class="recent-list">')
    for a in own:
        day = _article_day(a)
        thumb = article_thumb(a)
        image = ('<img class="recent-thumb" src="' + escape(thumb[0]) + '" alt="" width="' + str(thumb[1])
                 + '" height="' + str(thumb[2]) + '" loading="lazy">' if thumb else '')
        body += ('<li><a' + (' class="has-thumb"' if image else '') + ' href="' + escape(a['href']) + '">' + image
                 + '<span class="recent-text"><span class="recent-date">' + _jp_date(day)
                 + '</span>' + escape(a['title']) + '</span></a></li>')
    return body + '</ul></section>'


def past_and_eff_c(root, rows, now):
    """前日以前の試合と実績EFFは下位の折りたたみ。対象日を必ず書く。"""
    body = ''
    past = past_pending(root, rows, now)
    recent = next((r for r in rows if r['date'] < now.date().isoformat()
                   and any(preview_data.is_verified_final(g) for g in r['games'])), None)
    if past or recent:
        body += '<details class="home-fold" id="past-games"><summary>前日以前の試合</summary>' + past
        if recent:
            body += ('<a class="day-detail" href="' + day_articles.filename(recent['date']) + '">確定した直近の結果：'
                     + _jp_date(datetime.fromisoformat(recent['date']).date()) + ' ›</a>')
        body += '</details>'
    row = latest_game_day(root, now)
    if row:
        body += ('<details class="home-fold home-ranking" id="ranking"><summary>'
                 + _jp_date(datetime.fromisoformat(row['date']).date())
                 + 'の試合で活躍した選手（当日EFF）</summary>' + game_day_leaders(row) + '</details>')
    return body


# ------------------------------------------------------------- まとめ

def home(root, articles, news, matome, x_list_url='', now=None, variant=None):
    now = now or datetime.now(preview_data.JST)
    variant = variant or HOME_VARIANT
    if variant == 'C':
        rows = browse_ui.summaries(root, now)
        return (today_block_c(root, articles, now, rows) + recent_articles_c(articles, now)
                + past_and_eff_c(root, rows, now) + updates_feed(news, matome, x_list_url))
    if variant in OWN_NAMES:
        rows = browse_ui.summaries(root, now)
        body = today_block(root, now, rows) + articles_block(articles, now, OWN_NAMES[variant])
        if variant == 'A':
            return body + updates_feed(news, matome, x_list_url) + eff_folded(root, now)
        return (body + eff_link(root, now) + updates_feed(news, matome, x_list_url)
                + browse_ui.home_games(root, now, rows))
    return (ranking(root, now)
            + own_articles(articles)
            + updates_feed(news, matome, x_list_url)
            + '<script src="next-preview.js" defer></script>'
            + browse_ui.home_games(root, now))
