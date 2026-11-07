"""クラブ公式サイトのお知らせ（scripts/fetch.py の CLUB_FEEDS）の試験。ネットには出ない。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
import fetch  # noqa: E402
from scripts import home_sections  # noqa: E402


def atom(*entries):
    body = ''.join(
        '<entry><id>{u}</id><title><![CDATA[{t}]]></title><updated>{d}T12:00:00+09:00</updated>'
        '<link rel="alternate" href="{u}"/><summary><![CDATA[本文は保存しない]]></summary></entry>'.format(t=t, d=d, u=u)
        for t, d, u in entries)
    return ('<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
            '<title>クラブ</title>' + body + '</feed>').encode('utf-8')


class Page:
    status_code = 200
    fetch_attempts = 1

    def __init__(self, content):
        self.content = content


class ClubRelevant(unittest.TestCase):
    # 2026-10-31〜11-07 の実際の見出しから
    KEEP = [
        'エルジー・ギル選手 契約満了のお知らせ',
        '#15 松脇圭志選手 負傷のご報告',
        '【アンジェロ・チョル選手】インジュアリーリスト抹消のお知らせ',
        '松山駿選手 B.LEAGUE  通算1,000アシスト達成のお知らせ',
        '【ご報告】2026-27 SEASON  横地 聖真 選手との選手契約(新規)の締結について',
        '山澤健人通訳兼サポートコーチ 契約締結のお知らせ',
        '【試合情報】12/30（水）アウェー富山戦 試合開始時間 変更のお知らせ',
        '2028-29シーズン B.PREMIERライセンス交付決定のお知らせ',
        '岡田大河選手 移籍先決定のお知らせ',
        '【記録達成】ライアン・クリーナー選手がBリーグ通算2000リバウンド達成',
        'Bリーグによる制裁決定のお知らせ',
    ]
    DROP = [
        '【グッズ情報】11/6(金)vs.A千葉,10(火)vs.大阪 発売グッズのご案内',
        '【チケット】2026-27シーズン 12月5日ｰ12月20日開催分の一次先行販売開始価格について',
        '株式会社シグマテクノロジー シルバースポンサー契約締結のお知らせ',
        '「2026ｰ27シーズン MONTHLY MVP presented by 茨城いすゞ自動車 」実施のお知らせ',
        '神戸ストークス 求人情報',
        '群馬クレインサンダーズU18 2027年度トライアウト実施のお知らせ',
        '【試合結果】滋賀レイクス 64-87 名古屋ダイヤモンドドルフィンズ（ 2026/11/1）',
        '11/6(金) 仙台89ERS戦 ゲームレポート',
        'オフィシャルパートナー',
        '20261106仙台',
        '天皇杯_270106 vs 未定',
        '天皇杯 2026-27_202701081700_未定',
        '第102回 天皇杯ファイナルラウンドの組み合わせ決定のお知らせ',
        'ミズノと「MIZUNO SLEEP」カテゴリーにおけるオフィシャルサプライヤー契約締結',
    ]

    def test_player_and_team_moves_are_kept(self):
        for title in self.KEEP:
            self.assertTrue(fetch.club_relevant(title), title)

    def test_tickets_goods_sponsors_and_game_reports_are_dropped(self):
        for title in self.DROP:
            self.assertFalse(fetch.club_relevant(title), title)


class FetchClubNews(unittest.TestCase):
    def run_feeds(self, feeds_content, today='2026-11-07'):
        feeds = [(club, f'https://example-{i}.jp/RSS.rdf') for i, club in enumerate(feeds_content)]
        pages = {url: Page(feeds_content[club]) for club, url in feeds}
        with mock.patch.object(fetch, 'robots_allows', return_value=True), \
                mock.patch.object(fetch, 'get', side_effect=lambda url, **kw: pages[url]), \
                mock.patch.object(fetch, 'REPORT', []):
            return fetch.fetch_club_news(today=today, feeds=feeds)

    def test_keeps_recent_moves_with_club_source(self):
        items = self.run_feeds({'千葉ジェッツ': atom(
            ('エルジー・ギル選手 契約満了のお知らせ', '2026-11-02', 'https://chibajets.jp/news/detail/id=1'),
            ('【グッズ情報】新商品のご案内', '2026-11-04', 'https://chibajets.jp/news/detail/id=2'),
        )})
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it['source'], '千葉ジェッツ公式')
        self.assertEqual(it['club'], '千葉ジェッツ')
        self.assertEqual(it['date'], '2026-11-02')
        self.assertEqual(it['url'], 'https://chibajets.jp/news/detail/id=1')
        self.assertNotIn('本文', str(it))

    def test_future_pinned_and_old_entries_are_skipped(self):
        items = self.run_feeds({'川崎ブレイブサンダース': atom(
            ('選手契約締結のお知らせ', '2050-05-20', 'https://k.example/1'),   # 固定表示のページ
            ('選手契約締結のお知らせ（古い）', '2026-10-01', 'https://k.example/2'),
            ('選手 負傷のお知らせ', '2026-11-07', 'https://k.example/3'),
        )})
        self.assertEqual([i['url'] for i in items], ['https://k.example/3'])

    def test_same_title_twice_in_one_club_is_listed_once(self):
        items = self.run_feeds({'広島ドラゴンフライズ': atom(
            ('#1 選手 復帰のお知らせ', '2026-11-06', 'https://h.example/1'),
            ('#1 選手 復帰のお知らせ', '2026-11-06', 'https://h.example/2'),
        )})
        self.assertEqual(len(items), 1)

    def test_escaped_markup_in_titles_is_cleaned(self):
        items = self.run_feeds({'茨城ロボッツ': atom(
            ('選手 契約締結&lt;br&gt; のお知らせ &amp; ご挨拶', '2026-11-05', 'https://i.example/1'),
        )})
        self.assertEqual(items[0]['title'], '選手 契約締結 のお知らせ & ご挨拶')

    def test_club_budget_is_separate_from_news_budget(self):
        # ニュース側の予算を使い切っていても、クラブ公式は別枠で取得する
        with mock.patch.object(fetch, '_run_left', return_value=0):
            items = self.run_feeds({'琉球ゴールデンキングス': atom(
                ('#15 選手 負傷のご報告', '2026-11-04', 'https://g.example/1'))})
        self.assertEqual(len(items), 1)

    def test_club_feeds_cover_all_26_clubs_in_team_colors(self):
        import json
        clubs = {c['name'] for c in json.loads((ROOT / 'scripts' / 'team_colors.json').read_text('utf-8'))['clubs']}
        self.assertEqual({c for c, _ in fetch.CLUB_FEEDS}, clubs)


class HomeUpdates(unittest.TestCase):
    def test_club_news_has_its_own_group_and_is_not_media(self):
        news = [
            {'title': 'リーグのお知らせ', 'url': 'https://www.bleague.jp/news/1', 'source': 'B.LEAGUE公式', 'date': '2026-11-06'},
            {'title': '選手 契約満了', 'url': 'https://chibajets.jp/news/detail/id=1', 'source': '千葉ジェッツ公式',
             'club': '千葉ジェッツ', 'date': '2026-11-06'},
            {'title': 'メディアの記事', 'url': 'https://basket-count.com/1', 'source': 'バスケット・カウント', 'date': '2026-11-06'},
        ]
        html = home_sections.updates_feed(news, [])
        self.assertIn('クラブ公式サイトのお知らせ', html)
        club_part = html.split('クラブ公式サイトのお知らせ')[1].split('</div>')[0]
        self.assertIn('選手 契約満了', club_part)
        self.assertIn('<span class="upd-meta">千葉ジェッツ公式・2026.11.06</span>', club_part)
        media_part = html.split('バスケ専門メディアの新着')[1].split('</div>')[0]
        self.assertNotIn('選手 契約満了', media_part)
        self.assertIn('メディアの記事', media_part)

    def test_no_club_group_when_there_is_no_club_news(self):
        html = home_sections.updates_feed([{'title': 'x', 'url': 'https://a', 'source': 'B.LEAGUE公式', 'date': '2026-11-06'}], [])
        self.assertNotIn('クラブ公式サイトのお知らせ', html)


if __name__ == '__main__':
    unittest.main()
