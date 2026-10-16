import unittest
from pathlib import Path

class EditorialText(unittest.TestCase):
 def test_published_text_has_no_known_corruption(self):
  root=Path(__file__).resolve().parents[1]
  for path in list(root.glob('*.html'))+list(root.glob('*.svg')):
   text=path.read_bytes().decode('utf-8',errors='strict')
   for token in ('\ufffd','平圷','平圓','平垇','主劗','山ﾜ','全«試合»'):
    self.assertNotIn(token,text,str(path))
