# CLAUDE.md — NY引けノート（usmarket）

米国株の引け後サマリ（指数・GICS 11セクター・テーマ・ランキング・SEC 8-K・ニュース）を静的サイトに生成し、Discord に要約とURLを送るツール。
日本版（`../summary-jpn-stock-market`、大引けノート）をベースにした米国版で、構成・設計の多くを共有している。
**開発はループエンジニアリングで行う。Claude が自律的に実装し、ユーザーは機能とデザインの承認者。**

## 必ず読むもの
- `docs/BACKLOG.md` — 次にやるタスク（上から順に）
- `docs/SPEC.md` — 機能仕様
- `docs/DESIGN.md` — 画面設計・トークン
- `docs/DECISIONS.md` — これまでの設計判断。新しい判断をしたら追記する

## コマンド
```bash
uv sync                                   # 依存関係
uv run ruff check . && uv run ruff format --check .
uv run mypy src                           # strict
uv run pytest                             # ネットワークなし
uv run python tests/fixtures/make_sample.py   # ダミーデータの再生成
uv run usmarket render tests/fixtures/sample_summary.json --out site/index.html
SEC_USER_AGENT="usmarket you@example.com" uv run usmarket -v run --date 2026-09-28   # 実データで1日分
uv run python scripts/screenshot.py site/2026-09-28/index.html --out screenshots/ --full
```

## 1ループの手順
1. BACKLOG の `todo` のうち一番上のタスクを `doing` にする
2. 実装し、テストを書く。外部通信は fixture（`tests/fixtures/`）とモックで置き換える
3. ruff / mypy / pytest がすべて通るまで直す
4. 画面を変えたら、fixture からサイトを生成し、スクリーンショット（デスクトップ 1280px・スマホ 390px、ライト・ダーク）を撮って確認する
5. ブランチ `loop/<タスクID>` にコミットし、BACKLOG の状態を `done` にする（🔒 のタスクは `review`）
6. 🔒 のタスクでは止まってユーザーに提示する。それ以外は次のタスクへ進む

## 完了の定義
- 受け入れ条件を満たす / テストがある / lint・型・テストがすべて通る
- 仕様や判断を変えたら SPEC / DECISIONS を更新する
- 画面を変えたら、スクリーンショットで崩れがないことを確認した

## 自分で判断しないこと（必ずユーザーに確認）
- 💰 費用が発生するもの（有料データ、Claude API など）
- 公開範囲の変更、GitHub リポジトリの作成・push、デプロイ・cron の有効化、Discord への実送信（テスト用チャンネルを除く）
- 画面デザインの大きな変更、`DailySummary` から項目を削除する変更
- 利用規約上グレーなデータ取得元の追加
- `SEC_USER_AGENT` に入れる連絡先（ユーザー本人が決める。勝手にメールアドレスを入れない）

## コーディング規約
- Python 3.13、型ヒント必須（mypy strict）。行の長さは110文字
- `DailySummary`（models.py）が生成側と消費側の唯一の契約。変更したら `SCHEMA_VERSION` と DECISIONS を更新する
- データ源・ニュース・通知は `*/base.py` の Protocol を実装する。組み立ては pipeline で行う
- 時刻はすべて tz-aware。取引セッションは米東部時間（`calendar.ET`、zoneinfo で夏時間を処理）、表示は日本時間が基本
- ティッカーは yfinance の表記で保存する（クラス株は `BRK-B`）。YAML では `ON` などが真偽値になるので引用符で囲む
- yfinance は 429 を前提にする（D-05）。テストで実際の API を叩かない
- ニュース・開示は見出し・リンク・メタデータのみを扱い、本文は保存しない
- 表示文言は日本語。コードのコメントは英語でも日本語でもよい
- 秘密情報は環境変数から読み、コミットしない
