#!/usr/bin/env python3
"""バスケ男子日本代表の放送予定を、読者のカレンダーに登録できるようにする（本人 2026-11-24
「放映スケジュールと放映チャンネルをカレンダーに登録するツールを作って欲しい。記事に差し込みたい」）。

元データ：data/jpn_broadcast.json（JBA公式で確かめた試合・放送だけ。時刻は日本時間）
作るもの：
  - calendar/japan-national.ics … 全試合の購読用カレンダー（webcal で購読すると、追加した試合も届く）
  - calendar/<id>.ics            … 1試合ずつの登録用（iPhone・Mac・Outlook）
  - 記事の <!-- AUTO:JPN-CAL:START --> 〜 <!-- AUTO:JPN-CAL:END --> の中身
    （試合ごとの放送カードと「Googleカレンダーに追加」「iPhone・Outlookに追加」ボタン）
    START の印に ids="a,b" を書くと、その試合だけを出す。書かなければ全試合。

カレンダーの予定は「見始められる時刻」から始める：テレビ・配信のうち試合開始より前に始まる放送があれば
その時刻（例：テレ朝 3:45〜）、なければ試合開始。終わりは試合開始の2時間15分後。30分前に通知。
入力が同じなら出力も同じ（DTSTAMP はデータの updated から作る）。外部取得なし・標準ライブラリだけ。

使い方：python3 scripts/jpn_calendar.py   （変わったファイルだけ書く）
"""
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data/jpn_broadcast.json'
OUT = ROOT / 'calendar'
SITE = 'https://basuke-matome.jp/'
FEED = 'calendar/japan-national.ics'
JST = timezone(timedelta(hours=9))
GAME_LENGTH = timedelta(hours=2, minutes=15)
WEEK = '月火水木金土日'
BLOCK = re.compile(r'(<!-- AUTO:JPN-CAL:START(?P<attrs>[^>]*?)-->)(?P<body>.*?)(<!-- AUTO:JPN-CAL:END -->)', re.S)


def jst(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%M').replace(tzinfo=JST)


def utc(dt):
    return dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def hm(dt):
    return f'{dt.hour}:{dt.minute:02d}'


def window(g):
    tip = jst(g['tipoff'])
    early = [jst(t['start']) for t in g.get('tv', []) if jst(t['start']) <= tip]
    return min(early + [tip]), tip + GAME_LENGTH


def tv_label(t, tip):
    if t.get('start_label'):
        return t['name'] + ' ' + t['start_label']
    s = jst(t['start'])
    day = '' if s.date() == tip.date() else f'{s.day}日({WEEK[s.weekday()]}) '
    return t['name'] + ' ' + day + hm(s) + '〜'


def short_tv(name):
    return {'テレビ朝日系列': 'テレ朝系', '日本テレビ系列': '日テレ系'}.get(name, name)


def summary(g):
    tip = jst(g['tipoff'])
    live_tv = [short_tv(t['name']) for t in g.get('tv', []) if jst(t['start']) <= tip]
    later_tv = [short_tv(t['name']) + ' ' + hm(jst(t['start'])) + '〜' for t in g.get('tv', []) if jst(t['start']) > tip]
    head = '🏀 バスケ日本代表 vs ' + g['opponent'] + '｜' + '・'.join(live_tv + g.get('live', []))
    return head + ('（' + '・'.join(later_tv) + '）' if later_tv else '')


def details(g, article=None):
    tip = jst(g['tipoff'])
    lines = [g['event'] + '（' + ('ホーム' if g.get('home') else 'アウェー') + '）',
             '試合開始：' + g['tipoff_label'] + '（日本時間）']
    if g.get('tv'):
        lines.append('テレビ：' + '／'.join(tv_label(t, tip) for t in g['tv']))
    if g.get('live'):
        lines.append('ライブ配信：' + '・'.join(g['live']))
    lines.append('会場：' + g['venue'])
    if article:
        lines.append('記事：' + SITE + article)
    lines.append('出典：日本バスケットボール協会 ' + g['source'])
    return lines


def ics_text(s):
    return s.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')


def fold(line):
    """iCalendar の1行は75バイトまで。超える分は折り返す（UTF-8 の文字を割らない）。"""
    out, cur = [], b''
    for ch in line:
        b = ch.encode('utf-8')
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode('utf-8'))
            cur = b''
        cur += b
    out.append(cur.decode('utf-8'))
    return '\r\n '.join(out)


def vevent(g, stamp):
    start, end = window(g)
    return ['BEGIN:VEVENT',
            'UID:' + g['id'] + '@basuke-matome.jp',
            'DTSTAMP:' + stamp,
            'DTSTART:' + utc(start),
            'DTEND:' + utc(end),
            'SUMMARY:' + ics_text(summary(g)),
            'DESCRIPTION:' + ics_text('\n'.join(details(g))),
            'LOCATION:' + ics_text(g['venue']),
            'URL:' + g['source'],
            'BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + ics_text(summary(g)), 'TRIGGER:-PT30M', 'END:VALARM',
            'END:VEVENT']


def calendar(games, name, stamp):
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//basuke-matome.jp//jpn-calendar//JA', 'CALSCALE:GREGORIAN',
             'METHOD:PUBLISH', 'X-WR-CALNAME:' + ics_text(name), 'X-WR-TIMEZONE:Asia/Tokyo',
             'REFRESH-INTERVAL;VALUE=DURATION:PT12H', 'X-PUBLISHED-TTL:PT12H']
    for g in games:
        lines += vevent(g, stamp)
    lines.append('END:VCALENDAR')
    return '\r\n'.join(fold(x) for x in lines) + '\r\n'


def google_url(g, article):
    start, end = window(g)
    q = {'action': 'TEMPLATE', 'text': summary(g), 'dates': utc(start) + '/' + utc(end),
         'details': '\n'.join(details(g, article)), 'location': g['venue'], 'ctz': 'Asia/Tokyo'}
    return 'https://calendar.google.com/calendar/render?' + urlencode(q, quote_via=quote)


def card(g, article):
    tip = jst(g['tipoff'])
    e = html.escape
    rows = []
    if g.get('tv'):
        rows.append('<li><span class="jc-k">テレビ</span>' + e('／'.join(tv_label(t, tip) for t in g['tv'])) + '</li>')
    if g.get('live'):
        rows.append('<li><span class="jc-k">ライブ配信</span>' + e('・'.join(g['live'])) + '</li>')
    return (
        '<div class="jc-card">'
        '<div class="jc-date"><span class="jc-md">' + f'{tip.month}/{tip.day}' + '</span>'
        '<span class="jc-wd">(' + WEEK[tip.weekday()] + ')</span><span class="jc-time">' + hm(tip) + ' 開始</span></div>'
        '<div class="jc-main"><p class="jc-vs">日本 vs ' + e(g['opponent']) + '<span class="jc-ev">' + e(g['event']) + '・'
        + ('ホーム' if g.get('home') else 'アウェー') + '</span></p>'
        '<ul class="jc-rows">' + ''.join(rows) + '</ul>'
        '<div class="jc-btns"><a class="jc-btn jc-google" href="' + e(google_url(g, article)) + '" target="_blank" rel="noopener">Googleカレンダーに追加</a>'
        '<a class="jc-btn" href="calendar/' + e(g['id']) + '.ics" download>iPhone・Outlookに追加</a></div>'
        '</div></div>')


STYLE = ('<style>'
         '.jpn-cal{margin:28px 0;padding:16px;border:2px solid #151a18;border-radius:8px;background:#fbfdf5}'
         '.jpn-cal h2{margin-top:0}'
         '.jc-card{display:flex;gap:14px;padding:14px 0;border-top:1px solid #d5dad6}'
         '.jc-card:first-of-type{border-top:0}'
         '.jc-date{flex:0 0 84px;display:flex;flex-direction:column;align-items:center;justify-content:center;'
         'background:#151a18;color:#fff;border-radius:6px;padding:10px 4px;text-align:center;line-height:1.2}'
         '.jc-md{font-size:26px;font-weight:800;color:#ccf43b}'
         '.jc-wd{font-size:13px}'
         '.jc-time{font-size:13px;margin-top:4px;font-weight:700}'
         '.jc-main{flex:1;min-width:0}'
         '.jpn-cal .jc-vs{margin:0 0 6px;font-size:18px;font-weight:800}'
         '.jc-ev{display:block;font-size:12px;font-weight:400;color:#525b55}'
         '.jpn-cal .jc-rows{list-style:none;margin:0 0 10px;padding:0}'
         '.jpn-cal .jc-rows li{margin:0 0 4px;padding:0;font-size:14px}'
         '.jc-k{display:inline-block;min-width:5.5em;margin-right:6px;padding:1px 6px;border-radius:3px;'
         'background:#ccf43b;color:#151a18;font-size:12px;font-weight:700;text-align:center}'
         '.jc-btns{display:flex;flex-wrap:wrap;gap:8px}'
         '.jpn-cal .jc-btn{display:inline-block;padding:9px 12px;border:2px solid #151a18;border-radius:6px;'
         'background:#fff;color:#151a18;font-size:14px;font-weight:700;text-decoration:none;line-height:1.2}'
         '.jpn-cal .jc-btn:hover{background:#151a18;color:#ccf43b}'
         '.jpn-cal .jc-google{background:#151a18;color:#ccf43b}'
         '.jc-sub{margin-top:8px;padding-top:14px;border-top:2px dashed #d5dad6}'
         '.jpn-cal .jc-sub p{margin:0 0 8px;font-size:14px}'
         '@media(max-width:420px){.jc-card{flex-direction:column}.jc-date{flex-direction:row;gap:8px;flex-basis:auto;padding:8px}'
         '.jc-md{font-size:22px}.jc-time{margin-top:0}}'
         '</style>')


def block(games, article):
    feed_https = SITE + FEED
    webcal = 'webcal://' + feed_https.split('://', 1)[1]
    google_sub = 'https://calendar.google.com/calendar/r?cid=' + quote(webcal, safe='')
    n = len(games)
    return ('\n<section class="jpn-cal" id="jpn-calendar">' + STYLE +
            '<h2>放送予定をカレンダーに登録</h2>' +
            '<p>ボタンを押すと、試合の日時と放送チャンネルがカレンダーに入ります。予定の30分前に通知が届きます。</p>' +
            ''.join(card(g, article) for g in games) +
            '<div class="jc-sub"><p>' + (f'{n}試合をまとめて登録するなら、カレンダーの購読が便利です。' if n > 1 else 'カレンダーの購読もできます。') +
            '次の日本代表戦の放送予定も、ここに追加していきます。</p>'
            '<div class="jc-btns"><a class="jc-btn jc-google" href="' + html.escape(google_sub) + '" target="_blank" rel="noopener">Googleカレンダーで購読</a>'
            '<a class="jc-btn" href="' + html.escape(webcal) + '">iPhone・Macで購読</a></div></div>'
            '</section>\n')


def write_if_changed(path, text, newline=None):
    old = path.read_bytes() if path.exists() else None
    if old == text.encode('utf-8'):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline=newline or '') as f:
        f.write(text)
    return True


def main():
    data = json.loads(DATA.read_text(encoding='utf-8'))
    games = sorted(data['games'], key=lambda g: g['tipoff'])
    stamp = data.get('updated', '2026-11-24').replace('-', '') + 'T000000Z'
    changed = []
    if write_if_changed(ROOT / FEED, calendar(games, data['feed_title'], stamp)):
        changed.append(FEED)
    for g in games:
        p = OUT / (g['id'] + '.ics')
        if write_if_changed(p, calendar([g], data['feed_title'], stamp)):
            changed.append(str(p.relative_to(ROOT)))
    by_id = {g['id']: g for g in games}
    for art in sorted(ROOT.glob('article-*.html')):
        text = art.read_text(encoding='utf-8')
        if 'AUTO:JPN-CAL:START' not in text:
            continue

        def repl(m):
            ids = re.search(r'ids="([^"]*)"', m.group('attrs'))
            chosen = [by_id[i] for i in ids.group(1).split(',') if i in by_id] if ids else games
            return m.group(1) + block(chosen, art.name) + m.group(4)

        new = BLOCK.sub(repl, text)
        if write_if_changed(art, new):
            changed.append(art.name)
    print('[jpn_calendar] 更新：' + ('、'.join(changed) if changed else 'なし'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
