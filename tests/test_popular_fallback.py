import unittest
from scripts import build

class PopularFallback(unittest.TestCase):
    def setUp(self):
        self.articles=[{'href':'article-a.html','title':'A'},{'href':'article-b.html','title':'B'}]

    def test_missing_or_zero_views_are_unranked_recommendations(self):
        for values in ({},{'/article-a.html':0}):
            text=build.render_popular(self.articles,values)
            self.assertIn('おすすめ記事',text)
            self.assertNotIn('ランキング',text)
            self.assertNotIn('class="n',text)
            self.assertIn('article-a.html',text)

    def test_available_measurements_switch_to_popular_order(self):
        values={'/article-a.html':2,'/article-b.html':9}
        metadata=dict(status='success',updated='2026-10-14T04:00:00+09:00',timezone='Asia/Tokyo',period={'start':'2026-10-07','end':'2026-10-13'},total=values,week=values)
        text=build.render_popular(self.articles,values,metadata=metadata)
        self.assertIn('人気記事ランキング（週間）',text)
        self.assertLess(text.index('article-b.html'),text.index('article-a.html'))
