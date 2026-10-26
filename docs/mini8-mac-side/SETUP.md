# サムネ：記事ができたら Mac mini でその場で作る — 設置と操作の手順（MINI-8）

本人 10/27「推奨案（GitHubのWebhook→Tailscale Funnel→Mac miniの受け口→その場で生成）で進めて。私の操作が要るところは手順をちょうだい」。
ChatGPT の検品に合格し、本人が実行する時に行う。それまでは何も開けない・登録しない・常駐させない。

全体の流れ：記事作成（GitHub Actions）→ `data/thumbs/requests.json` に依頼を1件 → GitHub Webhook → Funnel → 受け口（127.0.0.1:8787）→ 作業役 → `codex exec --ephemeral` で画像 → `ready` → `thumb_deliver.py` → サイトが取り込み。

---

## A. Claude（Mac mini「Macbook ⇄ mini_連携用」）がやる設置 — PR #32 の統合後

1. 置き場所と、送信専用の作業用コピー（既存の `~/Claude/work/bleague-matome` とは分ける）
   ```bash
   mkdir -p "$HOME/Library/Application Support/basuke-thumb-hook/bin"
   git clone https://github.com/genjoK0216KK/bleague-matome "$HOME/Claude/work/bleague-thumb"
   cp "$HOME/Claude/work/bleague-thumb/mac/thumb-hook/hook_receiver.py" "$HOME/Claude/work/bleague-thumb/mac/thumb-hook/thumb_worker.py" "$HOME/Library/Application Support/basuke-thumb-hook/bin/"
   ```
2. 生成側のパッチ（先に控えを取る）。`docs/mini8-mac-side/01-OPERATIONS-creation-requests.patch` と `02-thumbnail_queue-requests.patch` を、
   `/Users/genjo/Documents/Codex/2026-10-25/claude-2026-10-25/outputs/basketball-thumbnail-automation/` で `patch -p1` する。当てた後に `python3 -m unittest test_thumbnail_queue`（18件）。
3. codex の場所を確かめ（ChatGPT アプリ同梱）、常駐の設定ファイルの `__CODEX__` をその絶対パスに置き換えて `~/Library/LaunchAgents/com.genjo.basuke-thumb-hook.plist` に置く。**読み込みはしない**（本人の操作4）。
4. `codex exec --ephemeral --skip-git-repo-check -s workspace-write -C <一時フォルダ> "1672x941の黒い画像を1枚作って out.png に保存して"` で画像ができることを確かめ、一時フォルダは消す。

## B. 木村さんの操作（Mac mini のターミナルで、上から順に。合計15分ほど）

### 1. 合言葉を作ってキーチェーンに入れる（画面にも、ほかのプロセスの引数にも出ない）
合言葉はシェル内蔵の printf から `security -i` の標準入力へ渡す（どのコマンドの引数にも載らない）。
```bash
S=$(openssl rand -hex 32); printf 'add-generic-password -U -a basuke-thumb -s basuke-thumb-webhook -T /usr/bin/security -w %s\n' "$S" | /usr/bin/security -i; unset S; /usr/bin/security find-generic-password -s basuke-thumb-webhook >/dev/null && echo "保存しました"
```

### 2. 受け口を起動する
```bash
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.genjo.basuke-thumb-hook.plist" && sleep 2 && curl -s -o /dev/null -w "受け口の応答：%{http_code}（401なら正常＝署名の無い通知を断っている）\n" -X POST -d '{}' http://127.0.0.1:8787/hooks/github
```

### 3. Tailscale の HTTPS と Funnel を有効にし、受け口のURLだけを公開する
1. HTTPS を有効にする：<https://login.tailscale.com/admin/dns> を開き、「HTTPS Certificates」の **Enable HTTPS** を押す。
2. 受け口だけを公開する（下を貼る）。初回に「Funnel を有効にするURL」が表示されたら、そのURLを開いて許可し、もう一度同じ行を貼る。
   ```bash
   /Applications/Tailscale.app/Contents/MacOS/Tailscale funnel --bg --set-path /hooks/github http://127.0.0.1:8787
   ```
3. 公開されたURLを確かめる（`https://aimac-mini.〜.ts.net/hooks/github` のように出る）。
   ```bash
   /Applications/Tailscale.app/Contents/MacOS/Tailscale funnel status
   ```

### 4. GitHub に通知先を登録する（合言葉は画面に出ない）
```bash
URL="https://$(/Applications/Tailscale.app/Contents/MacOS/Tailscale status --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')/hooks/github"; gh api repos/genjoK0216KK/bleague-matome/hooks --method POST --input - >/dev/null <<EOF && echo "登録しました：$URL"
{"name":"web","active":true,"events":["push"],"config":{"url":"$URL","content_type":"json","insecure_ssl":"0","secret":"$(security find-generic-password -s basuke-thumb-webhook -w)"}}
EOF
```
登録すると GitHub がすぐ確認の通知（ping）を送る。届いたかを見る：
```bash
tail -3 "$HOME/Library/Application Support/basuke-thumb-hook/receiver.log"
```
「GitHub から ping を受信」が出れば成功。うまくいかない時の画面での登録：<https://github.com/genjoK0216KK/bleague-matome/settings/hooks/new>（Payload URL＝上のURL、Content type＝application/json、Secret＝`security find-generic-password -s basuke-thumb-webhook -w | tr -d '\n' | pbcopy` で写して貼り、貼った後に `pbcopy < /dev/null`、イベント＝Just the push event）。

## C. 有効化と確認（Claude が行う。本人のOKの後）
1. 同じコミットで `python scripts/thumb_requests.py --init`（既存記事を基準に登録）と `data/thumbs/config.json` の `enabled=true` を main へ入れる。依頼台帳ができる push なので、受け口→作業役が動き、「新規0件」で終わることを `worker.log` で確かめる。
2. 次に記事が作られた時、数分以内に `worker.log` に「完成」、サイトの記事にサムネと OGP が入ることを確かめる。結果を MINI-8 に記録する。

## D. 止め方（止めたいものごとに。確かめ方つき）

| 止めたいもの | 止め方 | 止まったことの確かめ方 |
| --- | --- | --- |
| 動いている生成と送信 | `touch "$HOME/Library/Application Support/basuke-thumb-hook/STOP"`（次の作業の前・送信の前で止まる）。今すぐ止める時は続けて `pkill -f thumb_worker.py; pkill -f "codex exec --ephemeral"` | `pgrep -fl thumb_worker.py` が何も出さない。`tail -3 "$HOME/Library/Application Support/basuke-thumb-hook/worker.log"` に「止めた：停止の印」 |
| 新しい通知で作業役が起きること | 上の STOP で十分（受け口は通知を受けても起こさない）。受け口ごと止める時は `launchctl bootout gui/$(id -u)/com.genjo.basuke-thumb-hook` | STOP の時：`receiver.log` に「停止の印（STOP）があるため」。bootout の時：`curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8787/hooks/github` が 000 |
| 外からの通知の到達 | このURLだけ外す：`/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel --https=443 --set-path=/hooks/github off`。GitHub 側も止める時は <https://github.com/genjoK0216KK/bleague-matome/settings/hooks> で該当の Webhook の Active を外す（または Delete） | `/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel status` に /hooks/github が出ない。GitHub の Webhook 画面の Recent Deliveries が失敗になる |
| サイトへの反映 | `data/thumbs/config.json` を `enabled=false` にして main へ（Claude が行う）。作業役もこれを見て生成・送信をしない | 記事・一覧に新しい自動サムネが入らない。`worker.log` に「サイト側が無効」 |

再開：STOP を消す（`rm "$HOME/Library/Application Support/basuke-thumb-hook/STOP"`）／`launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.genjo.basuke-thumb-hook.plist"`／Funnel を手順B-3で再設定／enabled=true。止めていた間の依頼は台帳に残っているので、再開後の最初の通知（または受け口の起動時）にまとめて処理される。

## 費用・守り
- 費用は0円（Tailscale 個人無料、GitHub Webhook 無料、画像は ChatGPT 定額の範囲。1枚あたり約2万トークン）。
- 外に出るのは Funnel の1つのURLだけ。受け口は GitHub の署名を確かめ、中身は「見に行く合図」としてだけ使う。合言葉はキーチェーンと GitHub の Webhook 設定の2か所だけ。
- 定期巡回は作らない（受け口の常駐は、通知を待つだけで自分からは動かない）。取りこぼしの回収は、起動・ログイン時の1回と、届いた通知を機会にした回収（台帳を変えない main への push でも10分に1回まで）で行う。push の変更一覧が無い・20件以上で省略されている時は、変更を確かめずに作業役を起こす。
- 作業役の上限：1周で最大5件、1時間に最大20件。残りや失敗の再挑戦は、1分あけて同じ作業役が続ける。同じ作業が2回続けて失敗したら止めて、status.json に「本人判断待ち」を残す。
- 受け口の守り：署名の形式（ASCII の sha256=16進64桁）と一致を確かめてから数える（30回/分。超えても合図は残す）。読み取り10秒・同時8接続・5MBまで。同じ通知ID（X-GitHub-Delivery）は1回だけ数える。
- 受け口が動くのは genjo でログインしている間（既存の health-watch と同じ）。停電後の自動起動のあと、ログインまでの間の依頼は、ログイン後の回収で処理される。
