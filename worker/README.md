# usmarket-dispatch

平日の決まった時刻に、2つのリポジトリの GitHub Actions `daily` を起動する Cloudflare Worker です。

| リポジトリ | 起動時刻（JST） | 経緯 |
|---|---|---|
| `shiroforge/summary-jpn-stock-market`（大引けノート） | 15:50 / 16:10 / 16:30 / 17:00（最終回） | 日本版の D-28 |
| `shiroforge/summary-usa-stock-market`（NY引けノート） | 07:00 / 07:30 / 08:00 / 08:30（最終回） | D-29 |

時刻は `src/index.js` の `SLOTS` と `wrangler.toml` の cron で決まり、両者の一致は `tests/test_schedule.py` で確認します。

- 祝日の判定と「生成済みならスキップ」は `daily` 側で行うので、Worker は時刻どおりに起動するだけです。
- 起動に失敗しても、`daily.yml` に残した GitHub の cron が遅れて動きます。

## 導入手順

### 1. GitHub トークンを発行する
GitHub の Settings → Developer settings → Fine-grained personal access tokens で発行します。

- Repository access: `shiroforge/summary-usa-stock-market` と `shiroforge/summary-jpn-stock-market` の2つだけ
- Permissions: **Actions: Read and write**（他は付けない）
- 有効期限: 最長に設定し、期限切れの前に更新する

### 2. Worker を公開する
Cloudflare の無料アカウントが必要です。トークンはプロンプトに貼り付け、ファイルやコミットには残さないでください。

```bash
cd worker
npx wrangler login                    # ブラウザが開くので、Cloudflare にログインして許可する
npx wrangler deploy                   # Worker を公開する（初回は workers.dev のサブドメイン名を聞かれることがある）
npx wrangler secret put GITHUB_TOKEN  # 1. で発行したトークンを貼り付ける（画面には表示されない）
```

設定した時刻が反映されるまで、最大15分ほどかかります。`secret put` を先に実行すると、Worker の新規作成を確認されます。

### 3. 動作を確認する
翌朝、Actions の `daily` の一覧で、イベントが `workflow_dispatch` の実行が 07:00 JST ごろに始まっていることを確認します。Worker の実行結果は Cloudflare のダッシュボードで確認できます。

## テスト

```bash
cd worker && npm test
```

## 止めるとき

```bash
cd worker && npx wrangler delete
```

止めても、各リポジトリの GitHub の cron による配信（遅れあり）は続きます。

## リポジトリを追加・変更したとき
- 既存のトークンの設定画面（Fine-grained tokens → 対象のトークン → Edit）で、Repository access に追加します。作り直しは不要です。
- 起動時刻を変えたら `npx wrangler deploy` で反映します。
