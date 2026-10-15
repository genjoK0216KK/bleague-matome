import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import publish_update as subject


class PublishUpdate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / 'remote.git'
        subprocess.run(['git','init','--bare','--initial-branch=main',str(self.remote)],check=True,capture_output=True)
        self.local = self.root/'generated';self.editor = self.root/'editor'
        self.cmd(self.root,'clone',str(self.remote),str(self.local))
        self.identity(self.local)
        for path in ['news-6.html','news-7.html','data.json','source.py']:(self.local/path).write_text('base\n')
        self.commit(self.local,'base');self.cmd(self.local,'push','origin','main')
        self.cmd(self.root,'clone',str(self.remote),str(self.editor));self.identity(self.editor)
        old=os.getcwd();os.chdir(self.local);self.addCleanup(os.chdir,old)
    def cmd(self,cwd,*args):
        return subprocess.run(['git',*args],cwd=cwd,check=True,capture_output=True,text=True).stdout
    def identity(self,cwd):
        self.cmd(cwd,'config','user.name','Test');self.cmd(cwd,'config','user.email','test@example.com')
    def commit(self,cwd,message):
        self.cmd(cwd,'add','-A');self.cmd(cwd,'commit','-m',message)
    def overlap(self,paths):
        for path in paths:
            (self.local/path).write_text('generated\n');(self.editor/path).write_text('editorial\n')
        self.commit(self.local,'generated');self.commit(self.editor,'editorial');self.cmd(self.editor,'push','origin','main')
    def remote_text(self,path):return self.cmd(self.root,'--git-dir='+str(self.remote),'show','main:'+path)
    def test_news_conflict_preserves_published_edit_and_other_updates(self):
        (self.local/'data.json').write_text('new data\n');self.overlap(['news-6.html','news-7.html'])
        subject.publish()
        self.assertEqual(self.remote_text('news-6.html'),'editorial\n');self.assertEqual(self.remote_text('news-7.html'),'editorial\n')
        self.assertEqual(self.remote_text('data.json'),'new data\n');self.assertEqual(self.cmd(self.local,'status','--porcelain'),'')
    def test_news_only_conflict_skips_empty_commit(self):
        self.overlap(['news-6.html']);subject.publish();self.assertEqual(self.remote_text('news-6.html'),'editorial\n')
    def test_non_news_conflict_aborts_and_leaves_remote_unchanged(self):
        self.overlap(['source.py']);before=self.cmd(self.editor,'rev-parse','HEAD')
        with self.assertRaisesRegex(RuntimeError,'Non-news'):subject.publish()
        self.assertEqual(self.cmd(self.root,'--git-dir='+str(self.remote),'rev-parse','main'),before)
        self.assertFalse((self.local/'.git/rebase-merge').exists());self.assertEqual(self.cmd(self.local,'status','--porcelain'),'')
    def test_concurrent_deletion_is_preserved(self):
        (self.local/'news-6.html').write_text('generated\n');(self.local/'data.json').write_text('new\n');self.commit(self.local,'generated')
        (self.editor/'news-6.html').unlink();self.commit(self.editor,'delete');self.cmd(self.editor,'push','origin','main')
        subject.publish();self.assertNotIn('news-6.html',self.cmd(self.root,'--git-dir='+str(self.remote),'ls-tree','--name-only','main'))
        self.assertEqual(self.remote_text('data.json'),'new\n')
    def test_push_race_retries_against_new_upstream(self):
        (self.local/'data.json').write_text('new\n');self.commit(self.local,'generated');original=subject.git;race=[True]
        def git(*args,**kw):
            if args[0]=='push' and race[0]:
                race[0]=False;(self.editor/'news-6.html').write_text('later\n');self.commit(self.editor,'later');self.cmd(self.editor,'push','origin','main')
            return original(*args,**kw)
        with patch.object(subject,'git',side_effect=git):subject.publish()
        self.assertEqual(self.remote_text('news-6.html'),'later\n');self.assertEqual(self.remote_text('data.json'),'new\n')
