# お金管理 Streamlit アプリ

カード家計簿スプレッドシートとポイント残高をまとめて見るためのローカル Web アプリです。

スマホ画面で使うことを想定し、カード家計簿、ポイントダッシュボード、アップロード、OCR確認、ポイント一覧、失効予定、AI交換提案メモを用意しています。

## カード家計簿

アプリ起動時は `家計簿` 画面が開きます。

読み込み元:

- Google Sheets `Gmailカード家計簿`
- シート: `card_history`

できること:

- 月別の自分負担額、利用合計、未回収額、相手負担額を確認
- `扱い` ごとの絞り込み
- 店名、分類、相手、メモ、カード名で検索
- 明細カード表示
- 分類別集計
- 扱い別集計

画面右上の `再読込` を押すと、スプレッドシートCSVを再取得します。

注意:

- Streamlit 版のカード家計簿画面は読み取り専用です。
- 明細の `扱い`、`人数`、`回収済み` などをスマホから編集したい場合は、Apps Script Web アプリ版を使います。

## セットアップ方法

1. Python を用意します。
2. このフォルダで依存関係をインストールします。

```powershell
pip install -r requirements.txt
```

3. Tesseract OCR を使う場合は、別途 Tesseract 本体をインストールします。

Windows では以下のようにインストールし、必要に応じて `tesseract.exe` に PATH を通してください。

```powershell
winget install UB-Mannheim.TesseractOCR
```

4. OpenAI Vision API を使う場合だけ、環境変数を設定します。

```powershell
$env:OPENAI_API_KEY="sk-..."
```

5. PCだけで使う場合は、アプリを起動します。

```powershell
streamlit run app.py
```

## スマホで使う方法

PC とスマホを同じ Wi-Fi に接続してから、以下を実行します。

```powershell
.\run_mobile.ps1
```

起動すると、PowerShell に以下のようなURLが表示されます。

```text
PC URL:      http://127.0.0.1:8501
Phone URL:   http://192.168.x.x:8501
```

スマホのブラウザで `Phone URL` を開いてください。既に `8501` が使われている場合は、`8502` 以降の空きポートが自動で表示されます。スクリーンショットはスマホの写真ライブラリから直接選択できます。

スマホから接続できない場合は、以下を確認してください。

- PC とスマホが同じ Wi-Fi に接続されている
- VPN が通信を分離していない
- Windows Firewall で Python / Streamlit の通信を許可している
- PowerShell の起動ウィンドウを閉じていない
- 表示されたポート番号でアクセスしている

Windows Firewall が原因で開けない場合は、PowerShellを管理者として開き、このフォルダで以下を1回実行してください。

```powershell
.\enable_mobile_firewall_admin.ps1
```

このスクリプトは、Wi-FiをPrivateネットワークに変更できる場合は変更し、`8501-8510` 番ポートへの受信を許可します。

## いつでもURLで見られるようにする方法

GitHub と Streamlit Community Cloud を使うと、PCを起動していなくてもスマホからURLで開けます。

手順は [DEPLOY.md](DEPLOY.md) にまとめています。

注意:

- Streamlit 版のカード家計簿は読み取り専用です。
- 家計簿データを扱うため、`CARD_HISTORY_CSV_URL` と `APP_PASSWORD` は GitHub に書かず、Streamlit Secrets に設定します。
- Streamlit Community Cloud が private repository を読めない場合は、Secrets 化したうえでリポジトリを Public に変更してデプロイします。
- ポイント画像アップロードと SQLite 保存はクラウド無料環境では永続保存に向きません。常時運用するなら、保存先を外部DBまたは Google Sheets に移すのが安全です。

## 使い方

1. `家計簿` 画面でカード明細と月別集計を確認します。
2. `追加` 画面でポイント残高のスクリーンショットを選択します。
3. OCR方式を `pytesseract` または `OpenAI Vision` から選びます。
4. 読み取られた結果を確認し、サービス名、ポイント残高、通常ポイント、期間限定ポイント、有効期限、最終更新日、メモを修正します。
5. `保存する` を押すと SQLite に保存されます。
6. `ポイント` で総保有ポイント、サービス別残高、30日以内の失効警告を確認できます。
7. `一覧` で最新残高を表で確認できます。
8. `失効` で30日以内に失効する期間限定ポイントを確認できます。
9. `AI` で、AIに貼り付けやすい要約テキストと交換候補メモを確認できます。

## 対応サービス

初期設定では以下を想定しています。

- 楽天ポイント
- Vポイント
- JRE POINT
- PayPayポイント
- Ponta
- dポイント
- ANAマイル
- その他

OCR結果やファイル名にサービス名が含まれていれば自動判定します。判定できない場合は確認画面で手動修正してください。

## OCR精度が低い場合の修正方法

- スマホ画面のスクリーンショット解析は `OpenAI Vision` の方が安定します。使う場合は、起動前に以下を設定してください。

```powershell
$env:OPENAI_API_KEY="sk-..."
.\run_mobile.ps1
```

- `pytesseract` を使う場合、Pythonパッケージだけでなく Tesseract 本体が必要です。
- 画像をアップロードしてもフォームが自動入力されない場合は、まず以下を実行してください。

```powershell
winget install UB-Mannheim.TesseractOCR
```

- インストール後、PowerShell と Streamlit アプリを一度閉じて、`.\run_mobile.ps1` で起動し直してください。
- `OpenAI Vision` を使う場合は、`OPENAI_API_KEY` を設定してからアプリを起動してください。
- アップロード後にうまく埋まらない場合は、`読み取ったテキスト` を開いてOCR文字列を確認し、必要なら修正して `このテキストから再入力` を押してください。
- OpenAI Visionを設定している場合は、確認画面の `画像を再解析` で再解析できます。
- スクリーンショットを明るく、文字が大きく写る状態で撮り直してください。
- ポイント残高、有効期限、期間限定ポイントが同じ画面に見える状態で撮影してください。
- `OpenAI Vision` を使うと、画面レイアウトが複雑な場合でも読み取りやすいことがあります。
- 読み取り結果は保存前に必ず確認し、間違っている項目はフォームで修正してください。
- Tesseract の日本語読み取りが弱い場合は、日本語言語データ `jpn` が入っているか確認してください。

## 保存されるデータ

SQLite データベース:

- `data/points.db`

アップロード画像:

- `data/uploads/`

保存項目:

- サービス名
- ポイント残高
- 期間限定ポイント
- 通常ポイント
- 有効期限
- 最終更新日
- 画像ファイル名
- メモ
- OCRテキスト

## 画像削除機能

`アップロード` 画面のアップロード履歴から `削除` を押すと、該当レコードとローカル保存画像を削除します。

## 注意事項

- このアプリはローカル保存前提です。
- スクリーンショットには氏名、会員番号、バーコード、QRコード、利用履歴などの個人情報が写る可能性があります。
- 不要になった画像はアプリの削除ボタン、または `data/uploads/` から削除してください。
- ログインID、パスワード、Cookie は保存しません。
- 各ポイントサイトへの自動ログインやスクレイピングは行いません。
- OpenAI Vision API を使う場合、画像内容がAPIに送信されます。個人情報が写っている画像を送る前に内容を確認してください。
- ポイントの円換算は概算です。初期設定では多くのポイントを `1 pt = 1円`、ANAマイルを `1マイル = 1.5円` として扱っています。

## ファイル構成

```text
.
├── app.py
├── run_mobile.ps1
├── enable_mobile_firewall_admin.ps1
├── requirements.txt
├── README.md
├── DEPLOY.md
├── runtime.txt
├── packages.txt
├── money_mobile_app_backend.gs
├── money_mobile_app.html
├── .streamlit/
│   └── config.toml
└── data/
    ├── points.db
    └── uploads/
```

## Apps Script Web アプリ版

スマホからカード明細を編集する用途向けに、Apps Script Web アプリ用ファイルも用意しています。

- `money_mobile_app_backend.gs`
- `money_mobile_app.html`

これらを既存の Apps Script プロジェクトへ追加すると、Google Sheets を直接読み書きするスマホ向け Web アプリとして使えます。
