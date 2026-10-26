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
   cp "$HOME/Claude/work/bleague-thumb/mac/thumb-hook/hook_receiver.py" "$HOME/Claude/work/bleague-thumb/mac/thumb-hook/thumb_worker.py" "$HOME/Claude/work/bleague-thumb/mac/thumb-hook/thumb_stop.py" "$HOME/Library/Application Support/basuke-thumb-hook/bin/"
   ```
2. 生成側のパッチ（先に控えを取る）。`docs/mini8-mac-side/01-OPERATIONS-creation-requests.patch` と `02-thumbnail_queue-requests.patch` を、
   `/Users/genjo/Documents/Codex/2026-10-25/claude-2026-10-25/outputs/basketball-thumbnail-automation/` で `patch -p1` する。当てた後に `python3 -m unittest test_thumbnail_queue`（19件）。
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

以下、`H="$HOME/Library/Application Support/basuke-thumb-hook"` と `T=/Applications/Tailscale.app/Contents/MacOS/Tailscale` を最初に貼ってから使う。

### D-1. 生成と送信を止める（ふつうはこれだけ）
```bash
touch "$H/STOP"
```
- 動いている作業役は、次の作業の前・送信の前で止まる。受け口は通知を受けても作業役を起こさず、「あとで回収が要る」印（dirty）だけ残す。その通知は処理済みとして記録しない。
- 確かめ方：`tail -3 "$H/worker.log"` に「止めた：停止の印」、通知が来ていれば `tail -3 "$H/receiver.log"` に「停止の印（STOP）があるため」。

### D-2. 今すぐ止める（生成の途中でも）
```bash
/usr/bin/python3 "$H/bin/thumb_stop.py"
```
- STOP を置いたうえで、`worker.pid` の記録（PID・PGID・開始時刻・コマンド・置き場所）が今動いているプロセスと**全部一致した時だけ**、そのプロセスグループ（作業役・Codex・送信・git）に TERM を送る。5秒待って残っていれば、もう一度同じ確かめ方をしてから KILL する。
- 古い `worker.pid` の番号が別のプロセスに使い回されていても、開始時刻やコマンドが違うので何もしない（「何も止めません」と出る）。ほかの作業の codex は巻き込まない。
- 確かめ方：「止まりました」と出る。`tail -3 "$H/worker.log"` も見る。
- 途中で止めた作業は完成として保存されず、再開後にもう一度作られる。生成の回数と周の記録はその都度 status.json に保存しているので、止めて再開しても1時間の上限は超えない。

### D-3. 受け口ごと止める
```bash
launchctl bootout gui/$(id -u)/com.genjo.basuke-thumb-hook
```
- 確かめ方：`curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8787/hooks/github` が `000`。

### D-4. 外からの通知の到達を止める（Funnel）
1. まず今の公開設定を見る：
   ```bash
   "$T" serve status
   ```
2. 外し方（上で見た内容に合わせて、どちらか）
   - 公開しているのが /hooks/github だけなら、Funnel の設定をまとめて消す：`"$T" serve reset`
   - ほかの公開もあって /hooks/github だけ外したい時：`"$T" funnel --https=443 --set-path=/hooks/github off`（この版で受け付けない時は、`"$T" funnel --help` の「off」の書き方に従う。迷ったら D-3 で受け口を止めれば、Funnel が残っていても中には届かない）
3. 確かめ方：`"$T" serve status` と `"$T" funnel status` に /hooks/github が出ない。

### D-5. GitHub からの通知を止める（Webhook）
1. 画面：<https://github.com/genjoK0216KK/bleague-matome/settings/hooks> で該当の Webhook を開き、Active を外して保存（または Delete）。
2. 確かめ方（ターミナル）：
   ```bash
   gh api repos/genjoK0216KK/bleague-matome/hooks --jq '.[]|{id,active,url:.config.url}'
   ```
   該当の URL の `active` が `false`（Delete した時は一覧に出ない）。

### D-6. サイトへの反映を止める
`data/thumbs/config.json` を `enabled=false` にして main へ（Claude が行う）。作業役もこれを見て生成・送信をしない。確かめ方：`worker.log` に「サイト側が無効」、記事・一覧に新しい自動サムネが入らない。

### 再開
- 合言葉（キーチェーン）を変えた時：受け口は起動時に1回だけ読むので、`launchctl kickstart -k gui/$(id -u)/com.genjo.basuke-thumb-hook` で起動し直す。
- STOP だけの時：`rm "$H/STOP"` のあと、受け口を起動し直して止めていた間の分を回収する：`launchctl kickstart -k gui/$(id -u)/com.genjo.basuke-thumb-hook`（起動時に1回作業役を起こす）。
- D-3 の後：`launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.genjo.basuke-thumb-hook.plist"`
- D-4 の後：手順 B-3 の2をもう一度。D-5 の後：Active に戻す（Delete した時は手順 B-4）。D-6 の後：enabled=true（Claude）。
- 止めていた間の依頼は台帳に残っているので、再開後の起動時（または次の通知）にまとめて処理される。

### 同じ通知の扱い（二重処理しない理由）
- **再配達のまとめ**：受け口は、動いている間の最近500件の通知ID（X-GitHub-Delivery）を覚え、同じIDは1回だけ数える。これは手間を省くためのもので、記憶はメモリだけ（受け口を再起動すると忘れる）。
- **再送されても害が無い理由**：通知は「台帳を見に行く合図」でしかなく、中身は使わない。作業役は main の台帳を読み直し、同じ作成イベント（記事パスから決まるID）は state で1回しか受け取らない。だから古い通知の再送や、ID を変えた再送があっても、新しい生成は起きない（起きるのは台帳の見直し1回だけで、それも周の上限の中）。

## 費用・守り
- 費用は0円（Tailscale 個人無料、GitHub Webhook 無料、画像は ChatGPT 定額の範囲。1枚あたり約2万トークン）。
- 外に出るのは Funnel の1つのURLだけ。受け口は GitHub の署名を確かめ、中身は「見に行く合図」としてだけ使う。合言葉はキーチェーンと GitHub の Webhook 設定の2か所だけ。
- 定期巡回は作らない（受け口の常駐は、通知を待つだけで自分からは動かない）。取りこぼしの回収は、起動・ログイン時の1回と、届いた通知を機会にした回収（台帳を変えない main への push でも10分に1回まで）で行う。push の変更一覧が無い・20件以上で省略されている時は、変更を確かめずに作業役を起こす。
- 作業役の上限：生成は1周で最大5件、1時間に最大20件。周と周は最低1分あけ、1時間に30周まで（通知が続いても詰めて回らない）。残りや失敗の再挑戦は同じ作業役が続ける。同じ作業が2回続けて失敗したら止めて、status.json に「本人判断待ち」を残す。
- 送信の失敗（時間切れ・起動できない等も含む）：1・2・5・10・15分 あけて5回まで試す。6回目も失敗したら、**生成も含めて全体を止め**、status.json に「本人判断待ち」（deliver_blocked）を残す。次の通知で1周だけ試し直す。完成画像は ready に残るので失われない。
- サイト設定（data/thumbs/config.json）が読めない・辞書でない（[] や null）時は「無効」として扱い、生成も送信もしない（印は残す）。
- 受け口の守り：署名の形式（ASCII の sha256=16進64桁）と一致を確かめてから数える（30回/分。超えても合図は残す）。同時8接続まで（スレッドを作る前に数え、超えたら即座に切る）・1接続は全体で15秒まで・5MBまで。合言葉は起動時に1回だけ（10秒の時間切れ付きで）読み、通知ごとにキーチェーンを呼ばない。同じ通知の扱いは D の最後を参照。
- 受け口が動くのは genjo でログインしている間（既存の health-watch と同じ）。停電後の自動起動のあと、ログインまでの間の依頼は、ログイン後の回収で処理される。
