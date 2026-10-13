# Bライムの正規素材反映

承認済みLibrary ZIP `libfile_70452bbf1dd081919a1554a34b8ff8b6` のアウトラインSVGとPNG/ICOをそのまま使用。ライム #CCF43B、チャコール #151A18。新規画像生成・文字再入力・比較画像の切り抜きなし。

共通ヘッダーは暗背景用SVGを縦横比維持で表示。favicon SVG/ICO/16/32、Apple Touch 180、manifestの192/512を全公開HTMLへ設定。共通head処理は再実行可能で、build/stats経由の今後の生成にも適用する。Google確認用HTMLは変更しない。

143ページについてheaderを除いたbody DOMが変更前と一致。63テスト合格。320/390/899/900/1280pxでナビ幅・開閉・キーボード・JS失敗時を確認。ライム面の文字はチャコールにして視認性を確保。

生成コマンドやスケジュールの変更は不要。routine-promptは最新mainの共有ヘッダー・ロゴ・favicon保護を既に指示しているため、追加のClaude UI同期は不要。
