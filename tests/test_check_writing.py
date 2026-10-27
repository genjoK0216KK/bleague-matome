import unittest

from scripts import check_writing


def page(body):
    return f'<html><body><p>外の文、外の文、外の文。</p><article class="article"><h1>見出し、見出し、見出し</h1>{body}</article></body></html>'


class CheckWriting(unittest.TestCase):
    def test_readable_body_passes(self):
        body = ('<p class="lead">10/27は試合がありません。次の試合は10/29です。</p>'
                '<div class="note"><p style="margin:0"><strong>Q. 予測ですか？</strong><br>A. いいえ、比較です。予測ではありません。</p></div>')
        self.assertEqual(check_writing.check(page(body)), [])

    def test_two_commas_in_one_sentence(self):
        found = check_writing.check(page('<p>東京Uは強く、静岡は粘り、試合は接戦でした。</p>'))
        self.assertEqual(len(found), 1)
        self.assertIn('読点が2つ', found[0])

    def test_long_paragraph_and_br_lines(self):
        four = '<p>一。二。三。四。</p>'
        self.assertIn('4文', check_writing.check(page(four))[0])
        self.assertEqual(check_writing.check(page('<p>一。二。<br>三。四。</p>')), [])

    def test_process_words(self):
        found = check_writing.check(page('<p>Web検索のスニペットで確かめました。</p>'))
        self.assertEqual(sorted(f.split('「')[1].split('」')[0] for f in found), ['Web検索', 'スニペット'])

    def test_sources_tables_and_cards_are_not_counted(self):
        body = ('<p class="source">出典：A、B、C、D</p><div class="tablewrap"><table><tr><td>a、b、c</td></tr></table></div>'
                '<p class="table-note">EFF＝貢献度、REB＝リバウンド、AST＝アシスト。</p>'
                '<div class="card"><p>関連、関連、関連。</p></div><div class="breadcrumb">ホーム、一覧、記事</div>')
        self.assertEqual(check_writing.check(page(body)), [])


if __name__ == '__main__':
    unittest.main()
