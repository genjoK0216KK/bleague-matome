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

### 1. 合言葉を作ってキーチェーンに入れる（画面には出ない）
```bash
security add-generic-password -U -a basuke-thumb -s basuke-thumb-webhook -T /usr/bin/security -w "$(openssl rand -hex 32)" && echo "保存しました"
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

## D. 止め方（いつでも、どれか1つで止まる）
- サイト側で止める：`data/thumbs/config.json` を `enabled=false`。
- 受け口を止める：`launchctl bootout gui/$(id -u)/com.genjo.basuke-thumb-hook`
- 公開を閉じる：`/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel reset`（このMac miniで公開しているのは受け口だけ）
- 通知を消す：<https://github.com/genjoK0216KK/bleague-matome/settings/hooks> で該当の Webhook を Delete。

## 費用・守り
- 費用は0円（Tailscale 個人無料、GitHub Webhook 無料、画像は ChatGPT 定額の範囲。1枚あたり約2万トークン）。
- 外に出るのは Funnel の1つのURLだけ。受け口は GitHub の署名を確かめ、中身は「見に行く合図」としてだけ使う。合言葉はキーチェーンと GitHub の Webhook 設定の2か所だけ。
- 定期巡回は作らない（受け口の常駐は、通知を待つだけで自分からは動かない。起動・復帰時に1回だけ取りこぼしを回収）。
- 受け口が動くのは genjo でログインしている間（既存の health-watch と同じ）。停電後の自動起動のあと、ログインまでの間の依頼は、ログイン後の回収で処理される。
