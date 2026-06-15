# GitHub + Streamlit Cloud 公開手順

このアプリは Streamlit 製です。GitHub Pages では Python サーバーを実行できないため、常時URLで見る用途では Streamlit Community Cloud を使います。

## 重要な注意

- `.venv/`、`data/`、`__pycache__/`、`.streamlit/secrets.toml` は GitHub に上げません。
- Google Sheets の CSV URL は GitHub に書かず、Streamlit Cloud の Secrets に設定します。
- アプリは `APP_PASSWORD` が未設定だと停止します。公開URLを知っている人に家計データを見られないようにするためです。
- OpenAI Vision を使う場合、`OPENAI_API_KEY` も Streamlit Cloud の Secrets に設定します。
- Streamlit Community Cloud が private repository を読めない場合は、Secrets 化したうえでリポジトリを Public に変更してデプロイします。

## GitHub に入れるファイル

- `app.py`
- `requirements.txt`
- `runtime.txt`
- `packages.txt`
- `README.md`
- `DEPLOY.md`
- `.gitignore`
- `.streamlit/config.toml`

入れないもの:

- `.venv/`
- `data/`
- `__pycache__/`
- `*.pyc`
- `.streamlit/secrets.toml`

## Streamlit Community Cloud で公開する

1. GitHub に公開対象ファイルを入れます。
2. https://share.streamlit.io/ を開きます。
3. `New app` または `Deploy an app` を選びます。
4. Repository は `tumu0123-beep/okane-management-app`、Branch は `main`、Main file path は `app.py` にします。
5. `Advanced settings` の `Secrets` に下記を設定します。
6. `Deploy` を押します。
7. 発行された `.streamlit.app` のURLをスマホで開きます。

## Secrets

必須:

```toml
APP_PASSWORD = "自分だけが知っているパスワード"
CARD_HISTORY_CSV_URL = "Google Sheets の CSV export URL"
```

OpenAI Vision を使う場合だけ追加:

```toml
OPENAI_API_KEY = "sk-..."
```

## 公開後の確認

- 最初にパスワード画面が出る
- 正しいパスワードでログインできる
- `家計簿` 画面で当月の明細と月別集計が見える
- `分類別` / `扱い別` の切り替えが動く

## スマホから編集したい場合

Streamlit 版は読み取り専用です。`扱い`、`人数`、`回収済み`、メモをスマホから編集したい場合は、Apps Script Web アプリ版を使います。
