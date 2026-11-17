"""B.LEAGUE CARD 公式マスタ（ログイン不要）から、FANTASY ARENA の「最高の手札」計算に要る分だけを保存する。

python3 scripts/fantasy_cards.py [--year 2026]
→ data/fantasy/cards-<year>.json  {"retrieved_at", "source", "players": {"<クラブ略称>|<名前>": {"bits", "max_rare", "star1"}}}
"""
import argparse
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'https://api-card.bleaguepark.jp/jpbl/js_master/cards_json/{year}'
PLAYER_BITS = 1 | 2 | 4 | 8 | 16          # PG SG SF PF C（マスコット・特別カードは除く）


def key(club, name):
    return club + '|' + re.sub(r'[\s・.．　=＝-]', '', name or '')


def slim(master, year):
    club = {c['id']: c['club_name_short'] for c in master['m_clubs'].values()}
    person = {p['id']: p for p in master['m_personal'].values() if p['target_year'] == year}
    players = {}
    for card in master['m_cards'].values():
        p = person.get(str(card['pd_id']))
        if card['target_year'] != year or not p or not int(p['position']) & PLAYER_BITS or p['club_id'] not in club:
            continue
        row = players.setdefault(key(club[p['club_id']], p['name']), {'bits': 0, 'max_rare': 0, 'star1': False})
        row['bits'] |= int(p['position']) & PLAYER_BITS
        row['max_rare'] = max(row['max_rare'], int(card['rare_id']))
        row['star1'] = row['star1'] or int(card['rare_id']) == 1
    return players


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', default='2026')
    year = ap.parse_args().year
    url = SOURCE.format(year=year)
    res = requests.get(url, timeout=120, headers={'User-Agent': 'Mozilla/5.0'})
    res.raise_for_status()
    players = slim(res.json(), year)
    if len(players) < 300:
        raise SystemExit('カード数が少なすぎるので保存しません: %d' % len(players))
    out = ROOT / 'data/fantasy' / ('cards-' + year + '.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
    out.write_text(json.dumps({'retrieved_at': now, 'source': url, 'players': dict(sorted(players.items()))},
                              ensure_ascii=False, indent=0), encoding='utf-8')
    print(out, len(players))


if __name__ == '__main__':
    main()
