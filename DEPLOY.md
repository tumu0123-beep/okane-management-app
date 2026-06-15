# GitHub + Streamlit Cloud 公開手順

このアプリは Streamlit 製です。GitHub Pages では Python サーバーを実行できないため、常時URLで見る用途では Streamlit Community Cloud を使います。

## 重要な注意

- 家計簿データを扱うため、GitHub リポジトリは `Private` 推奨です。
- `.venv/`、`data/`、`__pycache__/`、`.streamlit/secrets.toml` は GitHub に上げません。
- カード家計簿画面は Google Sheets の公開CSVを読みます。
- ポイント画像アップロードと SQLite 保存は、無料クラウド環境では永続保存に向きません。常時利用するなら、後で外部DBまたは Google Sheets 保存に移すのが安全です。
- OpenAI Vision を使う場合、`OPENAI_API_KEY` は GitHub に書かず、Streamlit Cloud の Secrets に設定します。

## GitHub に入れるファイル

最低限:

- `app.py`
- `requirements.txt`
- `runtime.txt`
- `packages.txt`
- `README.md`
- `.gitignore`
- `.streamlit/config.toml`

任意:

- `money_mobile_app_backend.gs`
- `money_mobile_app.html`
- `repair_card_history_import.gs`
- `Gmail家計簿自動転記_引き継ぎ.md`

入れない:

- `.venv/`
- `data/`
- `__pycache__/`
- `*.pyc`
- `.streamlit/secrets.toml`

## Streamlit Community Cloud で公開する

1. GitHub で private repository を作成します。
2. このフォルダの公開対象ファイルを repository に push します。
3. https://share.streamlit.io/ を開きます。
4. `New app` を選びます。
5. Repository を選択します。
6. Branch は `main`、Main file path は `app.py` にします。
7. `Deploy` を押します。
8. 発行された URL をスマホで開きます。

## Secrets

OpenAI Vision を使う場合だけ、Streamlit Cloud の `App settings` -> `Secrets` に以下を設定します。

```toml
OPENAI_API_KEY = "sk-..."
```

Google Sheets のカード家計簿画面だけなら Secrets は不要です。

## 公開後の確認

- `家計簿` 画面で `2026-06` などの月が出る
- 自分負担、利用合計、未回収、相手負担が表示される
- 明細カードが表示される
- `分類` / `扱い` の切り替えが動く

## 編集もスマホで行いたい場合

Streamlit 版は読み取り専用です。`扱い`、`人数`、`回収済み`、メモをスマホから編集したい場合は、Apps Script Web アプリ版を使います。

対象ファイル:

- `money_mobile_app_backend.gs`
- `money_mobile_app.html`

Apps Script プロジェクトに追加し、Web アプリとしてデプロイします。アクセス権は `自分のみ` 推奨です。
