"""自動生成サムネの取り込み・差し替え（MINI-8、10/25 本人「サムネの自動差し替えまで進めて」・未公開）。

受入条件の検証：継続受渡し（thumb-inbox ブランチ）、本文指紋と画像SHAの照合（古い版・生成途中の更新は拒否）、
eyecatch・og:image・Twitter・TOP/一覧カードへの反映と再生成後の保持、同じ版の再実行は変更なし・ループなし、
失敗時は既存画像を保持、無効設定では何もしない。
"""
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from PIL import Image

from scripts import refresh_listings, thumb_auto as ta, thumb_deliver

STYLE = 'ink-lime-portrait-v3'
QA = {k: True for k in ta.QA_KEYS}


def article(body='本文A', pv=None, eyecatch='thumb-daily-20261025.svg'):
    pvb = f'<!-- AUTO:PV:START --><span class="pv">{pv} views</span><!-- AUTO:PV:END -->' if pv is not None else ''
    img = f'<img class="eyecatch" src="{eyecatch}" alt="10/25 見出し">\n' if eyecatch else ''
    return ('<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><title>T</title>\n'
            '<meta property="og:type" content="article">\n</head><body><main><article class="article">'
            '<div class="breadcrumb">ホーム</div>\n<h1>10/25 見出し</h1><div class="pmeta"><span class="tag data">順位・日程</span>'
            f'<span>2026.10.25</span>{pvb}</div>\n{img}<p class="lead">{body}</p>'
            '<h2>関連記事</h2><p>関連</p></article></main></body></html>')


def png(color=(20, 200, 80), size=(1672, 941)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, 'PNG')
    return buf.getvalue()


def bundle(inbox, path, source_html, image=None, qa=QA, legacy=False, **override):
    raw = source_html.encode()
    image = image or png()
    fp = ta.editorial_fingerprint(raw)
    key = ta.request_id(path, ta.blob_sha(raw) if legacy else fp, STYLE)
    m = dict(id=key, article_path=path, editorial_fingerprint=fp, source_blob_sha=ta.blob_sha(raw), style=STYLE,
             status='ready_unpublished', image_sha256=hashlib.sha256(image).hexdigest(), width=1672, height=941,
             prepared_at='2026-10-25T10:12:43+00:00', publication_approved=False, brief={'qa': qa})
    m.update(override)
    folder = Path(inbox) / m['id']
    folder.mkdir(parents=True)
    (folder / 'manifest.json').write_text(json.dumps(m, ensure_ascii=False))
    (folder / 'thumbnail.png').write_bytes(image)
    (folder / 'source.html').write_bytes(raw)
    return m


class Base(unittest.TestCase):
    PATH = 'article-daily-20261025.html'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'site'
        self.inbox = Path(self.temp.name) / 'inbox'
        (self.root / 'data/thumbs').mkdir(parents=True)
        self.inbox.mkdir()
        self.enable(True)
        self.html = article()
        (self.root / self.PATH).write_text(self.html)

    def enable(self, on):
        (self.root / ta.CONFIG).write_text(json.dumps({'enabled': on}))

    def run_import(self):
        with redirect_stdout(io.StringIO()):
            return ta.import_inbox(self.root, self.inbox)

    def page(self):
        return (self.root / self.PATH).read_text()

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in sorted(self.root.rglob('*')) if p.is_file()}


class Import(Base):
    def test_matching_version_is_imported_and_derivatives_fit_without_crop(self):
        m = bundle(self.inbox, self.PATH, self.html)
        r = self.run_import()
        self.assertEqual(r['imported'], [{'id': m['id'], 'article': self.PATH}])
        entry = json.loads((self.root / ta.REGISTRY).read_text())['entries'][self.PATH]
        self.assertEqual(entry['image_sha256'], m['image_sha256'])
        eye, og = (Image.open(self.root / entry['files'][k]['path']) for k in ('eyecatch', 'og'))
        self.assertEqual(eye.size, (1280, 720))
        self.assertEqual(og.size, (1200, 630))
        self.assertLess(max(abs(a - b) for a, b in zip(og.getpixel((5, 315)), ta.OG_BG)), 4)   # 左右は余白（全体を収める＝注記を切らない）
        self.assertGreater(og.getpixel((600, 3))[1], 150)             # 上下は画像（緑）で埋まる

    def test_old_version_is_rejected(self):
        """古い本文向けの画像（その後に本文が更新された）は採用しない。"""
        bundle(self.inbox, self.PATH, article(body='12:00版の本文'))
        r = self.run_import()
        self.assertEqual([x['reason'] for x in r['rejected']], ['stale_source'])
        self.assertEqual(json.loads((self.root / ta.REGISTRY).read_text())['entries'], {})
        self.assertFalse((self.root / ta.OUT_DIR).exists())

    def test_legacy_id_is_accepted_but_only_if_current(self):
        bundle(self.inbox, self.PATH, article(body='旧'), legacy=True)
        self.assertEqual(self.run_import()['rejected'][0]['reason'], 'stale_source')

    def test_newest_matching_version_wins_and_stale_ones_are_ignored(self):
        bundle(self.inbox, self.PATH, article(body='旧'))
        new = bundle(self.inbox, self.PATH, self.html, image=png((200, 20, 20)), prepared_at='2026-10-25T11:00:00+00:00')
        self.run_import()
        self.assertEqual(json.loads((self.root / ta.REGISTRY).read_text())['entries'][self.PATH]['id'], new['id'])

    def test_view_count_change_does_not_make_it_stale(self):
        bundle(self.inbox, self.PATH, article(pv=2))
        (self.root / self.PATH).write_text(article(pv=57))           # 閲覧数だけ変わった現在の記事
        self.assertEqual(len(self.run_import()['imported']), 1)

    def test_tampered_or_unchecked_inputs_are_rejected(self):
        cases = {
            'image_hash_mismatch': dict(image_sha256='0' * 64),
            'qa_incomplete': dict(brief={'qa': dict(QA, ai_label=False)}),
            'manifest_invalid': dict(status='pending'),
        }
        for reason, override in cases.items():
            with self.subTest(reason):
                shutil.rmtree(self.inbox); self.inbox.mkdir()
                bundle(self.inbox, self.PATH, self.html, **override)
                self.assertEqual(self.run_import()['rejected'][0]['reason'], reason)
        shutil.rmtree(self.inbox); self.inbox.mkdir()
        m = bundle(self.inbox, self.PATH, self.html)
        (self.inbox / m['id'] / 'source.html').write_text(self.html + ' ')   # 固定原文の改ざん
        self.assertEqual(self.run_import()['rejected'][0]['reason'], 'source_mismatch')
        shutil.rmtree(self.inbox); self.inbox.mkdir()
        bundle(self.inbox, self.PATH, self.html, image=png(size=(800, 800)), width=800, height=800)
        self.assertEqual(self.run_import()['rejected'][0]['reason'], 'image_invalid')
        shutil.rmtree(self.inbox); self.inbox.mkdir()
        bundle(self.inbox, '../index.html', self.html)
        self.assertEqual(self.run_import()['rejected'][0]['reason'], 'article_invalid')

    def test_same_version_rerun_changes_nothing(self):
        bundle(self.inbox, self.PATH, self.html)
        bundle(self.inbox, self.PATH, article(body='旧'))
        self.run_import()
        before = self.snapshot()
        r = self.run_import()
        self.assertEqual((r['imported'], r['rejected']), ([], []))
        self.assertEqual(self.snapshot(), before)


class Apply(Base):
    def setUp(self):
        super().setUp()
        self.m = bundle(self.inbox, self.PATH, self.html)
        self.run_import()

    def test_eyecatch_og_and_twitter_are_set_and_text_is_unchanged(self):
        r = ta.apply_all(self.root)
        self.assertEqual(r['applied'], [self.PATH])
        page = self.page()
        self.assertIn(f'<img class="eyecatch" src="thumbs/auto/article-daily-20261025-{self.m["image_sha256"][:12]}.jpg"', page)
        self.assertIn('data-default-src="thumb-daily-20261025.svg"', page)
        for meta in ('property="og:image"', 'property="og:image:width" content="1200"', 'name="twitter:card" content="summary_large_image"',
                     'name="twitter:image"'):
            self.assertIn(meta, page)
        self.assertEqual(ta.editorial_fingerprint(page.encode()), self.m['editorial_fingerprint'])   # 差し替えで指紋は不変＝生成側で再生成ループにならない

    def test_apply_twice_is_a_no_op(self):
        ta.apply_all(self.root)
        before = self.snapshot()
        self.assertEqual(ta.apply_all(self.root)['applied'], [])
        self.assertEqual(self.snapshot(), before)

    def test_build_reordering_head_does_not_cause_churn(self):
        """build（page_assets）が head の並びを変えても、同じ内容なら apply は何も変えない（毎回の差分を出さない）。"""
        ta.apply_all(self.root)
        page = self.page()
        metas = ''.join(m.group(0) for m in ta.META_AUTO.finditer(page))
        moved = ta.META_AUTO.sub('', page).replace('</head>', '<link rel="stylesheet" href="x.css">\n' + metas + '</head>')
        (self.root / self.PATH).write_text(moved)
        self.assertEqual(ta.apply_all(self.root)['applied'], [])
        self.assertEqual(self.page(), moved)

    def test_article_regenerated_with_default_image_gets_it_back(self):
        ta.apply_all(self.root)
        applied = self.page()
        (self.root / self.PATH).write_text(self.html)                 # 記事の再生成（同じ本文・既定のSVG）
        ta.apply_all(self.root)
        self.assertEqual(self.page(), applied)

    def test_article_without_eyecatch_gets_one_after_pmeta(self):
        (self.root / self.PATH).write_text(article(eyecatch=None))   # 日付記事は生成時に eyecatch を外す
        ta.apply_all(self.root)
        page = self.page()
        self.assertRegex(page, r'</div>\n<img class="eyecatch" src="thumbs/auto/[^"]+" [^>]*data-default-src="">')
        (self.root / self.PATH).write_text(ta.restore_html(page))
        self.assertNotIn('eyecatch', self.page())

    def test_updated_article_keeps_its_own_image(self):
        """本文が更新された記事には古い版の画像を入れない（既定の画像のまま）。"""
        ta.apply_all(self.root)
        updated = ta.apply_html(article(body='19:10版の本文'), json.loads((self.root / ta.REGISTRY).read_text())['entries'][self.PATH])
        (self.root / self.PATH).write_text(updated)                   # 古い画像が残ったまま本文だけ変わった場合も
        r = ta.apply_all(self.root)
        self.assertEqual(r['stale'], [{'article': self.PATH, 'reason': 'stale_source'}])
        page = self.page()
        self.assertIn('<img class="eyecatch" src="thumb-daily-20261025.svg"', page)
        self.assertNotIn('data-auto-thumb', page)
        self.assertNotIn('og:image', page)

    def test_missing_derived_file_keeps_existing_display(self):
        entry = json.loads((self.root / ta.REGISTRY).read_text())['entries'][self.PATH]
        (self.root / entry['files']['og']['path']).unlink()
        r = ta.apply_all(self.root)
        self.assertEqual(r['stale'], [{'article': self.PATH, 'reason': 'missing_file'}])
        self.assertEqual(self.page(), self.html)

    def test_disabled_config_touches_nothing(self):
        self.enable(False)
        before = self.snapshot()
        self.assertEqual(ta.apply_all(self.root), {'applied': [], 'stale': [], 'unchanged': 0})
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(ta.main(['import', '--root', str(self.root), '--inbox', str(self.inbox)]), 0)
        self.assertIn('無効', out.getvalue())
        self.assertEqual(self.snapshot(), before)


class Listings(unittest.TestCase):
    def test_refresh_listings_still_finds_rows_with_thumbnails(self):
        rows = ('<a class="item compact-item has-thumb" href="a.html"><img class="item-thumb" src="thumbs/auto/x.jpg" alt=""><div class="c">'
                '<h3>A</h3></div></a>\n<a class="item compact-item" href="b.html"><div class="c"><h3>B</h3></div></a>\n')
        self.assertEqual(refresh_listings.ROWS.search(rows).group(0), rows)

    def test_build_cards_show_image_only_for_auto_thumbnails(self):
        from scripts import build, home_sections
        from datetime import datetime
        items = [dict(href='article-daily-20261025.html', title='T1', cat='data', label='順位・日程', date='2026.10.25', extra='',
                      thumb='thumbs/auto/article-daily-20261025-abc.jpg', alt='T1', desc=''),
                 dict(href='article-daily-20261024.html', title='T2', cat='data', label='順位・日程', date='2026.10.24', extra='',
                      thumb='thumb-daily-20261024.svg', alt='T2', desc='')]
        html = build.render_articles(items)
        self.assertEqual(html.count('class="item-thumb"'), 1)
        self.assertIn('compact-item has-thumb" href="article-daily-20261025.html"', html)
        lead = home_sections.lead_article(items, datetime(2026, 10, 25, 9, 0))
        self.assertIn('class="lead-article has-thumb"', lead)
        self.assertIn('src="thumbs/auto/article-daily-20261025-abc.jpg"', lead)
        self.assertNotIn('<img', home_sections.lead_article(items[1:], datetime(2026, 10, 25, 9, 0)))


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, text=True, capture_output=True).stdout


class Deliver(unittest.TestCase):
    """Mac mini → thumb-inbox ブランチ（main には書かない）。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.remote, self.repo, self.ready = base / 'remote.git', base / 'clone', base / 'ready'
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(self.remote)], check=True)
        subprocess.run(['git', 'clone', '-q', str(self.remote), str(self.repo)], check=True, capture_output=True)
        for k, v in (('user.name', 'mac'), ('user.email', 'mac@example.com')):
            git(self.repo, 'config', k, v)
        (self.repo / 'index.html').write_text('main')
        git(self.repo, 'add', '-A'); git(self.repo, 'commit', '-qm', 'base'); git(self.repo, 'push', '-q', 'origin', 'main')
        self.main_head = git(self.remote, 'rev-parse', 'main')
        self.state = base / 'state.json'
        self.items = {}
        for body in ('旧', '新'):
            folder = base / 'work' / body
            folder.mkdir(parents=True)
            src = folder / 'source.html'; src.write_text(article(body=body))
            m = bundle(self.ready, 'article-daily-20261025.html', article(body=body), image=png((len(body) * 50, 0, 0)))
            m['source_file'] = str(src)
            (self.ready / m['id'] / 'manifest.json').write_text(json.dumps(m))
            (self.ready / m['id'] / 'source.html').unlink()
            self.items[body] = m['id']
        self.state.write_text(json.dumps({'latest': {'article-daily-20261025.html': self.items['新']}}))

    def deliver(self):
        with redirect_stdout(io.StringIO()):
            return thumb_deliver.deliver(self.ready, self.repo, self.state)

    def test_only_latest_version_is_pushed_to_inbox_branch_and_rerun_is_a_no_op(self):
        self.assertEqual(self.deliver(), [self.items['新']])
        files = git(self.remote, 'ls-tree', '-r', '--name-only', 'thumb-inbox').split()
        self.assertEqual(sorted(files), sorted(f'inbox/{self.items["新"]}/{n}' for n in ('manifest.json', 'source.html', 'thumbnail.png')))
        self.assertEqual(git(self.remote, 'rev-parse', 'main'), self.main_head)        # main は不変
        head = git(self.remote, 'rev-parse', 'thumb-inbox')
        self.assertEqual(self.deliver(), [])
        self.assertEqual(git(self.remote, 'rev-parse', 'thumb-inbox'), head)

    def test_delivered_bundle_is_importable_by_site(self):
        self.deliver()
        out = Path(self.temp.name) / 'export'; out.mkdir()
        subprocess.run(f'git -C {self.remote} archive thumb-inbox inbox | tar -x -C {out}', shell=True, check=True)
        site = Path(self.temp.name) / 'site'; (site / 'data/thumbs').mkdir(parents=True)
        (site / 'article-daily-20261025.html').write_text(article(body='新'))
        r = ta.import_inbox(site, out / 'inbox')
        self.assertEqual([x['id'] for x in r['imported']], [self.items['新']])

    def test_different_image_under_same_id_is_not_overwritten(self):
        self.deliver()
        img = self.ready / self.items['新'] / 'thumbnail.png'
        m = json.loads((self.ready / self.items['新'] / 'manifest.json').read_text())
        data = png((1, 2, 3)); img.write_bytes(data)
        m['image_sha256'] = hashlib.sha256(data).hexdigest()
        (self.ready / self.items['新'] / 'manifest.json').write_text(json.dumps(m))
        head = git(self.remote, 'rev-parse', 'thumb-inbox')
        self.assertEqual(self.deliver(), [])
        self.assertEqual(git(self.remote, 'rev-parse', 'thumb-inbox'), head)


class Workflow(unittest.TestCase):
    def test_import_step_is_gated_and_reads_inbox_branch_only(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/update.yml').read_text()
        step = text[text.index('自動生成サムネを取り込み'):text.index('- name: HTMLを生成')]
        self.assertIn("get('enabled') is True", step)
        self.assertIn('git fetch --depth=1 origin thumb-inbox', step)
        self.assertNotIn('git push', step)
        self.assertLess(text.index('3リーグ日付記事を更新'), text.index('自動生成サムネを取り込み'))
        self.assertEqual(len(re.findall(r'- cron:', text)), 4)
        config = json.loads((Path(__file__).resolve().parents[1] / ta.CONFIG).read_text())
        self.assertIs(config['enabled'], False)                       # 本人確認までは無効


if __name__ == '__main__':
    unittest.main()
