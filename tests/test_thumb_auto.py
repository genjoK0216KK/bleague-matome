"""自動生成サムネの取り込み・差し替え（MINI-8、10/25 本人「サムネの自動差し替えまで進めて」・未公開）。

受入条件の検証：継続受渡し（thumb-inbox ブランチ）、本文指紋と画像SHAの照合（10/30 本人「C」から、古い版の画像も
新しい画像が届くまで出し続ける）、
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

    def test_old_version_is_still_imported(self):
        """10/30 本人「C」：古い本文向けの画像（その後に本文が更新された）も採用する（空白にしない）。"""
        m = bundle(self.inbox, self.PATH, article(body='12:00版の本文'))
        r = self.run_import()
        self.assertEqual((r['imported'], r['rejected']), ([{'id': m['id'], 'article': self.PATH}], []))

    def test_legacy_id_is_accepted_even_if_outdated(self):
        m = bundle(self.inbox, self.PATH, article(body='旧'), legacy=True)
        self.assertEqual([x['id'] for x in self.run_import()['imported']], [m['id']])

    def test_missing_article_is_rejected(self):
        bundle(self.inbox, 'article-daily-20261031.html', article())
        self.assertEqual(self.run_import()['rejected'][0]['reason'], 'article_missing')

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

    def test_updated_article_keeps_previous_image_until_a_new_one(self):
        """10/30 本人「C」：本文が更新されても、新しい画像が届くまで前の画像を出す（再生成で既定に戻っても入れ直す）。"""
        ta.apply_all(self.root)
        (self.root / self.PATH).write_text(article(body='19:10版の本文'))   # 再生成されて既定の画像に戻った
        r = ta.apply_all(self.root)
        self.assertEqual((r['applied'], r['outdated'], r['stale']), ([self.PATH], [self.PATH], []))
        page = self.page()
        self.assertIn('data-auto-thumb', page)
        self.assertIn('og:image', page)
        self.assertIn('19:10版の本文', page)

    def test_changed_headline_removes_image_of_other_subject(self):
        """試合前の「ベスト5」が試合後に「試合結果」になった等。違う主題の画像は出さない。"""
        ta.apply_all(self.root)
        self.assertIn('data-auto-thumb', self.page())
        (self.root / self.PATH).write_text(self.page().replace('<h1>10/25 見出し</h1>', '<h1>10/25 試合結果</h1>'))
        r = ta.apply_all(self.root)
        self.assertEqual(r['stale'], [{'article': self.PATH, 'reason': 'title_changed'}])
        self.assertNotIn('data-auto-thumb', self.page())
        self.assertIn('<img class="eyecatch" src="thumb-daily-20261025.svg"', self.page())

    def test_missing_derived_file_keeps_existing_display(self):
        entry = json.loads((self.root / ta.REGISTRY).read_text())['entries'][self.PATH]
        (self.root / entry['files']['og']['path']).unlink()
        r = ta.apply_all(self.root)
        self.assertEqual(r['stale'], [{'article': self.PATH, 'reason': 'missing_file'}])
        self.assertEqual(self.page(), self.html)

    def test_disabled_config_touches_nothing(self):
        self.enable(False)
        before = self.snapshot()
        self.assertEqual(ta.apply_all(self.root), {'applied': [], 'stale': [], 'outdated': [], 'unchanged': 0})
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
        # 自動生成サムネが無い記事は、記事のサムネ（SVG）をトップに出す（本人 10/29）
        svg_lead = home_sections.lead_article(items[1:], datetime(2026, 10, 25, 9, 0))
        self.assertIn('src="thumb-daily-20261024.svg" alt="" width="480" height="300"', svg_lead)
        recent = home_sections.recent_articles_c(items, datetime(2026, 10, 25, 9, 0), skip=0)
        self.assertEqual(recent.count('class="recent-thumb"'), 2)
        self.assertIn('src="thumbs/auto/article-daily-20261025-abc.jpg"', recent)
        self.assertIsNone(home_sections.article_thumb(dict(thumb='')))
        self.assertIsNone(home_sections.article_thumb(dict(thumb='https://example.com/x.svg')))


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
            m['prepared_at'] = {'旧': '2026-10-25T10:00:00+00:00', '新': '2026-10-25T11:00:00+00:00'}[body]
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
        self.assertIsInstance(config['enabled'], bool)                # 10/29 本人OKで有効化（止める時は false）



class ReviewFixes(Base):
    """ChatGPT 独立QA（10/25 21:26）の4点。"""

    def producer_bundle(self, source_html, fingerprint):
        raw = source_html.encode()
        image = png()
        key = ta.request_id(self.PATH, fingerprint, STYLE)
        m = dict(id=key, article_path=self.PATH, editorial_fingerprint=fingerprint, source_blob_sha=ta.blob_sha(raw),
                 style=STYLE, status='ready_unpublished', image_sha256=hashlib.sha256(image).hexdigest(),
                 width=1672, height=941, prepared_at='2026-10-26T06:00:00+00:00', brief={'qa': QA})
        folder = self.inbox / key
        folder.mkdir(parents=True)
        (folder / 'manifest.json').write_text(json.dumps(m))
        (folder / 'thumbnail.png').write_bytes(image)
        (folder / 'source.html').write_bytes(raw)
        return m

    # P1-1：生成側の正規化版の指紋（PV除外）を受け取り側が受け付ける。旧版の指紋も受け付け続ける
    def test_producer_normalized_fingerprint_is_accepted(self):
        src = article(pv=4)
        (self.root / self.PATH).write_text(article(pv=9))           # 閲覧数だけ増えた現本文
        m = self.producer_bundle(src, ta.stable_fingerprint(src.encode()))
        self.assertEqual([x['id'] for x in self.run_import()['imported']], [m['id']])

    def test_legacy_raw_fingerprint_is_still_accepted(self):
        src = article(pv=4)
        (self.root / self.PATH).write_text(article(pv=9))
        m = self.producer_bundle(src, ta.editorial_fingerprint(src.encode()))
        self.assertEqual([x['id'] for x in self.run_import()['imported']], [m['id']])

    def test_fingerprint_that_matches_neither_is_rejected(self):
        m = self.producer_bundle(article(), hashlib.sha256(b'other').hexdigest())
        r = self.run_import()
        self.assertEqual(r['imported'], [])
        self.assertEqual(r['rejected'][0]['reason'], 'source_mismatch')

    def test_unchanged_producer_bundle_survives_view_count_changes(self):
        """生成側は旧指紋のまま。閲覧数が何度変わっても同じ画像を使い続ける。本文が変わっても外さない（10/30「C」）。"""
        src = article(body='本文A', pv=4)
        self.producer_bundle(src, ta.editorial_fingerprint(src.encode()))
        for pv in (5, 40, 400):
            (self.root / self.PATH).write_text(article(body='本文A', pv=pv))
            self.run_import(); ta.apply_all(self.root)
            self.assertIn('data-auto-thumb', self.page(), pv)
        (self.root / self.PATH).write_text(article(body='本文B', pv=400))
        self.assertEqual(ta.apply_all(self.root)['outdated'], [self.PATH])
        self.assertIn('data-auto-thumb', self.page())

    def test_view_count_only_change_keeps_producer_fingerprint(self):
        a, b = article(pv=4).encode(), article(pv=40).encode()
        self.assertEqual(ta.stable_fingerprint(a), ta.stable_fingerprint(b))   # 受け取り側の版照合は閲覧数に左右されない
        self.assertNotEqual(ta.editorial_fingerprint(a), ta.editorial_fingerprint(b))

    # P2-4：除外は許可リストの自動枠だけ。本文の自動枠（得点など）の変化は検知する
    def test_body_auto_block_change_is_detected(self):
        before = b'<article><h1>Result</h1><!-- AUTO:BODY:START --><p>95-90</p><!-- AUTO:BODY:END --></article>'
        self.assertNotEqual(ta.stable_fingerprint(before), ta.stable_fingerprint(before.replace(b'95-90', b'101-90')))

    def test_only_listed_non_editorial_blocks_are_ignored(self):
        self.assertEqual(ta.NON_EDITORIAL_AUTO, ('PV', 'AFFILIATE', 'GA'))
        base = '<article><h1>T</h1><p>本文</p>{}</article>'
        for name in ta.NON_EDITORIAL_AUTO:
            noisy = base.format(f'<!-- AUTO:{name}:START --><p>x{name}</p><!-- AUTO:{name}:END -->')
            self.assertEqual(ta.stable_fingerprint(noisy), ta.stable_fingerprint(base.format('')), name)
        other = base.format('<!-- AUTO:STANDINGS:START --><p>1位</p><!-- AUTO:STANDINGS:END -->')
        self.assertNotEqual(ta.stable_fingerprint(other), ta.stable_fingerprint(base.format('')))

    def test_body_score_change_is_reported_but_image_stays(self):
        page = article(body='<!-- AUTO:BODY:START -->95-90<!-- AUTO:BODY:END -->')
        (self.root / self.PATH).write_text(page)
        self.producer_bundle(page, ta.stable_fingerprint(page.encode()))
        self.run_import()
        ta.apply_all(self.root)
        self.assertIn('data-auto-thumb', self.page())
        (self.root / self.PATH).write_text(self.page().replace('95-90', '101-90'))
        r = ta.apply_all(self.root)
        self.assertEqual(r['outdated'], [self.PATH])
        self.assertIn('data-auto-thumb', self.page())

    def test_independent_repro_expectations(self):
        """ChatGPT の単独再現スクリプト（MINI-8-independent-repro-073cad6）と同じ条件で、修正後の期待値になる。"""
        source = ('<html><head><title>test</title></head><body><article><h1>10/25 test</h1>'
                  '<!-- AUTO:PV:START --><span>7 views</span><!-- AUTO:PV:END -->'
                  '<p>confirmed article body</p></article></body></html>')
        (self.root / 'article-daily-20261025.html').write_text(source)
        self.producer_bundle(source, ta.stable_fingerprint(source.encode()))
        self.assertEqual(len(self.run_import()['imported']), 1)          # 'accepted'
        before = b'<article><h1>Result</h1><!-- AUTO:BODY:START --><p>95-90</p><!-- AUTO:BODY:END --></article>'
        self.assertFalse(ta.stable_fingerprint(before) == ta.stable_fingerprint(before.replace(b'95-90', b'101-90')))

    def test_import_reports_count_for_workflow(self):
        src = article()
        self.producer_bundle(src, ta.stable_fingerprint(src.encode()))
        out = Path(self.temp.name) / 'gh-output'
        with redirect_stdout(io.StringIO()):
            import os
            old = os.environ.get('GITHUB_OUTPUT')
            os.environ['GITHUB_OUTPUT'] = str(out)
            try:
                ta.main(['import', '--root', str(self.root), '--inbox', str(self.inbox)])
                ta.main(['import', '--root', str(self.root), '--inbox', str(self.inbox)])
            finally:
                os.environ.pop('GITHUB_OUTPUT') if old is None else os.environ.__setitem__('GITHUB_OUTPUT', old)
        self.assertEqual(out.read_text().split(), ['imported=1', 'imported=0'])


class NewestOnly(Base):
    """ChatGPT検品（bc65bb3）の P1-2・P2-4：採用の候補は記事ごとに最新の完成画像だけ。"""

    def put(self, body, pv, prepared_at, color):
        src = article(body=body, pv=pv)
        return bundle(self.inbox, self.PATH, src, image=png(color), prepared_at=prepared_at)

    def test_valid_but_older_bundle_gets_terminal_mark(self):
        """P1-2：同じ本文の PV=5 と PV=40 の2つ。新しい方を採用し、古い方は終わりの印で未取り込みに残さない。"""
        (self.root / self.PATH).write_text(article(pv=40))
        old = self.put('本文A', 5, '2026-10-26T01:00:00+00:00', (1, 1, 1))
        new = self.put('本文A', 40, '2026-10-26T02:00:00+00:00', (2, 2, 2))
        r = self.run_import()
        self.assertEqual([x['id'] for x in r['imported']], [new['id']])
        seen = ta.registry(self.root)['seen']
        self.assertEqual(seen[old['id']], 'superseded:' + new['id'])     # 終わりの印＝送信側の awaiting から外れる
        self.assertEqual(set(seen), {old['id'], new['id']})
        again = self.run_import()
        self.assertEqual((again['imported'], again['superseded'], again['rejected']), ([], [], []))

    def test_body_reverting_to_old_version_does_not_bring_back_old_image(self):
        """P2-4：v1の画像A→v2の画像B（新しい）→本文がv1へ戻っても、Aへ自動で戻らない。"""
        a = self.put('本文v1', None, '2026-10-26T01:00:00+00:00', (1, 1, 1))
        (self.root / self.PATH).write_text(article(body='本文v1'))
        self.run_import(); ta.apply_all(self.root)
        self.assertIn(f'data-auto-thumb="{a["id"]}"', self.page())
        b = self.put('本文v2', None, '2026-10-26T02:00:00+00:00', (2, 2, 2))
        (self.root / self.PATH).write_text(self.page().replace('本文v1', '本文v2'))
        self.run_import(); ta.apply_all(self.root)
        self.assertIn(f'data-auto-thumb="{b["id"]}"', self.page())
        (self.root / self.PATH).write_text(self.page().replace('本文v2', '本文v1'))   # 過去の版へ戻る
        r = self.run_import(); ta.apply_all(self.root)
        self.assertEqual(r['imported'], [])
        self.assertIn(f'data-auto-thumb="{b["id"]}"', self.page())        # 新しい方の画像のまま
        self.assertTrue(ta.registry(self.root)['seen'][a['id']].startswith('superseded:'))

    def test_newer_bundle_for_other_version_replaces_older_image(self):
        """10/30「C」：本文がまだv1でも、より新しく完成した画像（v2向け）を採用する（退役させて空白にしない）。"""
        self.put('本文v1', None, '2026-10-26T01:00:00+00:00', (1, 1, 1))
        (self.root / self.PATH).write_text(article(body='本文v1'))
        self.run_import(); ta.apply_all(self.root)
        b = self.put('本文v2', None, '2026-10-26T02:00:00+00:00', (2, 2, 2))
        r = self.run_import()
        self.assertEqual(([x['id'] for x in r['imported']], r['retired']), ([b['id']], []))
        ta.apply_all(self.root)
        self.assertIn(f'data-auto-thumb="{b["id"]}"', self.page())

    def test_older_bundle_arriving_late_does_not_replace_newer_image(self):
        b = self.put('本文v2', None, '2026-10-26T02:00:00+00:00', (2, 2, 2))
        self.run_import()
        a = self.put('本文v1', None, '2026-10-26T01:00:00+00:00', (1, 1, 1))
        r = self.run_import()
        self.assertEqual(r['imported'], [])
        self.assertEqual(ta.registry(self.root)['entries'][self.PATH]['id'], b['id'])
        self.assertEqual(ta.registry(self.root)['seen'][a['id']], 'superseded:' + b['id'])

    def test_image_rejected_before_policy_change_is_marked_imported(self):
        """10/30 まで「古い版」として捨てていた採用中の画像は、取り込み済みの印に直す（送信側の未取り込みに残さない）。"""
        a = self.put('本文v1', None, '2026-10-26T01:00:00+00:00', (1, 1, 1))
        self.run_import()
        reg = ta.registry(self.root)
        reg['seen'][a['id']] = 'rejected:stale_source'
        ta.save_json(self.root / ta.REGISTRY, reg)
        self.run_import()
        self.assertEqual(ta.registry(self.root)['seen'][a['id']], 'imported')

class DeliverCarryOver(Deliver):
    """記事ごとに最新の完成画像を渡す。生成側の台帳が保留（PV_ONLY_DUPLICATE）の job を指していても引き継ぐ。"""

    def test_latest_pointing_to_blocked_job_still_delivers_newest_ready(self):
        self.state.write_text(json.dumps({'latest': {'article-daily-20261025.html': 'blocked0000000000000'}}))
        self.assertEqual(self.deliver(), [self.items['新']])

    def test_works_without_state(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(thumb_deliver.deliver(self.ready, self.repo, None), [self.items['新']])

    def test_broken_newest_ready_does_not_fall_back_to_older_version(self):
        (self.ready / self.items['新'] / 'thumbnail.png').write_bytes(png((9, 9, 9)))   # SHA不一致
        import contextlib
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.deliver(), [])
        tree = subprocess.run(['git', '-C', str(self.remote), 'ls-tree', '-r', '--name-only', 'thumb-inbox'],
                              text=True, capture_output=True).stdout
        self.assertNotIn(self.items['旧'], tree)                 # 古い版へは戻らない


class DeliverRetry(Deliver):
    """P1-2：送信に失敗しても、新しい画像が無い次の回で送り直される。"""

    def test_failed_push_is_retried_on_next_run_without_new_images(self):
        good = git(self.repo, 'remote', 'get-url', 'origin').strip()
        git(self.repo, 'remote', 'set-url', 'origin', str(Path(self.temp.name) / 'unreachable.git'))
        with redirect_stdout(io.StringIO()), self.assertRaises(thumb_deliver.DeliverError):
            import contextlib
            with contextlib.redirect_stderr(io.StringIO()):
                thumb_deliver.deliver(self.ready, self.repo, self.state)
        git(self.repo, 'remote', 'set-url', 'origin', good)
        self.assertEqual(self.deliver(), [self.items['新']])             # 生成の新規なし（pending0）でも送り直す
        self.assertEqual(self.deliver(), [])                             # 以後は変化なし

    def test_push_race_is_retried_with_fresh_branch(self):
        from unittest import mock
        real = thumb_deliver.git
        calls = {'push': 0}

        def flaky(repo, *args, check=True):
            if args and args[0] == 'push':
                calls['push'] += 1
                if calls['push'] == 1:
                    return subprocess.CompletedProcess(args, 1, '', 'rejected (fetch first)')
            return real(repo, *args, check=check)

        import contextlib
        with mock.patch.object(thumb_deliver, 'git', side_effect=flaky), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.deliver(), [self.items['新']])
        self.assertEqual(calls['push'], 2)
        self.assertEqual(git(self.remote, 'ls-tree', '--name-only', 'thumb-inbox', 'inbox/').split(),
                         [f'inbox/{self.items["新"]}'])

    def test_cli_exit_code_is_1_when_push_keeps_failing(self):
        git(self.repo, 'remote', 'set-url', 'origin', str(Path(self.temp.name) / 'unreachable.git'))
        import contextlib, sys
        from unittest import mock
        argv = ['thumb_deliver', '--ready', str(self.ready), '--repo', str(self.repo), '--state', str(self.state)]
        with mock.patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(thumb_deliver.main(), 1)


class DeliverDispatch(Deliver):
    """送れた時だけ、サイトの取り込み（thumbs.yml）を gh で起動する。起動の失敗は送信の失敗にしない。"""

    def run_with_gh(self, returncode=0, origin='https://github.com/genjoK0216KK/bleague-matome.git'):
        from unittest import mock
        import contextlib
        calls = []
        real_run = subprocess.run

        def fake_run(cmd, *a, **k):
            if cmd and cmd[0] == 'gh':
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, returncode, '', '' if returncode == 0 else 'HTTP 403')
            return real_run(cmd, *a, **k)

        real_slug = thumb_deliver.repo_slug
        with mock.patch.object(thumb_deliver.subprocess, 'run', side_effect=fake_run), \
             mock.patch.object(thumb_deliver, 'repo_slug', side_effect=lambda r, remote='origin': real_slug(r, remote) or 'genjoK0216KK/bleague-matome'), \
             contextlib.redirect_stderr(io.StringIO()):
            added = self.deliver()
        return added, calls

    def test_ingest_is_started_after_successful_push(self):
        added, calls = self.run_with_gh()
        self.assertEqual(added, [self.items['新']])
        self.assertEqual(calls, [['gh', 'workflow', 'run', 'thumbs.yml', '--repo', 'genjoK0216KK/bleague-matome', '--ref', 'main']])

    def site_ingested(self, ids):
        """サイトが取り込んだ状態（main の data/thumbs/registry.json に seen が載る）を作る。"""
        reg = {'version': 1, 'entries': {}, 'seen': {i: 'imported' for i in ids}, 'log': []}
        (self.repo / 'data/thumbs').mkdir(parents=True, exist_ok=True)
        (self.repo / 'data/thumbs/registry.json').write_text(json.dumps(reg))
        git(self.repo, 'checkout', '-q', 'main'); git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'ingested'); git(self.repo, 'push', '-q', 'origin', 'main')

    def test_nothing_new_and_already_ingested_does_not_start_ingest(self):
        self.deliver()
        self.site_ingested([self.items['新']])
        added, calls = self.run_with_gh()
        self.assertEqual((added, calls), ([], []))

    def test_delivered_but_not_ingested_is_restarted_on_next_call(self):
        added, calls = self.run_with_gh(returncode=1)          # 送信は成功、取り込みの起動は失敗
        self.assertEqual((added, len(calls)), ([self.items['新']], 1))
        added, calls = self.run_with_gh()                      # 新しい画像なしで次に呼ばれた時
        self.assertEqual(added, [])
        self.assertEqual(len(calls), 1)                        # 起動し直す
        self.site_ingested([self.items['新']])
        added, calls = self.run_with_gh()
        self.assertEqual((added, calls), ([], []))             # 取り込まれた後は起動しない

    def test_failed_dispatch_does_not_fail_delivery(self):
        added, calls = self.run_with_gh(returncode=1)
        self.assertEqual(added, [self.items['新']])
        self.assertEqual(len(calls), 1)

    def test_repo_slug_from_github_remotes(self):
        for url in ('https://github.com/genjoK0216KK/bleague-matome.git', 'git@github.com:genjoK0216KK/bleague-matome.git',
                    'https://github.com/genjoK0216KK/bleague-matome'):
            git(self.repo, 'remote', 'set-url', 'origin', url)
            self.assertEqual(thumb_deliver.repo_slug(self.repo), 'genjoK0216KK/bleague-matome')


class ThumbsWorkflow(unittest.TestCase):
    """P1-3：取り込みは thumb-inbox への push で即動き、通常更新の成功に依存しない。"""
    ROOT = Path(__file__).resolve().parents[1]

    def test_ingest_is_dispatched_with_hourly_fallback_outside_site_update_queue(self):
        text = (self.ROOT / '.github/workflows/thumbs.yml').read_text()
        trigger = re.search(r'^on:\n(.*?)^permissions:', text, re.M | re.S).group(1)
        self.assertIn('workflow_dispatch:', trigger)
        self.assertNotIn('schedule', trigger)    # 定期起動は持たない（本人 10/26「巡回は必要ない」）
        self.assertNotIn('cron', trigger)
        self.assertNotIn('push:', trigger)       # thumb-inbox には定義が無いので push では起動できない
        self.assertIn('group: thumbs', text)
        self.assertNotIn('site-update', text.split('concurrency:')[1].split('jobs:')[0])
        self.assertIn("get('enabled') is True", text)
        self.assertIn("grep -q '^imported=[1-9]'", text)              # 新しく採用した時だけ build
        self.assertIn('python scripts/publish_update.py', text)
        self.assertIn('git reset -q --hard origin/main', text)        # ぶつかったら最新から作り直す
        self.assertNotIn('push origin', text)                         # thumb-inbox や main へ直接 push しない

    def test_mac_side_patches_follow_creation_only_policy(self):
        d = self.ROOT / 'docs/mini8-mac-side'
        self.assertEqual(sorted(p.name for p in d.iterdir()),
                         ['01-OPERATIONS-creation-requests.patch', '02-thumbnail_queue-requests.patch', 'SETUP.md'])
        setup = (d / 'SETUP.md').read_text()
        self.assertNotIn('StartInterval', setup)
        self.assertIn("| /usr/bin/security -i", setup)                   # 合言葉は標準入力で渡す（引数に出さない）
        self.assertNotIn('-w "$(', setup)
        p1 = (d / '01-OPERATIONS-creation-requests.patch').read_text()
        added = '\n'.join(l for l in p1.splitlines() if l.startswith('+'))
        self.assertIn('thumbnail_queue.py requests', added)              # 作成イベントの受け取り
        self.assertIn('Webhook', added)                                   # 記事ができたら直接知らせる（本人 10/27）
        self.assertIn('codex exec --ephemeral', added)                    # 既存の会話 01a16fa6 は使わない
        self.assertIn('新しいタイマー巡回は作らない', added)
        self.assertNotIn('毎回の定期回', p1)                               # 止めた巡回を前提にしない
        self.assertNotIn('〈　', p1)                                       # 担当の空欄が残っていない
        self.assertNotIn('automation-2 を再開', p1)
        p2 = (d / '02-thumbnail_queue-requests.patch').read_text()
        changed = [l for l in p2.splitlines() if l[:1] in '+-' and not l.startswith(('+++', '---'))]
        # 生成側の本文指紋・job ID の定義は変えない（変えると既存記事が全件作り直しになる。独立検品 10/26）
        for line in changed:
            for frozen in ('def article_text', 'def editorial_fingerprint', 'def request_id', "html = raw.decode('utf-8')"):
                self.assertNotIn(frozen, line)

if __name__ == '__main__':
    unittest.main()
