# usmarket-dispatch

平日の 07:00 / 07:30 / 08:00 / 08:30 JST に、GitHub Actions の `daily` を起動する Cloudflare Worker です。経緯は `docs/DECISIONS.md` の D-29 を参照してください。

- 祝日の判定と「生成済みならスキップ」は `daily` 側で行うので、Worker は時刻どおりに起動するだけです。
- 起動に失敗しても、`daily.yml` に残した GitHub の cron が遅れて動きます。

## 導入手順

### 1. GitHub トークンを発行する
GitHub の Settings → Developer settings → Fine-grained personal access tokens で発行します。

- Repository access: `shiroforge/summary-usa-stock-market` のみ
- Permissions: **Actions: Read and write**（他は付けない）
- 有効期限: 最長に設定し、期限切れの前に更新する

### 2. Worker を公開する
Cloudflare の無料アカウントが必要です。トークンはプロンプトに貼り付け、ファイルやコミットには残さないでください。

```bash
cd worker
npx wrangler login
npx wrangler secret put GITHUB_TOKEN
npx wrangler deploy
```

設定した時刻が反映されるまで、最大15分ほどかかります。

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

止めても、GitHub の cron による配信（遅れあり）は続きます。
