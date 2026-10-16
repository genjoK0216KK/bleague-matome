"""Roll expired next-fixture selections forward without waiting for the full news job."""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
try:
    from . import next_preview, official_data as official
except ImportError:
    import next_preview, official_data as official


def refresh(root, year, now, client_factory=None):
    root = Path(root)
    prior = next_preview.load(root, now)
    if prior and not prior.get('errors') and not prior.get('player_errors'):
        return {'changed': False, 'reason': 'current', 'requests': 0}
    attempt = root/'data/match_articles/next-preview-attempt.json'
    if attempt.exists():
        saved = json.loads(attempt.read_text())
        if saved.get('errors') and timedelta(0) <= now-datetime.fromisoformat(saved['at']) < timedelta(minutes=30):
            return {'changed': False, 'reason': 'retry_cooldown', 'requests': 0}
    client = (client_factory or (lambda: official.Client(max_requests=160,time_budget=480)))()
    started = time.monotonic()
    state = next_preview.collect(client,root,year,now)
    finished = now + timedelta(seconds=time.monotonic()-started)
    errors = state.get('errors',[]) + state.get('player_errors',[])
    attempt.parent.mkdir(parents=True,exist_ok=True)
    attempt.write_text(json.dumps({'at':now.isoformat(),'errors':errors},ensure_ascii=False))
    if errors:
        # Keep the old (visibly expired) selection; never replace verified players with guesses.
        return {'changed':False,'reason':'unavailable','errors':errors,'requests':client.request_count}
    if state.get('games') and finished >= next_preview.valid_until(state):
        return {'changed':False,'reason':'expired_during_collection','requests':client.request_count}
    next_preview.write(root,state,now)
    return {'changed':True,'date':state.get('date'),'requests':client.request_count}
