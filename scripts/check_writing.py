#!/usr/bin/env python3
"""記事の文章が docs/writing-rules.md に沿っているかを確かめる（本人 2026-10-28「改行とか読みやすい文章にして」）。

数えるのは記事本文（article.article の中の p・li・div.note）だけ。出典欄（.source / .sources）・表と表の凡例・関連記事・パンくず・広告は数えない。
- 読点「、」が2つ以上の文
- 3文以上の段落（本人 2026-11-03「改行とか」）
- 作業の経緯の言葉（読者に関係ない「スニペット」「WebFetch」など）
- 本文の念押し・確かめ方（「確認しました」「ご確認ください」など。本人 2026-11-03「注釈が多すぎる」）
- 記事ごとの免責（「本記事は各公式発表…」）。免責はサイト全体で about.html の1か所だけ（本人 2026-11-03）
- 更新の注記が2つ以上
- 出典欄：URLをそのままリンク文字にしたもの、リンクの外の説明書き
使い方：python3 scripts/check_writing.py article-daily-20261028.html [...]  指摘があれば終了コード1。
標準ライブラリだけで動く。
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

MAX_COMMAS = 1
MAX_SENTENCES = 2
PROCESS_WORDS = ('スニペット', 'WebFetch', 'Web検索', '名前解決', '時台の再確認', '時台updates', '取得作業', 'egress', '接続先', '結果表示')
NOTE_WORDS = ('確認しました', 'で一致して', 'ご確認ください', '可能性があります', '保証するものではありません', '独自に集計', '予測したものですか', '予測ですか')
DISCLAIMER = re.compile(r'^本記事は|公式記録・発表は訂正される場合があります')
UPDATE_NOTE = re.compile(r'\d{1,2}時台?[のに]?更新')
SKIP_CLASSES = {'source', 'sources', 'tablewrap', 'table-note', 'card', 'breadcrumb', 'pmeta', 'adbox'}
SKIP_TAGS = {'table', 'script', 'style', 'h1', 'h2', 'h3', 'h4'}
BLOCKS = {'p', 'li'}
VOID = {'br', 'img', 'hr', 'meta', 'link', 'input', 'source', 'wbr'}
SENTENCE_END = re.compile(r'(?<=[。！？!?])')


class Blocks(HTMLParser):
    """記事本文の段落ごとのテキスト。<br> の前と後は別の行として数える。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []                 # (tag, skip, block)
        self.in_article = 0
        self.current = None
        self.blocks = []

    def skipping(self):
        return any(skip for _, skip, _ in self.stack)

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            if tag == 'br' and self.current is not None:      # 改行の後は別の行として数える
                self.blocks.append(''.join(self.current))
                self.current = []
            return
        classes = set((dict(attrs).get('class') or '').split())
        if tag == 'article' and 'article' in classes:
            self.in_article += 1
        skip = tag in SKIP_TAGS or bool(classes & SKIP_CLASSES)
        block = (self.in_article and not skip and not self.skipping() and self.current is None
                 and (tag in BLOCKS or (tag == 'div' and 'note' in classes)))
        if block:
            self.current = []
        self.stack.append((tag, skip, block))

    def handle_endtag(self, tag):
        while self.stack:
            name, _, block = self.stack.pop()
            if block:
                self.blocks.append(''.join(self.current))
                self.current = None
            if name == 'article' and self.in_article:
                self.in_article -= 1
            if name == tag:
                break

    def handle_data(self, data):
        if self.current is not None and not self.skipping():
            self.current.append(data)


class Sources(HTMLParser):
    """出典欄の行ごとに、リンクの文字とリンクの外の文字を分ける。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.in_link = False
        self.in_summary = False
        self.lines = [['', '']]          # [リンクの文字, リンクの外の文字]

    def handle_starttag(self, tag, attrs):
        classes = set((dict(attrs).get('class') or '').split())
        if self.depth:
            if tag not in VOID:
                self.depth += 1
            if tag == 'a':
                self.in_link = True
            elif tag == 'summary':
                self.in_summary = True
            elif tag in ('br', 'li'):
                self.lines.append(['', ''])
        elif classes & {'source', 'sources'}:
            self.depth = 1

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == 'a':
            self.in_link = False
        elif tag == 'summary':
            self.in_summary = False
        self.depth -= 1

    def handle_data(self, data):
        if self.depth and not self.in_summary:
            self.lines[-1][0 if self.in_link else 1] += data


def check_sources(html):
    parser = Sources()
    parser.feed(html)
    found = []
    for link, outside in parser.lines:
        link = link.strip()
        outside = re.sub(r'^出典[:：]?|[\s()（）、・]', '', outside)
        if link.startswith('http'):
            found.append(f'出典：URLをそのままリンクの文字にしない（媒体名：何の記事か（日付）にする）「{link[:40]}」')
        if outside:
            found.append(f'出典：リンクの外に説明を書かない「{outside[:40]}」')
    return found


def sentences(text):
    return [s.strip() for s in SENTENCE_END.split(' '.join(text.split())) if s.strip()]


def check(html):
    """指摘の一覧（文字列）。"""
    parser = Blocks()
    parser.feed(html)
    found = []
    updates = 0
    for n, block in enumerate([b for b in parser.blocks if b.strip()], 1):
        sents = sentences(block)
        if len(sents) > MAX_SENTENCES:
            found.append(f'段落{n}：{len(sents)}文あります（2文までに分ける）「{sents[0][:30]}…」')
        if UPDATE_NOTE.search(block):
            updates += 1
        if DISCLAIMER.search(block.strip()):
            found.append(f'段落{n}：記事ごとの免責は書かない（サイト全体の about.html に1か所ある）「{block.strip()[:24]}…」')
            continue
        for word in NOTE_WORDS:
            if word in block:
                found.append(f'段落{n}：念押し・確かめ方の言葉「{word}」（本文から消す。根拠は出典欄だけ）')
        for s in sents:
            if s.count('、') > MAX_COMMAS:
                found.append(f'段落{n}：読点が{s.count("、")}つ「{s[:60]}」')
        for word in PROCESS_WORDS:
            if word in block:
                found.append(f'段落{n}：作業の経緯の言葉「{word}」（消す）')
    if updates > 1:
        found.append(f'更新の注記が{updates}つあります（最新の1つにまとめる）')
    return found + check_sources(html)


def main(paths):
    bad = 0
    for path in paths:
        found = check(Path(path).read_text(encoding='utf-8'))
        print(f'{path}：' + ('指摘なし' if not found else f'{len(found)}件'))
        for line in found:
            print('  ' + line)
        bad += len(found)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
