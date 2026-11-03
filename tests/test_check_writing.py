import unittest

from scripts import check_writing


def page(body):
    return f'<html><body><p>外の文、外の文、外の文。</p><article class="article"><h1>見出し、見出し、見出し</h1>{body}</article></body></html>'


class CheckWriting(unittest.TestCase):
    def test_readable_body_passes(self):
        body = ('<p class="lead">10/27は試合がありません。次の試合は10/29です。</p>'
                '<div class="note"><p style="margin:0"><strong>Q. 第2戦はいつですか？</strong><br>A. 10/29です。会場は同じです。</p></div>')
        self.assertEqual(check_writing.check(page(body)), [])

    def test_two_commas_in_one_sentence(self):
        found = check_writing.check(page('<p>東京Uは強く、静岡は粘り、試合は接戦でした。</p>'))
        self.assertEqual(len(found), 1)
        self.assertIn('読点が2つ', found[0])

    def test_long_paragraph_and_br_lines(self):
        three = '<p>一。二。三。</p>'
        self.assertIn('3文', check_writing.check(page(three))[0])
        self.assertEqual(check_writing.check(page('<p>一。二。<br>三。四。</p>')), [])

    def test_reminders_in_body_but_not_in_the_closing_disclaimer(self):
        found = check_writing.check(page('<p>順位は公式ページで確認しました。</p><p>今後変わる可能性があります。</p>'))
        self.assertEqual(sorted(f.split('「')[1].split('」')[0] for f in found), ['可能性があります', '確認しました'])
        disclaimer = '<div class="note">本記事は各公式発表・報道をもとに作成しました。最新情報は公式サイトでご確認ください。</div>'
        self.assertEqual(check_writing.check(page(disclaimer)), [])

    def test_only_one_update_note(self):
        notes = '<div class="note">8時台の更新：結果を追記しました。</div><div class="note">19時に更新：会場を追記しました。</div>'
        self.assertIn('更新の注記が2つ', check_writing.check(page(notes))[-1])

    def test_sources_use_short_labels(self):
        good = ('<details class="sources"><summary>出典（1件）</summary><ul>'
                '<li><a href="https://example.com/a">B.LEAGUE公式：第1戦の試合ページ（10/31）</a></li></ul></details>')
        self.assertEqual(check_writing.check(page(good)), [])
        bad = ('<p class="source">出典:<br><a href="https://example.com/a">https://example.com/a</a>'
               '(B.LEAGUE公式、取得2026-11-03 08:40 JST)<br>※ 検索結果の表示で確認しました。</p>')
        found = check_writing.check(page(bad))
        self.assertEqual(len([f for f in found if 'URLをそのまま' in f]), 1)
        self.assertEqual(len([f for f in found if 'リンクの外' in f]), 2)

    def test_process_words(self):
        found = check_writing.check(page('<p>Web検索のスニペットで確かめました。</p>'))
        self.assertEqual(sorted(f.split('「')[1].split('」')[0] for f in found), ['Web検索', 'スニペット'])

    def test_sources_tables_and_cards_are_not_counted(self):
        body = ('<details class="sources"><summary>出典（1件）</summary><ul><li><a href="https://example.com">A：試合ページ（10/31）</a></li></ul></details><div class="tablewrap"><table><tr><td>a、b、c</td></tr></table></div>'
                '<p class="table-note">EFF＝貢献度、REB＝リバウンド、AST＝アシスト。</p>'
                '<div class="card"><p>関連、関連、関連。</p></div><div class="breadcrumb">ホーム、一覧、記事</div>')
        self.assertEqual(check_writing.check(page(body)), [])


if __name__ == '__main__':
    unittest.main()
