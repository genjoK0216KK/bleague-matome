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
        text=build.render_popular(self.articles,{'/article-a.html':2,'/article-b.html':9})
        self.assertIn('人気記事ランキング（週間）',text)
        self.assertLess(text.index('article-b.html'),text.index('article-a.html'))
