import contextlib
import io
import json
import sys
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime
from unittest import TestCase, mock
from scripts import pv, build

NOW=datetime(2026,10,14,4,0,tzinfo=pv.JST)

def snapshot():
    return dict(status='success',updated=NOW.isoformat(),timezone='Asia/Tokyo',
                period={'start':'2026-10-07','end':'2026-10-13'},total={'/article-a.html':0},week={'/article-a.html':3})

class PVReporting(TestCase):
    def test_completed_seven_days(self):
        with mock.patch.object(pv,'report',side_effect=[({'/a.html':20},'Asia/Tokyo'),({'/a.html':7},'Asia/Tokyo')]) as report:
            data=pv.collect(object(),'test',NOW)
        self.assertEqual(data['period'],{'start':'2026-10-07','end':'2026-10-13'})
        self.assertEqual(report.call_args.args[-2:],('2026-10-07','2026-10-13'))
        self.assertEqual(pv.report.__defaults__,('yesterday',))

    def test_property_timezone_is_used(self):
        with mock.patch.object(pv,'report',side_effect=[({},'America/Los_Angeles'),({},'America/Los_Angeles')]):
            data=pv.collect(object(),'test',NOW)
        self.assertEqual(data['period'],{'start':'2026-10-06','end':'2026-10-12'})

    def test_failure_preserves_previous_snapshot(self):
        with TemporaryDirectory() as tmp, mock.patch.object(pv,'OUT',str(Path(tmp)/'pv.json')):
            Path(pv.OUT).write_text('previous')
            with mock.patch.object(pv,'report',side_effect=[({},'Asia/Tokyo'),RuntimeError('unavailable')]):
                with self.assertRaises(RuntimeError):pv.save(object(),'test',NOW)
            self.assertEqual(Path(pv.OUT).read_text(),'previous')

    def test_success_replaces_only_complete_snapshot(self):
        with TemporaryDirectory() as tmp, mock.patch.object(pv,'OUT',str(Path(tmp)/'pv.json')):
            with mock.patch.object(pv,'report',side_effect=[({},'Asia/Tokyo'),({},'Asia/Tokyo')]):pv.save(object(),'test',NOW)
            self.assertEqual(json.loads(Path(pv.OUT).read_text())['status'],'success')
            self.assertFalse(Path(pv.OUT+'.tmp').exists())

    def test_unset_credentials_fail_without_network(self):
        with mock.patch.dict(pv.os.environ,{},clear=True),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pv.main(),1)

    def test_api_failure_nonzero_and_log_redacted(self):
        modules={'google.analytics.data_v1beta':SimpleNamespace(BetaAnalyticsDataClient=mock.Mock()),
                 'google.oauth2':SimpleNamespace(service_account=SimpleNamespace(Credentials=mock.Mock()))}
        output=io.StringIO()
        with mock.patch.dict(sys.modules,modules), mock.patch.dict(pv.os.environ,{'GA4_PROPERTY_ID':'fixture','GA4_SA_KEY':'{}'},clear=True), mock.patch.object(pv,'save',side_effect=RuntimeError('secret-fixture-marker')), contextlib.redirect_stdout(output):
            self.assertEqual(pv.main(),1)
        self.assertNotIn('secret-fixture-marker',output.getvalue())

    def test_missing_data_uses_unranked_recommendations(self):
        articles=[{'href':'article-a.html','title':'A'}]
        text=build.render_popular(articles,{},metadata={})
        self.assertIn('おすすめ記事',text)
        self.assertNotIn('ランキング',text)
        self.assertNotIn('class="n',text)

    def test_real_ranking_counts_ties_and_timestamp(self):
        articles=[{'href':f'article-{x}.html','title':x} for x in 'abc']
        data=snapshot();data['week']={'/article-a.html':3,'/article-b.html':3,'/article-c.html':2}
        text=build.render_popular(articles,data['week'],metadata=data)
        self.assertIn('2026-10-07〜2026-10-13',text)
        self.assertIn('3 PV',text)
        self.assertIn('取得 2026-10-14 04:00 JST',text)
        self.assertEqual(text.count('>1</span>'),2)
        self.assertIn('>3</span>',text)

    def test_zero_not_unknown(self):
        raw='<div class="pmeta">date</div>'
        self.assertIn('0 views',build.ensure_pv(raw,0,'取得日時'))
        self.assertNotIn('views',build.ensure_pv(raw,None))

    def test_stale_and_invalid_metadata(self):
        data=snapshot()
        self.assertIn('更新待ち',build.pv_note(data,NOW.replace(day=16)))
        data['period']['start']='2026-10-06'
        self.assertFalse(build.pv_valid(data))
        self.assertFalse(build.pv_valid({'total':{},'week':{}}))
