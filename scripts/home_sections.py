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

from . import browse_ui, day_articles, next_preview, official_data, preview_data

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


# ------------------------------------------------------------- まとめ

def home(root, articles, news, matome, x_list_url='', now=None):
    now = now or datetime.now(preview_data.JST)
    return (ranking(root, now)
            + own_articles(articles)
            + updates_feed(news, matome, x_list_url)
            + '<script src="next-preview.js" defer></script>'
            + browse_ui.home_games(root, now))
