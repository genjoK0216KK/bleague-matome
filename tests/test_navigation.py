import unittest
from bs4 import BeautifulSoup
from scripts import site_header, stats

class Navigation(unittest.TestCase):
    def test_primary_routes_and_mobile_control(self):
        soup=BeautifulSoup(site_header.render('injury.html'),'html.parser')
        self.assertEqual([a['href'] for a in soup.select('nav a')][:4], ['index.html','next-games.html','cat-kekka.html','injury.html'])
        button=soup.select_one('button');self.assertTrue(button.has_attr('hidden'))
        self.assertEqual(button['aria-expanded'],'false')
        self.assertEqual(button['aria-controls'],soup.nav['id'])
        self.assertEqual(soup.select_one('[aria-current]')['href'],'injury.html')

    def test_article_current_section(self):
        for fn,target in [('article-preview-507235.html','next-games.html'),('article-games-20261014.html','cat-kekka.html'),('cat-iseki-2.html','cat-iseki.html')]:
            soup=BeautifulSoup(site_header.render(fn),'html.parser')
            self.assertEqual(soup.select_one('[aria-current]')['href'],target)
            self.assertEqual(soup.select_one('[aria-current]')['aria-current'],'location')

    def test_idempotent_shared_assets(self):
        raw='<html><head><link href="style.css?v=4"></head><body>'+site_header.render()+'</body></html>'
        result=site_header.enhance(raw,'index.html')
        self.assertEqual(result,site_header.enhance(result,'index.html'))
        soup=BeautifulSoup(result,'html.parser')
        self.assertEqual(len(soup.select('script[src*="site-nav"]')),1)
        self.assertEqual(soup.select_one('link')['href'],'style.css?v=6')

    def test_standalone_generated_pages_have_navigation(self):
        soup=BeautifulSoup(stats.page('T','D','injury.html','BODY'),'html.parser')
        self.assertTrue(soup.select_one('button[aria-controls="site-navigation"]'))
        self.assertEqual(soup.select_one('[aria-current]')['href'],'injury.html')
        self.assertTrue(soup.select_one('script[src*="site-nav"]'))

if __name__=='__main__':unittest.main()
