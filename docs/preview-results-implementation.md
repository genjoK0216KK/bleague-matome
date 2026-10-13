# 次戦ランキング・3リーグ日付別記事：実装と検証

## 状態

初回機能はPR #3で公開済み。追加仕様は`codex/responsive-site-nav`で実装し、PR確認待ち（未公開）。
最新仕様・検証は [navigation-and-average-update.md](navigation-and-average-update.md) を参照。cron時刻と資格情報は変更しない。
元のClaude定期実行checkout `/Users/genjo/Claude/Scheduled/bleague-daily/clone` は変更していない。
ローカルcloneの `origin` は元checkout、追加remote `github` は公開GitHub。originにpushしないこと。

## 追加・変更ファイル

- `scripts/official_data.py`：公式HTML/JSON取得、ページング、シーズン・大会・平均/合計列検証、日程、次戦探索、登録選手、IL照合。
- `scripts/preview_data.py`：副作用のない順位計算と日次結果判定。
- `scripts/match_articles.py`：明示した別出力先へプレビュー・統合結果・特筆記事・サムネを生成するCLI。
- `scripts/stats.py`：既存EFF説明を現行公式定義へ修正。既存BP集計の計算・公開フローは変更していない。
- `auto.css`：新記事 `.match-article` に限って日付・出典を折り返す。
- `tests/test_preview_data.py`, `tests/test_official_data.py`, `tests/fixtures/*`：53テストと公式レスポンス抜粋。

追加本人指示によりworkflowへ新機能を接続。cron時刻は維持。buildは次戦/ILナビを追加、routine-promptは重複防止を追記。
自動実行はscripts/update_match_features.py。現在IL、当日/前日結果、翌日日程、次戦プレビューの順に実行する。
生成記事を隔離コピーに置き既存buildを実行した場合の一覧・カテゴリ・sitemap連携は検証済み。

## 初回公開時の実データ検証記録（当時は通算）

- 公式公開データを認証なしで取得できた。sandbox内DNSは失敗したが、承認された読み取り専用実行では取得成功。
- BP通算APIを終端まで取得。オーガスト PlayerID 51000312 は7試合・通算EFF243、ヴァン・タバーゲン 51000655 は5試合・130。
- B.ONE通算API：300人、B.NEXT通算API：48人の記録を取得。
- 統計指定は BP tab1/player-b1/e2、B.ONE tab2/player-b2/e7、B.NEXT tab3/player-b3/e15。game側ConventionKeyとは別。
- JSON `topics` 内には20行ごとの再掲ヘッダが混じる。thのみの行を除外し、データ列数は検証する。
- 次戦探索：2026-10-16の506464川崎–茨城、506465横浜BC–琉球、506466佐賀–北海道を確認。
- 10/13結果：507233 東京U80–71立川、ended/fixed=true。
- B.NEXTの10/13指定は10/22の507923へfallbackするが、月間カレンダーに10/13がないため試合なしと判定。10/22の結果は混入させない。
- 未開催試合には `_contexts_s3id.data` がない。対象試合のgame-top/canonical/関連クラブリンクを静的解析し、別試合のグローバルscoreboardを使わない。
- 公式用語集の現行EFFは被ファウル加点・被ブロック/ファウル減点を含む。簡略式で再計算しない。

## データ・表示方針

ランキングは次戦の両チーム内、2026-27レギュラーシーズンの公式今季平均EFF。
平均は公式のdt=avg/EFFPG列を直接使用し、通算/Gで再計算しない。対象大会外・過年度・未取得を0で補わない。
PlayerID単位で扱い、移籍のTOTALは一度だけ採用。所属別行しかなく合計を検証できない場合は未確認として除外。
複数ポジションは各表へ一度ずつ掲載。同値順位は1,1,3。公式G=0の未出場と未取得は別状態。

現在のクラブ登録一覧から出場確定を推論しない。
モデルには entry_confirmed / unannounced / expected / out / suspended / unknown を用意。
現在のliveアダプターは公式ILを正確なクラブ名・日本語名または公式プロフィール英語名で照合し、
それ以外はunknown（出場未確認）と表示する。IL公示から削除された行は欠場根拠にしない。
ILは取得時点の状態で、未来の試合時点の確定欠場として断定しない注記を表示。

統合記事は `article-games-YYYYMMDD.html` の日付固定キー。3リーグの予定・結果・平均ランキングを一つの記事内で表示。旧results URLはcanonical付き互換ページとして保持する。
未確定・取得不完全なら途中版。全試合確定後は同じ記事を更新。公式訂正は再取得した値で上書き。
取得失敗で前回の試合が消える場合は旧記事を保持しエラー報告する。
対象日の3リーグを各節で表示し、完全取得済みのリーグだけ「試合なし」と明示。
延期・中止はスコアを表示せず別状態。開始時刻不明の中止等に00:00を捏造しない。

個別記事は編集者が検証済みの特筆理由と公式URLを `--editorial-json` で渡した場合だけ作成。
点差やEFFの任意の閾値で特筆と断定しない。公式URLの取得は検証するが、理由と出典の意味的照合は編集責任。
ファイル例（例示文字列は本番に使用しない）：

```json
{"507233": {"reason": "検証済みの記録・節目などの具体的理由", "source": "https://www.bleague.jp/該当する公式発表"}}
```

## 実行方法

依存は既存と同じ `requests beautifulsoup4`。今回の一時Pythonは `/tmp/bleague-feature-venv/bin/python`。

```sh
python scripts/match_articles.py --date 2026-10-13 --season-year 2026 \
  --preview-game 506464 --output-root ../dry-run --capture-dir ../official-capture
```

`--preview-game` は複数指定可能。`--next-league BP`（またはB1/BN）は35日以内の次の試合日の全試合を公式カレンダーから探す。
`--offline` でURL・取得時刻付きの保存レスポンスを再生。オンライン実行時は毎回再取得し、キャッシュを古いまま採用しない。
output-rootは必須。コードを起動するだけでリポジトリや公開先へ書き込むことはない。
日付はJSTで指定。シーズン開始年も明示する。

```sh
python -m unittest discover -s tests -v
```

## 初回公開時の検証記録・プレビュー（過去版）

作業ルート `/Users/genjo/Documents/Codex/2026-10-13/task-3/` 内：

- `site-preview/article-preview-506464.html`：川崎–茨城、公式の通算EFFを表示。
- `site-preview/article-results-one-next-20261013.html`：東京U80–71立川 / B.NEXT試合なし。
- `site-preview/index.html`：隔離コピーで既存buildを実行した一覧。
- `dry-run/tests.log`：53件合格。
- `dry-run/live-league-check.json`：B.ONE/B.NEXT統計件数・次戦自動発見のlive記録。
- `dry-run/generation-report.json`：各公式URLと実取得時刻、生成物、エラー（なし）。
- `dry-run/layout-check.json`：390px/1280pxの両記事でdocument幅がviewport幅と一致。
- `dry-run/article-*-mobile.png`, `dry-run/article-*-desktop.png`：headless Chromeによる全ページ画像。
- `official-capture/`：再現用の公式レスポンス完全保存。公開repoには含めない。

テストは欠損、負値/ゼロ、同順位、複数position、未出場、集計モード不一致拒否、移籍TOTAL、重複、取得失敗、
日付JST境界、日程fallback、未開催と別試合スコア、延期/中止、訂正上書き、個別記事条件、
既存PREMIER描画回帰、一覧・sitemap・再実行の重複なしを含む。

## 残る制約と有効化前の確認

1. エントリー一覧・出場停止・クラブの個別見込み発表の自動解析は未実装。unknown表示で過剰な出場断定を防ぐ。
2. 延期・中止は合成fixtureで検証したが、実際の対象公式ページでのlive確認は未実施。公式構造変更時は未確定として扱う。
3. ILの表記揺れや英語別名は勝手に変換しない。完全一致できないものはunknownとなる。
4. 次戦探索は35日まで。月間日程の空・構造不明は試合なしと断定しない。試合日ページが20件以上の場合の追加ページングは未対応で、20件以上なら未確定にして過少件数の確定記事を防ぐ。
5. 手動 `--preview-game` は試合を指定する操作。自動的に「各チームの最も近い次戦」であることまで検証しない。通常は `--next-league` を使う。
6. リポジトリworkflowへ接続済み。外部Claude定期実行の保存済みプロンプトは未変更で、repoの重複防止指示との同期確認は残る。
7. 個別記事の特筆基準は編集判断のまま。自動選定の基準を決めるなら別途仕様化する。
8. ローカル検証にシステムPython3.9/LibreSSLのurllib3警告が出たが取得は成功。既存ActionsはPython3.12。

## 独立レビュー後の追加検証

`tests/test_review_regressions.py` を追加。開始時刻以降の次戦拒否、欠損スコア、中止延期の個別記事拒否、試合なし訂正・特筆撤回、片リーグ失敗後の管理履歴、記事依存ソース別取得時刻、offline表示を修正・検証した。53テスト合格、独立reviewerが最終修正を再確認。
`--as-of` はoffline時だけの履歴再現用。通常の次戦判定は現在時刻を使う。
個別記事の管理一覧 `managed_highlights` は候補一覧と分離し、不完全取得を経ても撤回可能。
運用接続・時間/API負荷・本番反映・rollbackは [preview-results-rollout.md](preview-results-rollout.md) 参照。

## 追加本人要件

injury_page.pyで現在IL・抹消履歴を別枠表示。診断情報を保存せず、選手公示/登録/抹消日、ページ公示日、取得日時を区別。失敗時は前回情報を保持し、12時間超も警告。ランキングは上位3人と3人目の同値まで。IL抹消と現在登録一覧掲載を表示するが出場は未確認。53テストと独立レビュー指摘修正済み。
