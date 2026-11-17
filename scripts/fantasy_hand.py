"""FANTASY ARENA「最高の手札」：その日の公式EFFで、あとから見て一番点が出た5人を組む。

カードの点 = EFF ×（1 ＋ レア度 ＋ ポジション一致 1.0）の切り捨て、最低1点。
デッキ・勝利・応援バッジ・特効のボーナスは入れない（人によって違うため）。
カードの有無・ポジション・レア度は data/fantasy/cards-<年>.json（scripts/fantasy_cards.py）を使う。
"""
import itertools
import json
import re
from pathlib import Path
try:
    from . import official_data as official, preview_data as data, match_articles as articles
except ImportError:
    import official_data as official
    import preview_data as data
    import match_articles as articles

SLOTS = (('PG', 1), ('SG', 2), ('SF', 4), ('PF', 8), ('C', 16))
RARE_BONUS = {1: 0, 2: 0, 3: 3, 4: 7, 5: 10}          # 10分の1単位（★3 +30% など）
STAR = {1: '☆1', 2: '★2', 3: '★3', 4: '★4', 5: '★5'}


def norm(name):
    return re.sub(r'[\s・.．　=＝-]', '', name or '')


def load_cards(root, season):
    path = Path(root) / 'data/fantasy' / ('cards-' + str(season)[:4] + '.json')
    return json.loads(path.read_text()) if path.exists() else None


def played(raw):
    t = str(raw.get('PlayTime') or '')
    m = re.fullmatch(r'(\d+):([0-5]\d)', t)
    return bool(m and (int(m[1]) or int(m[2])))


def pool(summary, cards):
    rows, uncarded = [], []
    for g in summary['games']:
        if g.get('status') in ('cancelled', 'postponed'):
            continue
        teams = {g['home_id']: g['home'], g['away_id']: g['away']}
        for raw in g.get('players', []):
            if raw.get('Category') != 1 or raw.get('PeriodCategory') != 18 or not played(raw):
                continue
            team = teams.get(str(raw.get('TeamID')))
            eff = raw.get('EFF')
            if team is None or isinstance(eff, bool) or not isinstance(eff, int):
                raise ValueError('公式EFFが未確認')
            card = cards['players'].get(team + '|' + norm(raw.get('PlayerNameJ')))
            if not card:
                uncarded.append(raw.get('PlayerNameJ') + '（' + team + '）')
                continue
            rows.append(dict(player_id=str(raw.get('PlayerID')), name=raw.get('PlayerNameJ'), team=team,
                             league=g['competition'], eff=eff, **card))
    return rows, uncarded


def score(eff, rare):
    return max(1, eff * (20 + RARE_BONUS[rare]) // 10)


def best_hand(rows, rare_of):
    cand = {}
    for slot, bit in SLOTS:
        ok = [r for r in rows if r['bits'] & bit and rare_of(r)]
        cand[slot] = sorted(ok, key=lambda r: (-score(r['eff'], rare_of(r)), int(r['player_id'] or 0)))[:6]
    best = None
    for combo in itertools.product(*cand.values()):
        if len({r['player_id'] for r in combo}) < len(SLOTS):
            continue
        total = sum(score(r['eff'], rare_of(r)) for r in combo)
        if best is None or total > best[0]:
            best = (total, combo)
    if best is None:
        return None
    return {'total': best[0], 'lineup': [dict(slot=slot, name=r['name'], team=r['team'], league=r['league'], eff=r['eff'],
                                              rare=rare_of(r), points=score(r['eff'], rare_of(r)))
                                         for (slot, _), r in zip(SLOTS, best[1])]}


def collect(root, summary):
    games = [g for g in summary['games'] if g.get('status') not in ('cancelled', 'postponed')]
    if not games:
        return None
    season = games[0].get('season') or ''
    cards = load_cards(root, season)
    if not cards:
        return {'error': 'カードデータが未取得'}
    if not all(summary.get('schedule_complete', {}).values()) or not all(data.is_verified_final(g) for g in games):
        return {'error': '全試合の公式記録確定待ち'}
    try:
        rows, uncarded = pool(summary, cards)
    except ValueError as exc:
        return {'error': str(exc)}
    star1 = best_hand(rows, lambda r: 1 if r['star1'] else 0)
    top = best_hand(rows, lambda r: r['max_rare'])
    if not star1 or not top:
        return {'error': '手札を組める選手がそろっていません'}
    return {'star1': star1, 'best': top, 'uncarded': uncarded,
            'cards_retrieved_at': cards['retrieved_at'], 'cards_source': cards['source']}


def html(result):
    if not result:
        return ''
    body = ('<section class="game-eff fantasy-best" id="fantasy-best"><p class="phase-label result-label">試合結果 ／ FANTASY ARENA</p>'
            '<h2>最高の手札（この日の結果から）</h2>'
            '<p class="candidate-label">この日の公式EFFで、あとから見て一番点が出た5人。カードの点だけ（ボーナス別）</p>')
    if result.get('error'):
        return body + '<p class="game-eff-pending">' + articles.esc(result['error']) + '。確定後に掲載します。</p></section>'
    for key, label in (('star1', '☆1だけ（だれでも使える）'), ('best', '全カードから（いちばん高いレア）')):
        hand = result[key]
        body += '<h3>' + label + '：' + str(hand['total']) + '点</h3>'
        body += ('<div class="tablewrap" tabindex="0" aria-label="' + label + '"><table><thead><tr><th scope="col">枠</th>'
                 '<th scope="col">選手・所属</th><th scope="col">EFF</th><th scope="col">カード</th><th scope="col">点</th></tr></thead><tbody>')
        for r in hand['lineup']:
            body += ('<tr><td>' + r['slot'] + '</td><td><strong>' + articles.esc(r['name']) + '</strong><small>'
                     + articles.esc(r['team'] + '・' + official.LEAGUES.get(r['league'], ('', '', '', r['league']))[3]) + '</small></td>'
                     '<td>' + str(r['eff']) + '</td><td>' + STAR[r['rare']] + '</td><td>' + str(r['points']) + '</td></tr>')
        body += '</tbody></table></div>'
    return body + '</section>'


def notes(result):
    if not result or result.get('error'):
        return ''
    text = ('<p>最高の手札は、この日の全試合（B.PREMIER・B.ONE・B.NEXT）に出場した選手から、PG・SG・SF・PF・Cの枠に1人ずつ、'
            'カードの点の合計がいちばん高くなる5人を選んでいます。カードの点＝公式EFF×（1＋レア度＋ポジション一致100%）の切り捨て'
            '（★3 +30%・★4 +70%・★5 +100%、最低1点）。デッキ・勝利予想・応援バッジ・特効のボーナスは含みません。'
            'カードの種類・ポジションは B.LEAGUE CARD 公式データ（' + articles.esc(result['cards_retrieved_at'][:10]) + ' 取得）です。</p>')
    if result.get('uncarded'):
        text += '<p>今季のカードがまだ無い出場選手は対象外：' + articles.esc('、'.join(result['uncarded'])) + '</p>'
    return text
