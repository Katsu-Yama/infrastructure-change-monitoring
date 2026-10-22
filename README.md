# Infrastructure Change Monitoring

## 三河港 InSAR MVP（開発中）

実データを使った収集・解析・Web画面を追加しました。従来のヒアリングモックは、このREADMEの後半と既存 `index.html` にあります。

公開画面：[三河港 InSAR Monitor](https://mikawa-insar.pages.dev)。指定された新矩形へ変更し、Supabaseの旧監視データ全件を削除後、新範囲で再解析・保存・公開しました。北行49観測（2025-04-24～2026-10-11）による暫定評価です。南行は現在の単一バースト処理で新矩形全体を包含できないため採用していません。

現在の矩形は左上（緯度34.74863、経度137.30809）・右下（緯度34.69886、経度137.34545）、18.94km²です。旧範囲の南行最終日2026-10-17とは、採用する観測系列が異なります。

| 機能 | 実装 | 検証状態 |
|---|---|---|
| 18.94km²の監視矩形・格子生成 | `config/mikawa.json`, `scripts/collect.py` | 指定座標と5,244格子を検証 |
| 変位候補の抽出・品質判定・CSV | `scripts/analyze.py`, `scripts/run.py` | 最新結果は利用可能2,101地点・候補0件。安全性の判定ではない |
| 地図・時系列・欠測・観測日の表示 | `web/` | ブラウザ・モバイル確認済み |
| 最新Sentinel-1の検索とSBASペア作成 | `scripts/sentinel.py plan` | 新矩形の北行94ペアを生成・解析 |
| 新規干渉処理・時系列化 | `scripts/process_sentinel.py` | HyP3 Basic＋MintPyで実データの時系列化・品質判定を完走 |
| AOI干渉画像の非公開保存 | `scripts/pair_store.py`, `scripts/clip_pair.py` | 新矩形の94ペア・37.75MiBを保存。旧範囲の混入を拒否 |
| Supabase保存・匿名読取り | `docs/schema.sql`, `scripts/publish.py` | 専用無料プロジェクト作成・実履歴保存・全JSON一致・匿名権限検証済み |
| Cloudflare公開 | `.github/workflows/deploy.yml` | 実公開・ブラウザ・全データのSupabase一致を検証済み |
| 月次Actions | `.github/workflows/monthly.yml` | [新範囲再処理39779347604](https://github.com/Katsu-Yama/infrastructure-change-monitoring/actions/runs/39779347604)：解析・Supabase読戻し・Cloudflare公開が成功 |

現在の公開結果は40m分解能・20m画素間隔の新規Sentinel-1 Burst InSARです。共通参照点の物理的安定性、施設台帳との対応、現地精度は未検証で、大気遅延は未補正です。個別施設の損傷・安全判定には使えません。

### 手元で動かす

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m scripts.run --bundle-baseline
npm ci --ignore-scripts
npm test
npm run build
python -m http.server 8080 --directory dist
```

ブラウザで `http://localhost:8080` を開きます。`web/index.html` をファイルとして直接開いた場合は、ブラウザの制限でJavaScriptやJSONを読み込めないため、最新の公開画面へ自動的に移動します。ローカルで開発・確認する場合は上記のHTTPサーバーから `dist` を表示してください。同梱の `web/baseline.json` は範囲変更前の実データ履歴です。最新の新矩形を表示するには公開画面、または公開DB設定で `python -m scripts.export_snapshot` を実行後にビルドした画面を使います。DB未設定時の履歴表示と最新月次結果を区別します。

### 最新の衛星観測を調べる

```sh
python -m pip install -r requirements-insar.txt
python -m scripts.sentinel plan
```

`output/sentinel-plan.json` に実観測と処理ペアが出力されます。planは認証不要・読み取りのみ。実際の処理は `python -m scripts.run --source sentinel` で行い、EarthdataとSupabaseの認証が必要です。HyP3 Basicだけを利用し、1回400件まで。最新観測を含む一気通貫の実データ検証は完了しました。参照点を自動選択した場合、その物理的な安定性は未検証と表示します。品質除外後も最新日を含むネットワークの連結性と１年以上の期間を必須にします。

### 無料サービスへの接続

Supabaseに `docs/schema.sql` と `docs/interferogram-schema.sql` を適用し、GitHub Actionsのvariables/secretsを登録します。

専用プロジェクト [mikawa-insar](https://supabase.com/dashboard/project/sxbvyjgzrzynkvounfxy) は東京リージョンで作成済みです。テーブルと非公開バケット、VariablesとSecrets５項目を設定済みです。Earthdataの２項目更新後、2026年10月21日にActions上の認証・HyP3非公開照会とNASA検索の復旧を確認しました。秘密値は取得・表示していません。秘密値はコードやチャットへ貼らないでください。

| 種類 | 名前 |
|---|---|
| Variable | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` |
| Variable（任意） | `INSAR_SOURCE`：既定 `sentinel`。履歴評価のみの試運転は `gsi` |
| Secret | `SUPABASE_SECRET_KEY` |
| Secret | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` |
| Secret（新規InSAR処理用） | `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` |

Cloudflare PagesのDirect Uploadプロジェクト名は `mikawa-insar`。公開フォルダは `dist`。`npm run deploy` は対象プロジェクトが存在しない場合だけ無料の静的公開先を作成し、認証・サーバーエラー時には停止します。`Monthly InSAR monitoring` は毎月2日05:17 JSTに動き、初回手動実行で新規観測の解析・保存・公開まで確認しました。再実行時は既存ジョブと保存済みペアを再利用します。Web閲覧には保存確認済みの静的スナップショットを使い、Supabaseの転送枠を節約します。

詳しい仕様・判定条件・未完了要件は [実装・検証記録](docs/IMPLEMENTATION.md) を参照してください。

`python -m scripts.verify_supabase` で実際の公開APIの読取りと権限拒否を検証できます。テストレコードは作成しません。GitHub CIでも公開URL・公開キーの設定時にこの検証を実行します。

新規観測の軽量カタログ収集は毎日05:37 JST、重い干渉処理は月次です。カタログをSupabaseへ保存・読戻しし、新規観測の有無を記録します。無料DBの休止リスクは残り、休止時は復旧が必要です。公開済みスナップショットはDB休止中も閲覧できます。中間データは約20か月を超えた未使用ペアを削除し、350MiBの上限を守ります。

---

衛星データを使った河川・海岸・港湾・沿線の変化監視MVPについて、管理者ヒアリングを行うための操作モックです。

## 確認できること

- 豊川、浜名湖岸、天浜線のモデル区間切り替え
- 変化候補、比較時期、確信度、観測条件、推奨対応の確認
- 現地確認・経過観察・対象外の判断記録
- 通知対象、しきい値、通知速度、一次確認担当者の聞き取り
- 要件メモのコピー

## 使い方

GitHub Pagesを有効にした場合、公開されたトップページから操作できます。ローカルでは `index.html` をブラウザで開いてください。

表示される地形、検出結果、数値はすべて要件ヒアリング用のデモデータです。
