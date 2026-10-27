#!/usr/bin/env python3
"""記事の文章が docs/writing-rules.md に沿っているかを確かめる（本人 2026-10-28「改行とか読みやすい文章にして」）。

数えるのは記事本文（article.article の中の p・li・div.note）だけ。出典欄（.source）・表と表の凡例・関連記事・パンくず・広告は数えない。
- 読点「、」が2つ以上の文
- 4文以上の段落
- 作業の経緯の言葉（読者に関係ない「スニペット」「WebFetch」など）
使い方：python3 scripts/check_writing.py article-daily-20261028.html [...]  指摘があれば終了コード1。
標準ライブラリだけで動く。
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

MAX_COMMAS = 1
MAX_SENTENCES = 3
PROCESS_WORDS = ('スニペット', 'WebFetch', 'Web検索', '名前解決', '時台の再確認', '時台updates', '取得作業', 'egress')
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


def sentences(text):
    return [s.strip() for s in SENTENCE_END.split(' '.join(text.split())) if s.strip()]


def check(html):
    """指摘の一覧（文字列）。"""
    parser = Blocks()
    parser.feed(html)
    found = []
    for n, block in enumerate([b for b in parser.blocks if b.strip()], 1):
        sents = sentences(block)
        if len(sents) > MAX_SENTENCES:
            found.append(f'段落{n}：{len(sents)}文あります（3文までに分ける）「{sents[0][:30]}…」')
        for s in sents:
            if s.count('、') > MAX_COMMAS:
                found.append(f'段落{n}：読点が{s.count("、")}つ「{s[:60]}」')
        for word in PROCESS_WORDS:
            if word in block:
                found.append(f'段落{n}：作業の経緯の言葉「{word}」（出典欄へ移すか消す）')
    return found


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
