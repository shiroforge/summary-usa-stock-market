# BACKLOG

状態: `todo` → `doing` → `review`（ユーザーの承認待ち）→ `done`。ループでは **上から順に** `todo` を1件ずつ片付ける。
🔒 = 承認ゲート（`review` で止め、ユーザーに提示する）。💰 = 費用が発生する（事前承認が必須）。

## Phase 0–1: 日本版からの移植（2026-09-29）

| ID | 状態 | タスク | 受け入れ条件 |
|---|---|---|---|
| U0-1 | done | リポジトリの初期化（uv, ruff, mypy, pytest）と日本版のコードの移植 | `ruff` / `mypy src` / `pytest` が通る |
| U0-2 | done | 米国のデータ源の技術検証（SPY 保有銘柄・Wikipedia・財務省・Nasdaq IPO・EDGAR・RSS・yfinance） | DECISIONS D-03〜D-25 に記録 |
| U0-3 | done | `DailySummary` v1（米国版） | ダミーJSONが往復で一致する |
| U0-4 | done | NYSE の営業日・短縮取引・夏時間 | 祝日・短縮取引・夏時間/冬時間のテスト |
| U0-5 | done | S&P500 マスタ、GICS セクター（推計＋ETF）、52週高安・移動平均線 | 手計算した値と一致する |
| U0-6 | done | テーマ（32＋IPO）、ニュースの単語単位のタグ付け | 全ティッカーを yfinance で確認 |
| U0-7 | done | 8-K（EDGAR）と時間外取引の反応 | fixture とモックでテスト |
| U0-8 | done | 画面（日次・アーカイブ・トレンド）と Discord の文面 | スクリーンショットで崩れがない |
| U0-9 | done | 実データで 2026-09-28 を生成 | 警告なしで生成できる |
| U0-10 | review 🔒 | **G1**: 仕様とデザインの承認（上昇色＝緑、名前「NY引けノート」、テーマの選定） | |

## Phase 2: 公開と自動化

| ID | 状態 | タスク | 受け入れ条件 |
|---|---|---|---|
| U2-1 | todo 🔒 | GitHub リポジトリの作成と push（公開範囲をユーザーが決める） | |
| U2-2 | todo 🔒 | Secrets の設定（`DISCORD_WEBHOOK_URL`、`SEC_USER_AGENT`）と Pages の有効化 | 手動実行（workflow_dispatch）で成功する |
| U2-3 | todo | GitHub Actions 上での yfinance・EDGAR・Nasdaq・財務省の到達性の確認 | 結果を DECISIONS に記録 |
| U2-4 | todo 🔒 | **G3**: 通知の文面と、公開・cron の有効化の承認 | |

## Phase 3: 拡張（承認を得た順に進める）

| ID | 状態 | タスク |
|---|---|---|
| U3-1 | todo | 決算カレンダー（翌営業日の主な決算発表予定） |
| U3-2 | todo | 経済指標カレンダー（CPI・雇用統計・FOMC など）と結果 |
| U3-3 | todo | 8-K の添付プレスリリース（EX-99.1）の見出しを使った決算の中身の表示 |
| U3-4 | todo 🔒💰 | LLM（Claude API）: ニュース要約・一言コメント |
| U3-5 | todo | 日本版とのクロスリンク（同じ日付の大引けノートへのリンク） |
