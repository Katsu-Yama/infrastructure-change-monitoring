# 三河港 InSAR MVP 実装・検証記録

## 目的と完了条件

三河港の5～10km²を対象に、舗装ヤード・臨港道路・橋梁取付部・護岸背後地の沈下・変位候補を月次で抽出する。GitHubに収集・解析・公開用コードを置き、Actionsで定期実行し、Supabaseに保存、Cloudflareで公開する。

次のすべてを実機・実サービスで検証するまで完了としない。

- [ ] 新規のSentinel-1観測からの月次InSAR処理を接続し、同一軌道・同一偏波・連結成分・水面・コヒーレンスを検査する。
- [ ] 施設台帳の登録と観測可能性を確認し、対象4種類の候補抽出を現地記録と照合する。
- [x] 収集・解析・公開コードをGitHubに保存し、CIを通す（下記検証記録）。
- [ ] 月次Actionsを起動し、実データで保存・公開まで完走する。
- [ ] Supabaseで保存結果の読戻し、匿名SELECT、匿名書込み禁止を検証する。
- [ ] Cloudflareの公開URLをブラウザで検証する。
- [ ] 課金するサービスを使わず、無料枠内の転送・保存・実行量を記録する。

## 現在の処理

2026年10月20日、コードコミット `0464adc` のGitHub Actions [実行39375233383](https://github.com/Katsu-Yama/infrastructure-change-monitoring/actions/runs/39375233383) で通常テスト・Webビルドと科学計算環境テストが成功した。科学計算環境では15件（実際のMintPyによる合成変位の復元を含む）を実行した。ローカルではブラウザの地図・履歴警告・時系列・CSV・メモ保持・モバイル表示・データ欠落時の表示も確認した。

Cloudflare用の公開ワークフローは `SUPABASE_URL is not configured` で停止した。Supabase専用プロジェクトの組織指定、GitHubへの設定値登録、CloudflareとEarthdataの認証接続、対象施設台帳の確認が残っている。公開URLや新規観測の実測結果はまだ検証できていない。

`python -m scripts.run` が国土地理院の公開数値時系列タイルを収集し、符号・単位をmmに統一し、格子点の変位傾向を再集計する。GSIのSBAS処理済み成果であり、このコードが生のSLCから干渉処理しているわけではない。

AOIは神野地区周辺の矩形 `[137.285,34.717,137.320,34.744]`、約9.6km²。水域を含む。120m間隔で観測可能性を調べる。施設境界は未確認であり、`config/assets.geojson` は空のままとする。施設位置や損傷を捏造しない。

GSI公開データは約90mで、更新は観測ごとのリアルタイム公開ではない。2026年時点の最新成果でも2025年までの観測を含む。このため、履歴スクリーニングだけでは月次の現況監視という目的は満たさない。画面・JSONの `operational_monthly_insar=false` を維持する。

## 評価手法

- RGBの符号付き24bit数値タイルを復号する。0x800000と透明画素は欠測。
- 公開サイトの処理に従って `signed_integer × -0.001 cm` をmmに変換。カラー凡例からの数値推定はしない。
- 12観測以上・730日以上の有効時系列にTheil–Sen推定を適用。
- 速度5mm/年以上、速度がペア傾きのMADの2倍以上、残差MAD12mm以下を暫定条件とする。
- 同符号の近傍候補が3点以上ある点を確認候補とする。隣接点は独立な証拠ではない。
- 隣接セルを抑制し最大10候補を出す。しきい値は未校正。
- 正は衛星へ近づく方向。単独のLOSを鉛直沈下に変換しない。
- 観測から90日超なら履歴扱い。処理月を新観測月として表示しない。
- GSI側で除かれた地震変動等はこの成果から復元できない。

## 無料枠を守る構成

- 公開GitHubリポジトリの標準Ubuntu runnerを使う。有料の大型runnerは使わない。
- 1回80MB・3000 HTTPリクエストを初期上限とし、超過時は失敗として前回の正常な公開結果を維持する。
- 生画像・全域SLCをSupabaseに置かず、AOIの数値時系列・メタデータ・解析結果をJSONで保存する。
- 1レポート8MiB未満・24月分を上限とする。上限だけでも192MiB未満、インデックス・他用途・転送分は別に管理する。
- 静的Cloudflare Pagesで配信。公開用publishable keyだけを画面へ渡す。
- GSI画像の不変URLは一回のジョブ内でキャッシュ、メタデータは毎回再取得。更新日だけでなく入力のSHA256を記録。
- Actionsの保存アーティファクトに生画像を大量保存しない。
- HyP3の全域製品は1ペアずつ一時取得し、AOI保存後に一時ディレクトリを破棄する。時系列解析も実行ごとの隔離領域で行い、過去ペアや前回のMintPy出力を混在させない。
- 無料Supabaseは休止される可能性がある。可用性保証はせず、休止時は復旧が必要。無意味なkeep-aliveは設けない。
- 公開リポジトリのスケジュールは60日無活動で停止する場合がある。運用時にActionsの有効状態を確認する。

## 接続手順

1. 専用Supabaseプロジェクトを無料組織で作成し、`docs/schema.sql` と `docs/interferogram-schema.sql` を適用する。
2. GitHubのActions variablesに `SUPABASE_URL` と `SUPABASE_PUBLISHABLE_KEY` を登録する。
3. Actions secretsに `SUPABASE_SECRET_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` を登録する。チャットやリポジトリに秘密値を貼らない。
4. Cloudflare PagesのDirect Uploadプロジェクト `mikawa-insar` を作成する。APIトークンの権限は対象アカウントのPages Editに限定する。
5. Earthdataの認証情報をActions Secretsへ登録する。`Monthly InSAR monitoring` を手動実行し、新規InSAR・Supabase読戻し・Cloudflareデプロイを確認する。履歴だけの先行試運転には `INSAR_SOURCE=gsi` を使う。
6. 公開画面の処理月・最終観測日・欠測・履歴表示を確認する。

Actionsのcronは毎月2日05:17 JST。処理に失敗した場合はエラーとして終了し、前回データをゼロ件で上書きしない。

## 月次の新規観測を処理する経路

40m解像度・20m画素間隔のSentinel-1 Burst InSARをASF HyP3 Basicで処理する経路を採用候補とする。Earthdata認証が必要。無料Basicは月8,000クレジット。`5x1` の単一バーストペアは1クレジットで、初期履歴を含めた処理を小分けにできる。追加クレジット購入・HyP3+には自動移行しない。

`scripts/process_sentinel.py` に取得・AOI切出し・非公開保存・品質マスク・MintPy時系列化のコードを実装済み。2026年10月20日の実カタログ検索で、北行50観測93ペア（最終2026年10月11日）・南行41観測67ペア（最終2026年10月5日）を確認した。認証が未接続のため、この160ペアの干渉処理・時系列化はまだ実行していない。以下は実サービスでの検証が必要。

- ASFでAOIを包含する同一burstのVV観測を検索する。
- 観測間隔と軌道の整合する複数ペアをつなぎ、SBASネットワークを作る。
- デフォルト参照点をそのまま採用せず、共通の参照領域を設定する。
- コヒーレンス・水面・連結成分をマスクし、AOIに切り出してから保存する。
- 位相の閉合誤差と参照領域の安定性を検査する。
- HyP3の生位相は衛星から遠ざかる符号であり、GSI表示と符号が異なる。取り込み時に統一する。
- 20mの画素間隔を20mの分解能と表記しない。個別構造物の判別可否を別途検証する。

共通参照点は明示指定がなければ、全ペアで水域外・有効連結成分・コヒーレンス0.35以上を満たす画素から選択する。この参照点が地上で不動であることを保証しない。大気遅延は未補正のため、結果は暫定評価として表示する。欠測・連結成分・時間コヒーレンスに加え、MintPyの三角閉合診断で整数周期の不整合が検出された画素を除外する。閉合診断の欠落時は公開処理を中止する。閉合がゼロであっても、大気・基準点・全ての解析誤差が否定されるわけではない。

`tests/test_scientific_runtime.py` は既知の変位を与えた合成GeoTIFFと実際のMintPy処理で、位相の符号、mm換算、時系列復元を検証する。これはソフトウェアの数値テストであり、三河港の観測精度を示す実測結果ではない。MintPy 1.6.4が整数閉合不整合ゼロの診断図で停止する問題は、`scripts/mintpy_entry.py` で診断図のみを省略して回避する。数値診断そのものは省略しない。

Webのみの再デプロイ時にも `scripts/export_snapshot.py` で最新の公開済みSupabaseレポートを取り込み、同一内容のハッシュを確認して静的配信する。DB通信失敗時はデプロイを停止し、既存の公開結果を古い同梱履歴で上書きしない。初回でDBが空の場合だけ、明示した履歴画面を使う。

## 一次情報

- [GSIデータ概要](https://sarprod.gsi.go.jp/dataOverview)
- [GSI利用規約・クレジット](https://sarprod.gsi.go.jp/termsOfService)
- [GSI時系列閲覧手順](https://sarprod.gsi.go.jp/guide)
- [GSI公開TSALoader](https://sarprod.gsi.go.jp/gsiMaps/sar/js/gsitsa_util.js)
- [HyP3 Burst InSAR仕様](https://hyp3-docs.asf.alaska.edu/guides/burst_insar_product_guide/)
- [HyP3 Basicクレジット](https://hyp3-docs.asf.alaska.edu/using/credits/)
- [Cloudflare Pages無料枠](https://developers.cloudflare.com/pages/platform/limits/)
- [Cloudflare Actions連携](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/)
- [GitHub Actions課金](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [Supabase DBサイズ](https://supabase.com/docs/guides/platform/database-size)
