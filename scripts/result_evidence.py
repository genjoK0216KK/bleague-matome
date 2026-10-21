"""試合結果の「原典照合」用の記録と判定（設計・未接続）。

公式サイトを直接取得できない間に、公式の検索インデックスやクラブ公式の報告で結果の公開を
見つけても、それは「公開情報が存在する証拠・参考」にとどめる。本番の確定スコア・BOX SCORE へは
自動で入れない。確定は従来どおり、公式の試合ページを直接取得し GameEndedFlg かつ RecordFixedFlg、
出典あり、得点が0以上の整数の場合だけ（preview_data.is_verified_final）。

このモジュールは記録を作って照合結果を返すだけで、保存済みの試合データを書き換えない。
"""
from datetime import datetime

try:
    from . import preview_data as data
except ImportError:
    import preview_data as data

ROUTES = {
    'official_direct': '公式サイトを直接取得',
    'official_search_index': '公式サイトの検索インデックス（検索結果の断片）',
    'club_official': 'クラブ公式の通常公開報告',
}
UNKNOWN = '不明'


def evidence(route, url, *, date_jst, home, away, league=None, season=None, game_id=None,
             home_score=None, away_score=None, status_text=None, retrieved_at, crawled_at=None, note=''):
    """1件の記録。取得経路・こちらの取得時刻・原典の更新（クロール）時点を別の項目にする。
    分からない値は推測せず「不明」（ID は None のまま）。"""
    if route not in ROUTES:
        raise ValueError('unknown route: ' + str(route))
    return {
        'route': route, 'route_label': ROUTES[route], 'url': url,
        'date_jst': date_jst, 'game_id': str(game_id) if game_id else None,
        'home': home, 'away': away, 'league': league or UNKNOWN, 'season': season or UNKNOWN,
        'home_score': home_score, 'away_score': away_score, 'status_text': status_text or UNKNOWN,
        'retrieved_at': retrieved_at, 'crawled_at': crawled_at or UNKNOWN, 'note': note,
    }


def _is_final_text(text):
    return str(text).strip().upper() in ('FINAL', '試合終了', '終了')


def _checks(game, ev):
    """記録が対象の試合を指しているか。違えば理由を返す（推測で寄せない）。"""
    reasons = []
    game_date = data.jst_date(game['starts_at']) if game.get('starts_at') else game.get('official_date')
    if ev['date_jst'] != game_date:
        reasons.append('日付が違う（記録 %s／試合 %s）' % (ev['date_jst'], game_date))
    if ev['game_id'] is None:
        reasons.append('試合IDが不明（対戦と日付だけでは同一試合と確定しない）')
    elif ev['game_id'] != str(game['game_id']):
        reasons.append('試合IDが違う')
    if (ev['home'], ev['away']) != (game.get('home'), game.get('away')):
        reasons.append('対戦の組み合わせが違う')
    if ev['league'] not in (UNKNOWN, game.get('competition')):
        reasons.append('リーグが違う')
    if ev['season'] not in (UNKNOWN, game.get('season')):
        reasons.append('シーズンが違う')
    return reasons


def _stale(game, ev):
    """原典の更新時点が試合開始より前、または不明なら、その記録は最新の結果の根拠にしない。"""
    if ev['crawled_at'] == UNKNOWN:
        return '原典の更新時点が不明'
    if game.get('starts_at') and datetime.fromisoformat(ev['crawled_at']) < datetime.fromisoformat(game['starts_at']):
        return '原典の更新時点が試合開始より前'
    return None


def reconcile(game, items, direct_fetch_ok):
    """照合結果を返す。game は書き換えない。

    state:
      confirmed_official : 公式の直接取得で確定（既存の確定条件）。記録は参考に添えるだけ
      official_not_fixed : 公式を直接取得できたが、公式記録はまだ確定していない（結果未公開・未確定）
      reference_only     : 直接取得できず、対象試合を指す参考記録はある（確定扱いしない）
      reference_stale    : 直接取得できず、対象試合を指す記録はあるが、原典の更新時点が不明または試合前
      mismatch           : 対象試合を指す記録どうしで状態・得点が食い違う（照合待ち。途中経過を FINAL で上書きしない）
      unverified         : 直接取得できず、対象試合を指す記録も無い
    """
    if data.is_verified_final(game):
        state = 'confirmed_official'
    elif direct_fetch_ok:
        state = 'official_not_fixed'
    else:
        state = 'unverified'
    same_game, rejected = [], []
    for ev in items:
        reasons = _checks(game, ev)
        if reasons:
            rejected.append(dict(ev, reasons=reasons))
        else:
            stale = _stale(game, ev)
            same_game.append(dict(ev, reasons=[stale] if stale else []))
    if state == 'unverified' and same_game:
        finals = {(e['home_score'], e['away_score']) for e in same_game if _is_final_text(e['status_text'])}
        partial = [e for e in same_game if not _is_final_text(e['status_text'])]
        if len(finals) > 1 or (finals and partial):
            state = 'mismatch'
        elif any(not e['reasons'] for e in same_game):
            state = 'reference_only'
        else:
            state = 'reference_stale'
    return {'game_id': str(game['game_id']), 'state': state,
            'can_publish_score': state == 'confirmed_official',
            'matched': same_game, 'rejected': rejected}
