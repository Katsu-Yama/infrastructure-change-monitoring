# Infrastructure Change Monitoring

## 三河港 InSAR MVP（開発中）

実データを使った収集・解析・Web画面を追加しました。従来のヒアリングモックは、このREADMEの後半と既存 `index.html` にあります。

| 機能 | 実装 | 検証状態 |
|---|---|---|
| 約9.62km²の国土地理院InSAR履歴取得 | `scripts/collect.py` | 実データで動作確認 |
| 変位候補の抽出・品質判定・CSV | `scripts/analyze.py`, `scripts/run.py` | 初回5候補。ただし2025年までの履歴 |
| 地図・時系列・欠測・観測日の表示 | `web/` | ブラウザ・モバイル確認済み |
| 最新Sentinel-1の検索とSBASペア作成 | `scripts/sentinel.py plan` | 実カタログで160ペア確認 |
| 新規干渉処理・時系列化 | `scripts/process_sentinel.py` | HyP3 Basic＋MintPy。認証後の実データ検証が必要 |
| AOI干渉画像の非公開保存 | `scripts/pair_store.py`, `scripts/clip_pair.py` | 切出し数値テスト済み。Supabase接続後の検証が必要 |
| Supabase保存・匿名読取り | `docs/schema.sql`, `scripts/publish.py` | 専用無料プロジェクト作成・実履歴保存・全JSON一致・匿名権限検証済み |
| 月次Actions・Cloudflare公開 | `.github/workflows/` | Secrets設定・初回完走の検証待ち |

公開済みGSI成果の再集計と、新規Sentinel-1の月次処理は別の段階です。現在の履歴画面は個別施設の現況監視が完了したことを示しません。データ解像度90mで、橋梁等の安全判定はできません。

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

ブラウザで `http://localhost:8080` を開きます。`web/baseline.json` は生成された実データです。DB未設定時は履歴として表示し、DB接続障害時のフォールバックも明示します。

### 最新の衛星観測を調べる

```sh
python -m pip install -r requirements-insar.txt
python -m scripts.sentinel plan
```

`output/sentinel-plan.json` に実観測と処理ペアが出力されます。planは認証不要・読み取りのみ。実際の処理は `python -m scripts.run --source sentinel` で行い、EarthdataとSupabaseの認証が必要です。HyP3 Basicだけを利用し、1回400件まで。干渉画像のAOI切出し・非公開保存・共通参照点と連結成分の検査・MintPyによる時系列化までコードを実装していますが、認証後の一気通貫の実データ検証は未完了です。参照点を自動選択した場合、その物理的な安定性は未検証と表示します。

### 無料サービスへの接続

Supabaseに `docs/schema.sql` と `docs/interferogram-schema.sql` を適用し、GitHub Actionsのvariables/secretsを登録します。

専用プロジェクト [mikawa-insar](https://supabase.com/dashboard/project/sxbvyjgzrzynkvounfxy) は東京リージョンで作成済みです。テーブルと非公開バケットも設定済みで、`SUPABASE_URL` と `SUPABASE_PUBLISHABLE_KEY` はGitHub ActionsのVariablesへ登録・読戻し済みです。残るSecretsの値は、コードやチャットへ貼らずGitHubの設定画面へ登録してください。

| 種類 | 名前 |
|---|---|
| Variable | `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` |
| Variable（任意） | `INSAR_SOURCE`：既定 `sentinel`。履歴評価のみの試運転は `gsi` |
| Secret | `SUPABASE_SECRET_KEY` |
| Secret | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` |
| Secret（新規InSAR処理用） | `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` |

Cloudflare PagesのDirect Uploadプロジェクト名は `mikawa-insar`。公開フォルダは `dist`。`Monthly InSAR monitoring` は毎月2日05:17 JSTに動きます。初回は手動実行してください。秘密キーはGitHubのSecretsへ登録し、コードやチャットに貼らないでください。Web閲覧には原則として保存確認済みの静的スナップショットを使い、Supabaseの転送枠を節約します。

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
