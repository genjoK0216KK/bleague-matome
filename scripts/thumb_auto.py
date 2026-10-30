#!/usr/bin/env python3
"""自動生成サムネ（ChatGPT が Mac mini で生成・検品した PNG）の取り込みと記事への差し替え。

流れ（MINI-8、10/25 本人「サムネの自動差し替えまで進めて」）
  1. 受け渡し：Mac mini の ready/<id>/ を tools/thumb_deliver.py が専用ブランチ thumb-inbox の
     inbox/<id>/{manifest.json, thumbnail.png, source.html} に置く（main には書かない）。
  2. 取り込み（import）：thumbs.yml（送信直後に起動・1時間ごとの保険）と update.yml がそのブランチを読み取り専用で展開し、本スクリプトが検査する。
       - manifest の形・status・style・ID（記事パス＋本文指紋から再計算）・画像の SHA256・PNG 寸法・制作側の5項目QA
       - 同梱の固定原文 source.html の blob SHA と本文指紋が manifest と一致すること
       - 記事がまだあること。いまの本文と版が違っても採用する（本人 10/30「C」：空白にせず、新しい画像が届くまで
         前の画像を出す。毎日の記事は本文が変わると thumb_requests.py が作り直しを積む）
     合格した画像だけを Web 用（本文 1280px JPEG）と OGP 用（1200×630、余白で全体を収める＝注記を切らない）に
     変換して thumbs/auto/ に置き、data/thumbs/registry.json に記録する。
  3. 適用（apply）：build.py の最初に毎回呼ぶ。登録済みの画像を eyecatch・og:image・Twitter 画像として入れる。
     記事が再生成されて既定の画像に戻っても次の build で入り直す。本文が変わった記事にも、新しい画像が届くまで
     前の画像を入れ続ける（10/30 まではここで外していたため、書き換わった記事のサムネが消えていた）。
     ただし見出しまで変わった記事（試合前の「ベスト5」が試合後に「試合結果」になる等）は、画像の主題が違うので
     外して既定の表示に戻す。thumb_requests.py が作り直しを積み、新しい画像が届けばまた入る。
     差し替えで本文の指紋は変わらないので再生成のループは起きない。同じ状態で再実行しても変更なし。

公開ゲート：data/thumbs/config.json の "enabled" が true の時だけ取り込み・適用する（既定 false）。
false の間は本番の記事・一覧に一切触れない。有効化は本人確認の後。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import sys
from datetime import datetime, timezone
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = 'data/thumbs/config.json'
REGISTRY = 'data/thumbs/registry.json'
OUT_DIR = 'thumbs/auto'
SITE = 'https://basuke-matome.jp/'
STYLES = ('ink-lime-portrait-v3',)
QA_KEYS = ('text_and_numbers', 'source_qualifiers', 'likeness_or_no_named_person', 'layout', 'ai_label')
ARTICLE = re.compile(r'article-[A-Za-z0-9_-]*?\d{8}\.html')
LOG_LIMIT = 80
EYECATCH_W, OG_W, OG_H = 1280, 1200, 630
OG_BG = (21, 26, 24)          # #151A18（サイトの黒）


# ------------------------------------------------ 本文の指紋（生成側 thumbnail_queue.py と同じ定義）

class _ArticleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        if tag in ('h1', 'h2', 'h3', 'p', 'tr', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag in ('td', 'th'):
            self.parts.append(' | ')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def article_text(raw):
    """生成側 thumbnail_queue.article_text のコピー（同じ入力で同じ文字列になること）。"""
    parser = _ArticleText()
    html = raw.decode('utf-8') if isinstance(raw, bytes) else raw
    article = re.search(r'<article\b[^>]*>([\s\S]*?)</article>', html, re.I)
    html = article[1] if article else html
    related = re.search(r'<h[2-6]\b[^>]*>\s*関連記事\s*</h[2-6]>', html, re.I)
    if related:
        html = html[:related.start()]
    parser.feed(html)
    return '\n'.join(' '.join(line.split()) for line in ''.join(parser.parts).splitlines() if line.strip())


def editorial_fingerprint(raw):
    return hashlib.sha256(article_text(raw).encode()).hexdigest()


# 本文ではない自動枠だけを許可リストで除く（閲覧数・広告・計測タグ）。これ以外の AUTO 枠（本文・表など）は
# 照合に含めるので、得点などが変われば指紋も変わる。
# 生成側（Mac mini の thumbnail_queue.py）の指紋は従来どおり（自動枠込み）で変えない。変えると既存の記事が
# すべて新しいIDに見えて作り直しになるため（独立検品 10/26）。受け取り側は生成側の指紋をそのまま固定原文で
# 確かめ、いまの本文との版の照合だけをこの正規化版で行う。閲覧数だけの変化で作り直さないことは、生成側の
# 既存の判定（PV_ONLY_DUPLICATE）が担う。
NON_EDITORIAL_AUTO = ('PV', 'AFFILIATE', 'GA')
AUTO_BLOCK = re.compile(r'<!-- AUTO:(' + '|'.join(NON_EDITORIAL_AUTO) + r'):START -->.*?<!-- AUTO:\1:END -->', re.S)


def stable_fingerprint(raw):
    """記事の中身の照合用（正規化版の本文指紋）。本文ではない自動枠（NON_EDITORIAL_AUTO）だけを除く。
    本文・見出し・表が変われば変わり、閲覧数・広告・画像URLだけの変化では変わらない。"""
    html = raw.decode('utf-8') if isinstance(raw, bytes) else raw
    return hashlib.sha256(article_text(AUTO_BLOCK.sub('', html)).encode()).hexdigest()


def blob_sha(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def request_id(path, fingerprint, style):
    return hashlib.sha256((path + '\0' + fingerprint + '\0' + style).encode()).hexdigest()[:20]


# ------------------------------------------------------------------ 状態

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return False
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)
    return True


def enabled(root):
    return load_json(Path(root) / CONFIG, {}).get('enabled') is True


def registry(root):
    reg = load_json(Path(root) / REGISTRY, {})
    reg.setdefault('version', 1)
    reg.setdefault('entries', {})     # article_path -> 採用中の画像
    reg.setdefault('seen', {})        # manifest id -> 判定（同じ版の再実行を変更なしにする）
    reg.setdefault('log', [])
    return reg


def note(reg, event, **detail):
    reg['log'].append(dict(at=now_iso(), event=event, **detail))
    del reg['log'][:-LOG_LIMIT]


class Reject(Exception):
    def __init__(self, reason, detail=''):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


# ------------------------------------------------------------------ 取り込み

def png_size(data):
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise Reject('image_invalid', 'PNG ではない')
    width, height = struct.unpack('>II', data[16:24])
    if width < 1000 or height < 500 or not 1.6 <= width / height <= 1.95:
        raise Reject('image_invalid', f'{width}x{height}')
    return width, height


def check_bundle(root, folder):
    """inbox/<id>/ を検査して、採用できる候補（dict）を返す。だめなら Reject。"""
    folder = Path(folder)
    manifest = load_json(folder / 'manifest.json', None)
    if not isinstance(manifest, dict):
        raise Reject('manifest_invalid', 'manifest.json が読めない')
    for key in ('id', 'article_path', 'editorial_fingerprint', 'source_blob_sha', 'image_sha256', 'style', 'status'):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise Reject('manifest_invalid', key)
    path, mid = manifest['article_path'], manifest['id']
    if folder.name != mid:
        raise Reject('manifest_invalid', 'フォルダ名と id が違う')
    if not ARTICLE.fullmatch(path):
        raise Reject('article_invalid', path)
    if manifest['status'] != 'ready_unpublished' or manifest['style'] not in STYLES:
        raise Reject('manifest_invalid', manifest['status'] + '/' + manifest['style'])
    # 生成側の ID は「記事パス＋本文指紋」（指紋導入前の古い記録は「記事パス＋元HTMLの blob SHA」）から作られる
    if mid not in (request_id(path, manifest['editorial_fingerprint'], manifest['style']),
                   request_id(path, manifest['source_blob_sha'], manifest['style'])):
        raise Reject('manifest_invalid', 'id が記事パスと本文指紋（または元HTML）から再計算した値と違う')
    qa = (manifest.get('brief') or {}).get('qa') or {}
    if any(qa.get(k) is not True for k in QA_KEYS):
        raise Reject('qa_incomplete', ','.join(k for k in QA_KEYS if qa.get(k) is not True))
    image = (folder / 'thumbnail.png').read_bytes() if (folder / 'thumbnail.png').exists() else b''
    if hashlib.sha256(image).hexdigest() != manifest['image_sha256']:
        raise Reject('image_hash_mismatch')
    width, height = png_size(image)
    if (manifest.get('width'), manifest.get('height')) not in ((width, height), (None, None)):
        raise Reject('image_invalid', '寸法が manifest と違う')
    source = (folder / 'source.html').read_bytes() if (folder / 'source.html').exists() else b''
    # 生成側の本文指紋は、正規化版（自動枠を除く＝現行の生成側）と旧版（自動枠込み＝既存の manifest）の
    # どちらでもよい。どちらも固定原文から再計算して一致すること。
    if blob_sha(source) != manifest['source_blob_sha'] or manifest['editorial_fingerprint'] not in (
            stable_fingerprint(source), editorial_fingerprint(source)):
        raise Reject('source_mismatch', '固定原文が manifest と一致しない')
    if not (Path(root) / path).exists():
        raise Reject('article_missing', path)
    return dict(manifest=manifest, image=image, width=width, height=height,
                stable_fingerprint=stable_fingerprint(source), title=_h1_text(source.decode('utf-8', 'replace')))


def derive(root, cand):
    """Web 用の2種類を作る（元PNGは本番に置かない）。注記を切らないよう、OGP は余白で全体を収める。"""
    from PIL import Image
    import io
    m = cand['manifest']
    stem = m['article_path'][:-5] + '-' + m['image_sha256'][:12]
    out = Path(root) / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    src = Image.open(io.BytesIO(cand['image'])).convert('RGB')
    eye = src.resize((EYECATCH_W, round(EYECATCH_W * src.height / src.width)), Image.LANCZOS)
    scale = min(OG_W / src.width, OG_H / src.height)
    fit = src.resize((round(src.width * scale), round(src.height * scale)), Image.LANCZOS)
    og = Image.new('RGB', (OG_W, OG_H), OG_BG)
    og.paste(fit, ((OG_W - fit.width) // 2, (OG_H - fit.height) // 2))
    files = {}
    for kind, img in (('eyecatch', eye), ('og', og)):
        name = f'{stem}{"" if kind == "eyecatch" else "-og"}.jpg'
        target = out / name
        if not target.exists():               # 同じ画像（同じ SHA）は作り直さない
            tmp = target.with_suffix('.tmp')
            img.save(tmp, 'JPEG', quality=86, optimize=True, progressive=True)
            os.replace(tmp, target)
        files[kind] = dict(path=f'{OUT_DIR}/{name}', width=img.width, height=img.height)
    return files


def import_inbox(root, inbox):
    """inbox/<id>/ を全部検査し、記事ごとに「検査に合格した中でいちばん新しく完成した画像」を採用する。
    いまの本文と版が違っても採用する（空白にしない）。不正なものは理由を記録して捨てる（前の画像はそのまま）。
    同じ記事のより古い画像には「置き換え済み（superseded）」の終わりの印を付ける（送信側が未取り込みと誤って
    起動を繰り返さない）。採用中の画像より古い画像には戻らない。
    戻り値：{'imported': [...], 'rejected': [...], 'superseded': [...], 'retired': [], 'unchanged': n}"""
    root, inbox = Path(root), Path(inbox)
    reg = registry(root)
    result = {'imported': [], 'rejected': [], 'superseded': [], 'retired': [], 'unchanged': 0}
    folders = sorted(p for p in inbox.iterdir() if p.is_dir()) if inbox.is_dir() else []
    valid = {}
    for folder in folders:
        mid = folder.name
        try:
            cand = check_bundle(root, folder)
        except Reject as exc:
            prior = reg['seen'].get(mid)
            if prior != 'rejected:' + exc.reason:
                reg['seen'][mid] = 'rejected:' + exc.reason
                note(reg, 'rejected', id=mid, reason=exc.reason, detail=exc.detail)
                result['rejected'].append({'id': mid, 'reason': exc.reason, 'detail': exc.detail})
            else:
                result['unchanged'] += 1
            continue
        except (OSError, ValueError) as exc:
            reg['seen'][mid] = 'rejected:error'
            note(reg, 'rejected', id=mid, reason='error', detail=type(exc).__name__)
            result['rejected'].append({'id': mid, 'reason': 'error', 'detail': type(exc).__name__})
            continue
        valid.setdefault(cand['manifest']['article_path'], []).append(cand)
    for path, cands in sorted(valid.items()):
        entry = reg['entries'].get(path)
        if entry and not entry.get('retired') and entry['id'] not in {c['manifest']['id'] for c in cands}:
            # 採用中の画像（inbox から消えたものも）と比べる＝古い画像へは戻らない
            cands = cands + [dict(manifest=dict(id=entry['id'], prepared_at=entry.get('prepared_at')), current=True)]
        cands.sort(key=lambda c: (c['manifest'].get('prepared_at') or '', c['manifest']['id']))
        top = cands[-1]
        for cand in cands[:-1]:
            mid = cand['manifest']['id']
            if cand.get('current') or mid == top['manifest']['id']:
                continue
            mark = 'superseded:' + top['manifest']['id']
            if reg['seen'].get(mid) != mark:
                reg['seen'][mid] = mark
                note(reg, 'superseded', id=mid, article=path, by=top['manifest']['id'])
                result['superseded'].append({'id': mid, 'article': path, 'by': top['manifest']['id']})
            else:
                result['unchanged'] += 1
        if top.get('current'):
            continue
        m = top['manifest']
        if entry and entry['id'] == m['id'] and entry['image_sha256'] == m['image_sha256'] and not entry.get('retired') \
                and all((root / f['path']).exists() for f in entry['files'].values()):
            if reg['seen'].get(m['id']) != 'imported':      # 10/30 まで「古い版」として捨てていた画像
                reg['seen'][m['id']] = 'imported'
            entry.setdefault('title', top['title'])         # 10/30 より前に採用した画像
            result['unchanged'] += 1
            continue
        files = derive(root, top)
        reg['entries'][path] = dict(
            id=m['id'], article_path=path, image_sha256=m['image_sha256'],
            editorial_fingerprint=m['editorial_fingerprint'], stable_fingerprint=top['stable_fingerprint'],
            source_blob_sha=m['source_blob_sha'], style=m['style'], files=files,
            source_size=[top['width'], top['height']], prepared_at=m.get('prepared_at'), imported_at=now_iso(),
            title=top['title'])
        reg['seen'][m['id']] = 'imported'
        note(reg, 'imported', id=m['id'], article=path, image=m['image_sha256'][:12])
        result['imported'].append({'id': m['id'], 'article': path})
    save_json(root / REGISTRY, reg)
    return result


# ------------------------------------------------------------------ 適用（build.py から毎回）

IMG = re.compile(r'<img\b[^>]*\bclass="eyecatch"[^>]*>')
META_AUTO = re.compile(r'[ \t]*<meta\b[^>]*\bdata-auto-thumb="[^"]*"[^>]*>\n?')


def _attr(tag, name):
    m = re.search(r'\b' + name + r'="([^"]*)"', tag)
    return unescape(m.group(1)) if m else None


def _h1_text(html):
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
    return unescape(re.sub(r'<[^>]+>', '', m.group(1))).strip() if m else ''


def apply_html(html, entry):
    """1記事分。eyecatch・og:image・Twitter 画像を entry の画像にする（何度呼んでも同じ結果）。"""
    files, mid = entry['files'], entry['id']
    eye, og = files['eyecatch'], files['og']
    img = IMG.search(html)
    if img:
        tag = img.group(0)
        default = _attr(tag, 'data-default-src')
        if default is None:
            default = _attr(tag, 'src') or ''
        alt = _attr(tag, 'alt') or _h1_text(html)
    else:
        default, alt = '', _h1_text(html)
    new = (f'<img class="eyecatch" src="{escape(eye["path"])}" width="{eye["width"]}" height="{eye["height"]}" '
           f'alt="{escape(alt)}" data-auto-thumb="{escape(mid)}" data-default-src="{escape(default)}">')
    if img:
        html = html[:img.start()] + new + html[img.end():]
    else:
        pmeta = re.search(r'<div class="pmeta">.*?</div>', html, re.S)
        if not pmeta:
            return html
        html = html[:pmeta.end()] + '\n' + new + html[pmeta.end():]
    url = SITE + og['path']
    wanted = [f'<meta {k}="{v}" content="{escape(c)}" data-auto-thumb="{escape(mid)}">' for k, v, c in (
        ('property', 'og:image', url), ('property', 'og:image:width', str(og['width'])),
        ('property', 'og:image:height', str(og['height'])), ('property', 'og:image:alt', alt),
        ('name', 'twitter:card', 'summary_large_image'), ('name', 'twitter:image', url))]
    if [m.group(0).strip() for m in META_AUTO.finditer(html)] == wanted:
        return html                    # 既に同じ内容（build が並べ替えた位置も含めてそのまま＝再実行で変化なし）
    html = META_AUTO.sub('', html)
    metas = ''.join(w + '\n' for w in wanted)
    anchor = re.search(r'<meta\b[^>]*property="og:url"[^>]*>\n?', html) or re.search(r'<meta\b[^>]*og:url[^>]*>\n?', html)
    if anchor:
        end = anchor.end() if anchor.group(0).endswith('\n') else anchor.end()
        return html[:end] + ('' if anchor.group(0).endswith('\n') else '\n') + metas + html[end:]
    return html.replace('</head>', metas + '</head>', 1)


def restore_html(html):
    """自動サムネを外して元の表示に戻す（ロールバック・本文が変わった記事）。"""
    img = IMG.search(html)
    if img and 'data-auto-thumb=' in img.group(0):
        tag = img.group(0)
        default = _attr(tag, 'data-default-src') or ''
        if default:
            back = f'<img class="eyecatch" src="{escape(default)}" alt="{escape(_attr(tag, "alt") or "")}">'
            html = html[:img.start()] + back + html[img.end():]
        else:
            end = img.end() + (1 if html[img.end():img.end() + 1] == '\n' else 0)
            start = img.start() - (1 if html[img.start() - 1:img.start()] == '\n' else 0)
            html = html[:start] + html[end:]
    return META_AUTO.sub('', html)


def apply_all(root, force=False):
    """登録済みの画像を記事へ入れる。設定が無効なら何もしない（force は試験・プレビュー用）。
    本文が画像の版から変わっていても入れる（outdated に記録するだけ）。
    戻り値：{'applied': [...], 'stale': [...], 'outdated': [...], 'unchanged': n}"""
    root = Path(root)
    result = {'applied': [], 'stale': [], 'outdated': [], 'unchanged': 0}
    if not (force or enabled(root)):
        return result
    reg = registry(root)
    for path, entry in sorted(reg['entries'].items()):
        target = root / path
        if not target.exists() or not all((root / f['path']).exists() for f in entry['files'].values()):
            result['stale'].append({'article': path, 'reason': 'missing_file'})
            continue
        html = target.read_text(encoding='utf-8')
        if entry.get('retired'):
            # 10/30 より前の記録（新しい版を採用できなかった古い画像）：既定の表示に戻す。
            new = restore_html(html)
            result['stale'].append({'article': path, 'reason': 'retired'})
        elif entry.get('title') and entry['title'] != _h1_text(html):
            # 見出しが変わった＝記事の主題が変わった：違う主題の画像は出さない（作り直しが届けば入る）。
            new = restore_html(html)
            result['stale'].append({'article': path, 'reason': 'title_changed'})
        else:
            if stable_fingerprint(html) != entry['stable_fingerprint']:
                result['outdated'].append(path)      # 本文は変わったが、新しい画像が届くまで前の画像を出す
            new = apply_html(html, entry)
        if new != html:
            tmp = target.with_suffix('.tmp')
            tmp.write_text(new, encoding='utf-8')
            os.replace(tmp, target)
            if stable_fingerprint(new) != stable_fingerprint(html):      # 安全確認：本文は変えていない
                tmp.write_text(html, encoding='utf-8')
                os.replace(tmp, target)
                raise RuntimeError('サムネ差し替えで本文の指紋が変わったため元に戻しました: ' + path)
            result['applied'].append(path)
        else:
            result['unchanged'] += 1
    return result


# ------------------------------------------------------------------ CLI

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('command', choices=['import', 'apply', 'status'])
    parser.add_argument('--root', default=str(ROOT))
    parser.add_argument('--inbox', help='inbox/<id>/ を含むフォルダ（thumb-inbox ブランチの inbox/）')
    parser.add_argument('--force', action='store_true', help='設定が無効でも実行（ローカル検証・プレビュー専用）')
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.command == 'status':
        print(json.dumps({'enabled': enabled(root), **registry(root)}, ensure_ascii=False, indent=1))
        return 0
    if not (args.force or enabled(root)):
        print('[thumb_auto] 無効（data/thumbs/config.json enabled=false）のため何もしません')
        return 0
    if args.command == 'import':
        if not args.inbox:
            parser.error('import には --inbox が必要')
        result = import_inbox(root, args.inbox)
        for r in result['rejected']:
            print(f"::notice::thumb rejected id={r['id']} reason={r['reason']} {r['detail']}")
        for r in result['imported']:
            print(f"::notice::thumb imported id={r['id']} article={r['article']}")
        output = os.environ.get('GITHUB_OUTPUT')
        if output:                                  # 取り込み専用ワークフローが「新しく採用したか」を判断する
            with open(output, 'a', encoding='utf-8') as handle:
                handle.write(f"imported={len(result['imported'])}\n")
    else:
        result = apply_all(root, force=args.force)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
