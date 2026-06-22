from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sqlite3
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from urllib import parse, request

import altair as alt
import pandas as pd
import streamlit as st
from PIL import Image, ImageEnhance, ImageOps


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "points.db"
CARD_HISTORY_CSV_URL_SECRET = "CARD_HISTORY_CSV_URL"
CARD_HISTORY_UPDATE_URL_SECRET = "CARD_HISTORY_UPDATE_URL"
CARD_HISTORY_UPDATE_TOKEN_SECRET = "CARD_HISTORY_UPDATE_TOKEN"
APP_PASSWORD_SECRET = "APP_PASSWORD"
CARD_HANDLINGS = ["すべて", "自分の支出", "割り勘", "立替", "お使い", "不明"]
CARD_EDIT_HANDLINGS = ["自分の支出", "割り勘", "立替", "お使い", "不明"]
CARD_PAYMENT_METHOD_PRESETS = ["現金", "PayPay", "楽天ペイ", "交通系IC", "口座振替", "その他"]
CARD_LARGE_CATEGORY_PRESETS = ["未分類", "食費", "日用品", "交通", "通信", "住居", "水道光熱", "医療", "美容", "娯楽", "旅行", "仕事", "その他"]
CARD_SMALL_CATEGORY_PRESETS = ["", "スーパー", "コンビニ", "外食", "通販", "電子マネー", "交通", "宿泊", "サブスク", "その他"]

SERVICE_META = {
    "楽天ポイント": {"mark": "R", "color": "#d71920", "yen_rate": 1.0, "keywords": ["楽天", "rakuten"]},
    "Vポイント": {"mark": "V", "color": "#005bac", "yen_rate": 1.0, "keywords": ["vポイント", "v point", "vpoint"]},
    "JRE POINT": {"mark": "J", "color": "#2f8f4e", "yen_rate": 1.0, "keywords": ["jre", "jre point"]},
    "PayPayポイント": {"mark": "P", "color": "#e60012", "yen_rate": 1.0, "keywords": ["paypay"]},
    "Ponta": {"mark": "P", "color": "#f39800", "yen_rate": 1.0, "keywords": ["ponta"]},
    "dポイント": {"mark": "d", "color": "#d70c18", "yen_rate": 1.0, "keywords": ["dポイント", "d point", "dpoint"]},
    "ANAマイル": {"mark": "A", "color": "#004098", "yen_rate": 1.5, "keywords": ["ana", "マイル"]},
    "その他": {"mark": "?", "color": "#6b7280", "yen_rate": 1.0, "keywords": []},
}

SERVICE_NAMES = list(SERVICE_META.keys())
OCR_ERROR_PREFIX = "OCR_ERROR:"
POINT_JSON_TEMPLATE = {
    "service_name": "楽天ポイント",
    "total_points": 8356,
    "normal_points": 6856,
    "limited_points": 1500,
    "expiration_date": "2025-06-30",
    "updated_at": "2026-06-13",
    "memo": "",
    "raw_text": "画面に見える文字",
}


def config_value(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value.strip()
    try:
        secret_value = st.secrets.get(name, "")
    except Exception:
        return ""
    return str(secret_value or "").strip()


def require_app_password() -> None:
    expected_password = config_value(APP_PASSWORD_SECRET)
    if not expected_password:
        st.error("APP_PASSWORD is not configured. Set it in Streamlit Secrets before using this app.")
        st.stop()

    if st.session_state.get("app_authenticated") is True:
        return

    st.title("お金管理")
    entered_password = st.text_input("パスワード", type="password")
    if st.button("ログイン", use_container_width=True):
        if entered_password == expected_password:
            st.session_state["app_authenticated"] = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    st.stop()


def init_storage() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS point_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                total_points INTEGER NOT NULL DEFAULT 0,
                limited_points INTEGER NOT NULL DEFAULT 0,
                normal_points INTEGER NOT NULL DEFAULT 0,
                expiration_date TEXT,
                updated_at TEXT NOT NULL,
                image_filename TEXT,
                image_path TEXT,
                memo TEXT,
                ocr_text TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_records() -> pd.DataFrame:
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM point_records ORDER BY updated_at DESC, id DESC").fetchall()
    if not rows:
        return pd.DataFrame(
            columns=[
                "id",
                "service_name",
                "total_points",
                "limited_points",
                "normal_points",
                "expiration_date",
                "updated_at",
                "image_filename",
                "image_path",
                "memo",
                "ocr_text",
                "created_at",
            ]
        )
    return pd.DataFrame([dict(row) for row in rows])


def load_latest_by_service() -> pd.DataFrame:
    df = load_records()
    if df.empty:
        return df
    sorted_df = df.sort_values(["service_name", "updated_at", "id"], ascending=[True, False, False])
    return sorted_df.drop_duplicates("service_name", keep="first").sort_values("total_points", ascending=False)


def save_record(values: dict[str, Any]) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO point_records (
                service_name, total_points, limited_points, normal_points,
                expiration_date, updated_at, image_filename, image_path,
                memo, ocr_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["service_name"],
                int(values["total_points"] or 0),
                int(values["limited_points"] or 0),
                int(values["normal_points"] or 0),
                values.get("expiration_date") or None,
                values["updated_at"],
                values.get("image_filename"),
                values.get("image_path"),
                values.get("memo", ""),
                values.get("ocr_text", ""),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def delete_record(record_id: int) -> None:
    with connect_db() as conn:
        row = conn.execute("SELECT image_path FROM point_records WHERE id = ?", (record_id,)).fetchone()
        conn.execute("DELETE FROM point_records WHERE id = ?", (record_id,))
        conn.commit()
    if row and row["image_path"]:
        path = Path(row["image_path"])
        if path.exists() and path.is_file() and path.parent == UPLOAD_DIR:
            path.unlink()


def save_uploaded_image(uploaded_file) -> tuple[str, Path]:
    suffix = Path(uploaded_file.name).suffix.lower() or ".png"
    safe_stem = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(uploaded_file.name).stem).strip("_") or "upload"
    filename = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}_{safe_stem}{suffix}"
    image_path = UPLOAD_DIR / filename
    image_path.write_bytes(uploaded_file.getbuffer())
    return filename, image_path


def run_ocr(image_path: Path, engine: str) -> str:
    if engine == "OpenAI Vision":
        return run_openai_vision(image_path)
    return run_tesseract(image_path)


def run_tesseract(image_path: Path) -> str:
    try:
        import pytesseract

        tesseract_path = find_tesseract_executable()
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)

        image = prepare_image_for_ocr(image_path)
        try:
            return pytesseract.image_to_string(image, lang="jpn+eng", config="--psm 6").strip()
        except Exception:
            return pytesseract.image_to_string(image, lang="eng", config="--psm 6").strip()
    except Exception as exc:
        return (
            f"{OCR_ERROR_PREFIX} pytesseract を実行できませんでした。Tesseract 本体のインストールまたは PATH 設定を確認してください。\n"
            f"エラー: {exc}"
        )


def find_tesseract_executable() -> Path | None:
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    candidates = [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    return next((path for path in candidates if path.exists()), None)


def prepare_image_for_ocr(image_path: Path) -> Image.Image:
    image = Image.open(image_path)
    image = ImageOps.exif_transpose(image).convert("RGB")
    max_width = 1800
    if image.width < max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, int(image.height * ratio)))
    gray = ImageOps.grayscale(image)
    gray = ImageEnhance.Contrast(gray).enhance(1.8)
    gray = ImageEnhance.Sharpness(gray).enhance(1.4)
    return gray


def run_openai_vision(image_path: Path) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return f"{OCR_ERROR_PREFIX} OPENAI_API_KEY が未設定のため OpenAI Vision OCR は実行していません。"

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        mime_type = image_mime_type(image_path)
        response = client.responses.create(
            model=os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "あなたはポイント残高スクリーンショット専用の画像解析器です。"
                                "画像内に複数の画面やカードがある場合は、最も大きく表示されている残高画面、"
                                "またはユーザーが保存対象にしそうなポイント残高部分を優先してください。"
                                "数値はカンマを除いた整数にしてください。"
                                "通常ポイントと期間限定ポイントが読み取れる場合、合計が読めなくても合算して total_points を入れてください。"
                                "日付は YYYY-MM-DD に正規化してください。"
                                "サービス名は必ず次のいずれかに正規化してください: "
                                + ", ".join(SERVICE_NAMES)
                                + "。"
                                "出力はMarkdownや説明文を含めず、JSONオブジェクトだけにしてください。"
                                f"JSON形式例: {json.dumps(POINT_JSON_TEMPLATE, ensure_ascii=False)}"
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime_type};base64,{encoded}",
                        },
                    ],
                }
            ],
        )
        return response.output_text.strip()
    except Exception as exc:
        return f"{OCR_ERROR_PREFIX} OpenAI Vision OCRを実行できませんでした。\nエラー: {exc}"


def image_mime_type(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def normalize_google_sheet_csv_url(csv_url: str) -> str:
    value = csv_url.strip()
    if not value:
        return value

    parsed = parse.urlparse(value)
    if "docs.google.com" not in parsed.netloc or "/spreadsheets/d/" not in parsed.path:
        return value

    parts = [part for part in parsed.path.split("/") if part]
    try:
        spreadsheet_id = parts[parts.index("d") + 1]
    except (ValueError, IndexError):
        return value

    query = parse.parse_qs(parsed.query)
    gid = (query.get("gid") or ["0"])[0]
    if not gid and parsed.fragment.startswith("gid="):
        gid = parsed.fragment.split("=", 1)[1]
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid or '0'}"


def read_card_history_csv(csv_url: str) -> pd.DataFrame:
    normalized_url = normalize_google_sheet_csv_url(csv_url)
    cache_buster = f"_ts={int(datetime.now().timestamp())}"
    separator = "&" if "?" in normalized_url else "?"
    url = f"{normalized_url}{separator}{cache_buster}"
    try:
        return pd.read_csv(url)
    except Exception as exc:
        raise RuntimeError(
            "Google Sheets の CSV を取得できませんでした。Streamlit Secrets の CARD_HISTORY_CSV_URL と、"
            "スプレッドシートの公開/共有設定を確認してください。"
        ) from exc


def card_history_update_configured() -> bool:
    return bool(config_value(CARD_HISTORY_UPDATE_URL_SECRET))


def post_card_history_update(payload: dict[str, Any]) -> dict[str, Any]:
    update_url = config_value(CARD_HISTORY_UPDATE_URL_SECRET)
    if not update_url:
        raise RuntimeError("CARD_HISTORY_UPDATE_URL is not configured. Set it in Streamlit Secrets.")

    token = config_value(CARD_HISTORY_UPDATE_TOKEN_SECRET)
    body = dict(payload)
    if token:
        body["token"] = token

    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        update_url,
        data=encoded,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            response_body = response.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError("スプレッドシートへの保存に失敗しました。Apps Script のデプロイURLと権限を確認してください。") from exc

    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Apps Script から予期しない応答が返りました。") from exc

    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "Apps Script 側で更新に失敗しました。"))
    return result


def extract_point_fields(text: str, filename: str) -> dict[str, Any]:
    ai_fields = extract_fields_from_json(text)
    if ai_fields:
        return ai_fields

    service = detect_service_name(f"{filename}\n{text}")
    normalized_text = normalize_ocr_text(text)

    numbers = [parse_number(match.group(1)) for match in re.finditer(r"([0-9][0-9,]*)\s*(?:pt|ポイント|p|マイル)", normalized_text, re.I)]
    total = (
        find_number_near_keywords(normalized_text, ["総保有", "合計", "残高", "ポイント残高", "保有"])
        or (max(numbers) if numbers else 0)
    )
    limited = find_number_near_keywords(normalized_text, ["期間限定", "限定"])
    normal = find_number_near_keywords(normalized_text, ["通常", "通常ポイント"])
    if total and limited and not normal and total >= limited:
        normal = total - limited
    if total and normal and not limited and total >= normal:
        limited = total - normal
    if not total and (normal or limited):
        total = normal + limited

    expiration = find_date_after_keywords(normalized_text, ["有効期限", "期限", "失効"])
    updated = find_date_after_keywords(normalized_text, ["最終更新日", "最終更新", "更新日", "取得日", "更新"]) or date.today().isoformat()

    return {
        "service_name": service,
        "total_points": total,
        "limited_points": limited or 0,
        "normal_points": normal or max(total - (limited or 0), 0),
        "expiration_date": expiration,
        "updated_at": updated,
        "memo": "",
    }


def normalize_ocr_text(text: str) -> str:
    replacements = {
        "，": ",",
        "．": ".",
        "／": "/",
        "ー": "-",
        "−": "-",
        "Ｐ": "P",
        "ｐ": "p",
        "ｔ": "t",
        "ポイント": "ポイント",
        "ボイント": "ポイント",
        "楽天ボイント": "楽天ポイント",
        "期間限定ボイント": "期間限定ポイント",
        "通常ボイント": "通常ポイント",
    }
    normalized = text
    for before, after in replacements.items():
        normalized = normalized.replace(before, after)
    normalized = re.sub(r"(?<=\d)\s*,\s*(?=\d{3}\b)", ",", normalized)
    normalized = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", ",", normalized)
    return normalized


def is_ocr_error(text: str) -> bool:
    return text.strip().startswith(OCR_ERROR_PREFIX)


def has_meaningful_extraction(values: dict[str, Any]) -> bool:
    if not values:
        return False
    return (
        values.get("service_name") != "その他"
        or int(values.get("total_points") or 0) > 0
        or int(values.get("normal_points") or 0) > 0
        or int(values.get("limited_points") or 0) > 0
        or bool(values.get("expiration_date"))
    )


def extract_fields_from_json(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.I | re.M).strip()
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    service = detect_service_name(str(data.get("service_name") or ""))

    total = parse_json_number(data.get("total_points"))
    normal = parse_json_number(data.get("normal_points"))
    limited = parse_json_number(data.get("limited_points"))
    if total and limited and not normal and total >= limited:
        normal = total - limited
    if total and normal and not limited and total >= normal:
        limited = total - normal

    expiration = normalize_date_text(str(data.get("expiration_date") or ""))
    updated = normalize_date_text(str(data.get("updated_at") or "")) or date.today().isoformat()
    return {
        "service_name": service,
        "total_points": total,
        "limited_points": limited,
        "normal_points": normal,
        "expiration_date": expiration,
        "updated_at": updated,
        "memo": str(data.get("memo") or ""),
    }


def parse_json_number(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"[0-9][0-9,]*", str(value))
    return parse_number(match.group(0)) if match else 0


def detect_service_name(source: str) -> str:
    normalized = source.lower()
    for name in SERVICE_NAMES:
        if name.lower() in normalized:
            return name
    for name, meta in SERVICE_META.items():
        if any(keyword.lower() in normalized for keyword in meta["keywords"]):
            return name
    return "その他"


def normalize_date_text(value: str) -> str:
    match = re.search(r"(20[0-9]{2})[年/.-]\s*([0-9]{1,2})[月/.-]\s*([0-9]{1,2})日?", value)
    if not match:
        return ""
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()


def parse_number(raw: str) -> int:
    return int(raw.replace(",", ""))


def find_number_near_keywords(text: str, keywords: list[str]) -> int:
    compact = re.sub(r"\s+", " ", text)
    for keyword in keywords:
        patterns = [
            rf"{keyword}[^0-9]{{0,30}}([0-9][0-9,]*)\s*(?:pt|ポイント|p|マイル)?",
            rf"([0-9][0-9,]*)\s*(?:pt|ポイント|p|マイル)?[^。\n]{{0,30}}{keyword}",
        ]
        for pattern in patterns:
            match = re.search(pattern, compact, re.I)
            if match:
                return parse_number(match.group(1))
    return 0


def find_first_date(text: str, keywords: list[str] | None = None) -> str:
    candidates = []
    for match in re.finditer(r"(20[0-9]{2})[年/.-]\s*([0-9]{1,2})[月/.-]\s*([0-9]{1,2})日?", text):
        found = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        context = text[max(0, match.start() - 30) : match.end() + 30]
        if not keywords or any(keyword in context for keyword in keywords):
            candidates.append(found.isoformat())
    return candidates[0] if candidates else ""


def find_date_after_keywords(text: str, keywords: list[str]) -> str:
    date_pattern = r"(20[0-9]{2})[年/.-]\s*([0-9]{1,2})[月/.-]\s*([0-9]{1,2})日?"
    compact = re.sub(r"\s+", " ", text)
    for keyword in keywords:
        match = re.search(rf"{keyword}[^0-9]{{0,40}}{date_pattern}", compact)
        if match:
            year, month, day = match.group(1), match.group(2), match.group(3)
            return date(int(year), int(month), int(day)).isoformat()
    return ""


def yen_total(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    total = 0.0
    for _, row in df.iterrows():
        total += int(row["total_points"] or 0) * SERVICE_META.get(row["service_name"], SERVICE_META["その他"])["yen_rate"]
    return total


@st.cache_data(ttl=300, show_spinner=False)
def load_card_history() -> pd.DataFrame:
    csv_url = config_value(CARD_HISTORY_CSV_URL_SECRET)
    if not csv_url:
        raise RuntimeError("CARD_HISTORY_CSV_URL is not configured. Set it in Streamlit Secrets.")
    df = read_card_history_csv(csv_url)
    df = df.dropna(how="all")
    if df.empty:
        return normalize_card_history_df(df)
    return normalize_card_history_df(df)


def normalize_card_history_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["行番号"] = range(2, len(df) + 2)
    expected = [
        "行番号",
        "日付",
        "利用店名",
        "金額",
        "カード名",
        "大分類",
        "小分類",
        "扱い",
        "相手",
        "人数",
        "自分負担額",
        "相手負担額",
        "回収済み",
        "メモ",
        "メールID",
        "メールURL",
    ]
    for column in expected:
        if column not in df.columns:
            df[column] = None

    normalized = df[expected].copy()
    normalized["行番号"] = pd.to_numeric(normalized["行番号"], errors="coerce").fillna(0).astype(int)
    normalized["日付"] = pd.to_datetime(normalized["日付"], errors="coerce")
    normalized = normalized.dropna(subset=["日付", "利用店名", "金額"])
    for column in ["金額", "人数", "自分負担額", "相手負担額"]:
        normalized[column] = (
            normalized[column]
            .astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("nan", "", regex=False)
            .replace("", "0")
        )
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0)

    normalized["扱い"] = normalized["扱い"].fillna("自分の支出").replace("", "自分の支出")
    normalized["相手"] = normalized["相手"].fillna("")
    normalized["メモ"] = normalized["メモ"].fillna("")
    normalized["大分類"] = normalized["大分類"].fillna("未分類").replace("", "未分類")
    normalized["小分類"] = normalized["小分類"].fillna("")
    normalized["カード名"] = normalized["カード名"].fillna("")
    normalized["回収済み"] = normalized["回収済み"].astype(str).str.upper().isin(["TRUE", "1", "YES"])
    normalized = normalize_card_burden_amounts(normalized)
    normalized["月"] = normalized["日付"].dt.strftime("%Y-%m")
    normalized["日付表示"] = normalized["日付"].dt.strftime("%Y/%m/%d")
    return normalized.sort_values("日付", ascending=False)


def normalize_card_burden_amounts(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()

    own_mask = normalized["扱い"] == "自分の支出"
    normalized.loc[own_mask, "人数"] = 0
    normalized.loc[own_mask, "自分負担額"] = normalized.loc[own_mask, "金額"]
    normalized.loc[own_mask, "相手負担額"] = 0

    split_mask = normalized["扱い"] == "割り勘"
    split_counts = normalized.loc[split_mask, "人数"].where(normalized.loc[split_mask, "人数"] >= 2, 2)
    split_counts = split_counts.clip(lower=2, upper=10).round()
    normalized.loc[split_mask, "人数"] = split_counts
    normalized.loc[split_mask, "自分負担額"] = (normalized.loc[split_mask, "金額"] / split_counts).round()
    normalized.loc[split_mask, "相手負担額"] = normalized.loc[split_mask, "金額"] - normalized.loc[split_mask, "自分負担額"]

    advance_mask = normalized["扱い"].isin(["立替", "お使い"])
    normalized.loc[advance_mask, "人数"] = 0
    normalized.loc[advance_mask, "自分負担額"] = 0
    normalized.loc[advance_mask, "相手負担額"] = normalized.loc[advance_mask, "金額"]

    return normalized


def card_history_summary(df: pd.DataFrame) -> dict[str, int]:
    if df.empty:
        return {
            "count": 0,
            "total": 0,
            "own": 0,
            "partner": 0,
            "unpaid": 0,
            "alerts": 0,
        }
    unpaid = df[(df["扱い"].isin(["立替", "お使い"])) & (~df["回収済み"])]["金額"].sum()
    alerts = int((df["扱い"] == "不明").sum() + ((df["扱い"] == "割り勘") & (df["自分負担額"] == 0)).sum())
    return {
        "count": int(len(df)),
        "total": int(df["金額"].sum()),
        "own": int(df["自分負担額"].sum()),
        "partner": int(df["相手負担額"].sum()),
        "unpaid": int(unpaid),
        "alerts": alerts,
    }


def card_money(value: Any) -> str:
    return f"¥{int(float(value or 0)):,}"


def filter_card_history(df: pd.DataFrame, month: str, handling: str, query: str) -> pd.DataFrame:
    filtered = df.copy()
    if month:
        filtered = filtered[filtered["月"] == month]
    if handling and handling != "すべて":
        filtered = filtered[filtered["扱い"] == handling]
    if query:
        normalized_query = normalize_card_query(query)
        haystack = (
            filtered["利用店名"].astype(str)
            + " "
            + filtered["大分類"].astype(str)
            + " "
            + filtered["小分類"].astype(str)
            + " "
            + filtered["相手"].astype(str)
            + " "
            + filtered["メモ"].astype(str)
            + " "
            + filtered["カード名"].astype(str)
        ).map(normalize_card_query)
        filtered = filtered[haystack.str.contains(normalized_query, regex=False, na=False)]
    return filtered


def normalize_card_query(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"\s+", "", text)


def handling_badge(handling: str) -> str:
    colors = {
        "自分の支出": ("#d9f2eb", "#0e7c66"),
        "割り勘": ("#dbeafe", "#1d4ed8"),
        "立替": ("#fef3c7", "#975a16"),
        "お使い": ("#fef3c7", "#975a16"),
        "不明": ("#fee4e2", "#b42318"),
    }
    bg, fg = colors.get(handling, ("#f1f5f9", "#475569"))
    return f"<span class='money-chip' style='background:{bg};color:{fg}'>{escape(str(handling or '不明'))}</span>"


def expiration_df(df: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    if df.empty:
        return df
    today = date.today()
    rows = []
    for _, row in df.iterrows():
        exp = parse_iso_date(row.get("expiration_date"))
        limited = int(row.get("limited_points") or 0)
        if exp and limited > 0 and 0 <= (exp - today).days <= days:
            item = row.to_dict()
            item["days_left"] = (exp - today).days
            rows.append(item)
    return pd.DataFrame(rows).sort_values("days_left") if rows else pd.DataFrame()


def parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def make_ai_summary(latest: pd.DataFrame, expiring: pd.DataFrame) -> str:
    total_yen = int(round(yen_total(latest)))
    lines = [
        f"現在のポイント総額は円換算で約{total_yen:,}円です。",
        "サービス別の最新残高:",
    ]
    for _, row in latest.iterrows():
        lines.append(
            f"- {row['service_name']}: 合計{int(row['total_points']):,}、通常{int(row['normal_points']):,}、期間限定{int(row['limited_points']):,}"
        )
    if not expiring.empty:
        lines.append("30日以内に失効するポイント:")
        for _, row in expiring.iterrows():
            lines.append(
                f"- {row['service_name']}: {int(row['limited_points']):,}ポイント、期限{row['expiration_date']}、あと{int(row['days_left'])}日"
            )
    else:
        lines.append("30日以内に失効する期間限定ポイントは登録されていません。")
    return "\n".join(lines)


def make_exchange_suggestions(latest: pd.DataFrame, expiring: pd.DataFrame) -> list[dict[str, str]]:
    suggestions = []
    if not expiring.empty:
        for _, row in expiring.head(3).iterrows():
            service = row["service_name"]
            points = int(row["limited_points"])
            suggestions.append(
                {
                    "title": f"{service}の期限切れ前に消化",
                    "body": f"{points:,} pt があと{int(row['days_left'])}日で失効予定。少額決済、チャージ、日用品購入を優先。",
                }
            )
    if "ANAマイル" in set(latest["service_name"]):
        miles = int(latest.loc[latest["service_name"] == "ANAマイル", "total_points"].iloc[0])
        suggestions.append({"title": "ANAマイルの使い道確認", "body": f"{miles:,}マイルを登録中。航空券、提携ポイント交換、期限を確認。"})
    if not suggestions:
        suggestions.append({"title": "期限情報を追加", "body": "各サービスの期限付きポイントを登録すると、交換・消化候補を出しやすくなります。"})
    return suggestions


def css() -> None:
    st.markdown(
        """
        <style>
        :root { --primary: #6c63ff; --accent: #7c3aed; --danger: #dc2626; }
        .stApp { background: #f8f8fc; }
        .block-container { max-width: 520px; padding: 1.2rem 1rem 6rem; }
        [data-testid="stSidebar"] { display: none; }
        .app-title { text-align: center; font-weight: 800; font-size: 1.1rem; margin: 0 0 1rem; color: #111827; }
        h1, h2, h3, h4, h5, h6, p, label,
        [data-testid="stMarkdownContainer"] h1,
        [data-testid="stMarkdownContainer"] h2,
        [data-testid="stMarkdownContainer"] h3,
        [data-testid="stMarkdownContainer"] h4 { color: #111827 !important; }
        .hero {
            color: white; border-radius: 22px; padding: 22px 20px;
            background: linear-gradient(135deg, #5b7cff 0%, #7c3aed 100%);
            box-shadow: 0 16px 34px rgba(86, 83, 255, .25);
        }
        .hero .label { opacity: .9; font-size: .85rem; }
        .hero .amount { font-size: 2.35rem; font-weight: 900; line-height: 1.05; margin: .55rem 0; }
        .card {
            background: white; border: 1px solid #ececf4; border-radius: 16px; padding: 14px 16px;
            box-shadow: 0 8px 24px rgba(18, 23, 34, .05); margin: .75rem 0;
        }
        .row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .service { display: flex; align-items: center; gap: 12px; min-width: 0; }
        .logo {
            width: 34px; height: 34px; border-radius: 10px; color: white;
            display: inline-flex; align-items: center; justify-content: center; font-weight: 900;
        }
        .name { font-weight: 800; color: #111827; }
        .sub { color: #6b7280; font-size: .78rem; margin-top: 2px; }
        .points { font-weight: 900; color: #111827; white-space: nowrap; }
        .danger { color: var(--danger); font-weight: 900; }
        .muted { color: #6b7280; font-size: .86rem; }
        .tip { background: #fff8eb; border-radius: 14px; padding: 13px 14px; color: #4b5563; font-size: .88rem; }
        .upload-box { border: 1.5px dashed #c5bdfa; border-radius: 22px; padding: 18px; background: white; }
        .nav-card {
            background: rgba(255,255,255,.96); border: 1px solid #ececf4; border-radius: 16px;
            padding: 6px 8px; margin-bottom: 14px; box-shadow: 0 8px 20px rgba(18, 23, 34, .05);
        }
        .stRadio [role="radiogroup"] { display: grid; grid-template-columns: repeat(6, 1fr); gap: 4px; }
        .stRadio label {
            justify-content: center; text-align: center; min-height: 40px; border-radius: 12px;
            padding: 4px 2px; font-size: .78rem; background: #f7f7fb; white-space: nowrap;
        }
        [data-testid="stButtonGroup"] button {
            background: #ffffff !important; color: #111827 !important; border-color: #ececf4 !important;
            min-height: 38px; padding: 4px 8px;
        }
        [data-testid="stButtonGroup"] button[aria-pressed="true"] {
            background: #f2efff !important; color: #5b3df5 !important; border-color: #7c3aed !important;
            font-weight: 800;
        }
        div[data-testid="stMetricValue"] { font-size: 1.55rem; }
        button[kind="primary"], .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #5b7cff, #7c3aed);
        }
        .money-hero {
            background: #0f172a; color: white; border-radius: 18px; padding: 18px 16px;
            box-shadow: 0 14px 32px rgba(15, 23, 42, .18); margin-bottom: .75rem;
        }
        .money-hero .amount { font-size: 2rem; font-weight: 900; line-height: 1.05; margin: .45rem 0; }
        .money-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: .75rem 0; }
        .money-kpi {
            background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px;
            min-height: 86px; box-shadow: 0 6px 16px rgba(18, 23, 34, .04);
        }
        .money-kpi-label { color: #64748b; font-size: .76rem; font-weight: 800; }
        .money-kpi-value { color: #111827; font-size: 1.28rem; font-weight: 900; margin-top: 7px; overflow-wrap: anywhere; }
        .money-card {
            background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px 13px;
            box-shadow: 0 6px 16px rgba(18, 23, 34, .04); margin: .55rem 0;
        }
        .money-card-top { display: flex; justify-content: space-between; gap: 10px; align-items: start; }
        .money-merchant { font-weight: 900; color: #111827; line-height: 1.28; word-break: break-word; }
        .money-amount { font-weight: 900; color: #111827; white-space: nowrap; }
        .money-meta { color: #64748b; font-size: .78rem; margin-top: 4px; }
        .money-chip {
            display: inline-flex; align-items: center; border-radius: 999px; padding: 3px 8px;
            min-height: 23px; font-size: .76rem; font-weight: 900; margin-right: 4px; margin-top: 8px;
        }
        .money-two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
        .money-mini { background: #f8fafc; border-radius: 10px; padding: 9px; color: #64748b; font-size: .76rem; }
        .money-mini b { display: block; color: #111827; font-size: .92rem; margin-top: 2px; }
        .money-table-row {
            display: flex; justify-content: space-between; gap: 12px; align-items: center;
            background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 11px 12px; margin: .45rem 0;
        }
        .money-table-row .label { font-weight: 900; color: #111827; }
        .money-table-row .sub { color: #64748b; font-size: .76rem; }
        .money-table-row .value { font-weight: 900; white-space: nowrap; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def service_badge(service_name: str) -> str:
    meta = SERVICE_META.get(service_name, SERVICE_META["その他"])
    return f"<span class='logo' style='background:{meta['color']}'>{meta['mark']}</span>"


def page_dashboard() -> None:
    latest = load_latest_by_service()
    expiring = expiration_df(latest)
    total = int(round(yen_total(latest)))

    st.markdown("<div class='app-title'>ダッシュボード</div>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="hero">
          <div class="row"><div class="label">総保有ポイント（円換算）</div><div class="label">今月の推移</div></div>
          <div class="amount">¥{total:,}</div>
          <div class="label">登録サービス {len(latest)} 件</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### サービス別ポイント一覧")
    if latest.empty:
        st.info("まだポイントが登録されていません。スクリーンショットをアップロードしてください。")
    else:
        for _, row in latest.head(6).iterrows():
            st.markdown(
                f"""
                <div class="card row">
                  <div class="service">
                    {service_badge(row['service_name'])}
                    <div>
                      <div class="name">{row['service_name']}</div>
                      <div class="sub">通常 {int(row['normal_points']):,} pt / 期間限定 {int(row['limited_points']):,} pt</div>
                    </div>
                  </div>
                  <div class="points">{int(row['total_points']):,} pt</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if not expiring.empty:
        expiring_total = int(expiring["limited_points"].sum())
        st.markdown(
            f"<div class='card row'><div><b>失効予定のポイントがあります</b><div class='sub'>30日以内に失効するポイント</div></div><div class='danger'>{expiring_total:,} pt</div></div>",
            unsafe_allow_html=True,
        )

    show_trend_chart(load_records())


def page_card_budget() -> None:
    st.markdown("<div class='app-title'>カード家計簿</div>", unsafe_allow_html=True)

    refresh_col, note_col = st.columns([1, 2])
    with refresh_col:
        if st.button("再読込", use_container_width=True):
            load_card_history.clear()
            st.rerun()
    with note_col:
        st.caption("Google Sheets の card_history を表示")

    try:
        df = load_card_history()
    except Exception as exc:
        st.error(f"スプレッドシートを読み込めませんでした: {exc}")
        return

    if df.empty:
        st.info("card_history に表示できる明細がありません。")
        return

    months = sorted(df["月"].dropna().unique(), reverse=True)
    default_month = months[0] if months else date.today().strftime("%Y-%m")

    filter_cols = st.columns([1, 1])
    with filter_cols[0]:
        month = st.selectbox("月", months, index=months.index(default_month) if default_month in months else 0)
    with filter_cols[1]:
        handling = st.selectbox("扱い", CARD_HANDLINGS)
    with st.form("card-history-search", border=False):
        search_col, submit_col = st.columns([4, 1])
        with search_col:
            query = st.text_input("検索", placeholder="店名・支払方法・分類・相手・メモ")
        with submit_col:
            st.form_submit_button("検索", use_container_width=True)

    page_card_manual_entry_form(df)

    filtered = filter_card_history(df, month, handling, query)
    summary = card_history_summary(filtered)

    st.markdown(
        f"""
        <div class="money-hero">
          <div class="label">{escape(month)} の自分負担</div>
          <div class="amount">{card_money(summary['own'])}</div>
          <div class="label">表示中 {summary['count']} 件 / 利用合計 {card_money(summary['total'])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="money-grid">
          <div class="money-kpi"><div class="money-kpi-label">未回収</div><div class="money-kpi-value">{card_money(summary['unpaid'])}</div></div>
          <div class="money-kpi"><div class="money-kpi-label">相手負担</div><div class="money-kpi-value">{card_money(summary['partner'])}</div></div>
          <div class="money-kpi"><div class="money-kpi-label">確認待ち</div><div class="money-kpi-value">{summary['alerts']}件</div></div>
          <div class="money-kpi"><div class="money-kpi-label">明細数</div><div class="money-kpi-value">{summary['count']}件</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if hasattr(st, "segmented_control"):
        view = st.segmented_control("表示", ["明細", "分類", "扱い"], default="明細", label_visibility="collapsed")
    else:
        view = st.radio("表示", ["明細", "分類", "扱い"], horizontal=True, label_visibility="collapsed")

    if view == "分類":
        page_card_category_summary(filtered)
    elif view == "扱い":
        page_card_handling_summary(filtered)
    else:
        page_card_entries(filtered)


def page_card_manual_entry_form(df: pd.DataFrame) -> None:
    with st.expander("現金・PayPayなどを手入力", expanded=False):
        if not card_history_update_configured():
            st.caption("保存先の Apps Script URL が未設定です。Secrets を設定すると手入力を追加できます。")
            return

        payment_options = card_select_options(df["カード名"], CARD_PAYMENT_METHOD_PRESETS, "現金")
        large_options = card_select_options(df["大分類"], CARD_LARGE_CATEGORY_PRESETS, "未分類")
        small_options = card_select_options(df["小分類"], CARD_SMALL_CATEGORY_PRESETS, "")

        with st.form("card-manual-entry-create", clear_on_submit=True):
            entry_date = st.date_input("日付", value=date.today())
            payment_method = st.selectbox("支払方法", payment_options, index=payment_options.index("現金") if "現金" in payment_options else 0)
            merchant = st.text_input("利用店名", placeholder="スーパー、PayPay送金、現金支払いなど")
            amount = st.number_input("金額", min_value=0, step=100, format="%d")
            large_category = st.selectbox("大分類", large_options, index=large_options.index("未分類") if "未分類" in large_options else 0)
            small_category = st.selectbox("小分類", small_options)
            edit_cols = st.columns([1, 1])
            with edit_cols[0]:
                handling = st.selectbox("扱い", CARD_EDIT_HANDLINGS, index=0, key="manual_handling")
            with edit_cols[1]:
                split_count = st.selectbox("人数", list(range(2, 11)), index=0, key="manual_split_count")
            person = st.text_input("相手")
            collected = st.checkbox("回収済み")
            memo = st.text_area("メモ", height=80)
            submitted = st.form_submit_button("手入力を追加", type="primary", use_container_width=True)

        if submitted:
            if not merchant.strip():
                st.error("利用店名を入力してください。")
                return
            if int(amount or 0) <= 0:
                st.error("金額を入力してください。")
                return
            try:
                post_card_history_update(
                    {
                        "action": "createManualEntry",
                        "date": entry_date.strftime("%Y-%m-%d"),
                        "paymentMethod": payment_method,
                        "merchant": merchant,
                        "amount": int(amount),
                        "largeCategory": large_category,
                        "smallCategory": small_category,
                        "handling": handling,
                        "splitCount": split_count,
                        "person": person,
                        "collected": collected,
                        "memo": memo,
                    }
                )
                load_card_history.clear()
                st.success("手入力を追加しました。")
                st.rerun()
            except Exception as exc:
                st.error(f"追加できませんでした: {exc}")


def page_card_entries(df: pd.DataFrame) -> None:
    st.markdown("#### 明細")
    if df.empty:
        st.info("条件に合う明細がありません。")
        return

    if not card_history_update_configured():
        st.warning("編集を保存するには Streamlit Secrets に CARD_HISTORY_UPDATE_URL を設定してください。表示だけならこのまま使えます。")

    max_rows = st.slider("表示件数", 20, 120, 50, step=10)
    for _, row in df.head(max_rows).iterrows():
        handling = str(row["扱い"] or "不明")
        person = str(row["相手"] or "").strip()
        memo = str(row["メモ"] or "").strip()
        person_chip = f"<span class='money-chip' style='background:#f1f5f9;color:#475569'>{escape(person)}</span>" if person else ""
        collected_chip = "<span class='money-chip' style='background:#d9f2eb;color:#0e7c66'>回収済み</span>" if bool(row["回収済み"]) else ""
        memo_html = f"<div class='money-meta'>メモ: {escape(memo)}</div>" if memo else ""
        st.markdown(
            f"""
            <div class="money-card">
              <div class="money-card-top">
                <div>
                  <div class="money-merchant">{escape(str(row['利用店名']))}</div>
                  <div class="money-meta">{escape(str(row['日付表示']))} / {escape(str(row['大分類']))} / {escape(str(row['カード名']))}</div>
                </div>
                <div class="money-amount">{card_money(row['金額'])}</div>
              </div>
              <div>{handling_badge(handling)}{person_chip}{collected_chip}</div>
              <div class="money-two">
                <div class="money-mini">自分負担<b>{card_money(row['自分負担額'])}</b></div>
                <div class="money-mini">相手負担<b>{card_money(row['相手負担額'])}</b></div>
              </div>
              {memo_html}
            </div>
            """,
            unsafe_allow_html=True,
        )
        page_card_entry_editor(row, df)


def page_card_entry_editor(row: pd.Series, df: pd.DataFrame) -> None:
    row_number = int(row.get("行番号") or 0)
    if row_number < 2:
        return

    title = f"編集: {row['日付表示']} {row['利用店名']} {card_money(row['金額'])}"
    with st.expander(title, expanded=False):
        if not card_history_update_configured():
            st.caption("保存先の Apps Script URL が未設定です。DEPLOY.md の CARD_HISTORY_UPDATE_URL を設定すると、ここからスプレッドシートへ保存できます。")
            return

        large_options = card_select_options(df["大分類"], CARD_LARGE_CATEGORY_PRESETS, str(row["大分類"] or "未分類"))
        small_options = card_select_options(df["小分類"], CARD_SMALL_CATEGORY_PRESETS, str(row["小分類"] or ""))
        current_handling = str(row["扱い"] or "自分の支出")
        if current_handling not in CARD_EDIT_HANDLINGS:
            current_handling = "不明"
        split_count = int(row["人数"] or 2)
        if split_count < 2:
            split_count = 2

        with st.form(f"card-entry-edit-{row_number}"):
            large_category = st.selectbox(
                "大分類",
                large_options,
                index=large_options.index(str(row["大分類"] or "未分類")) if str(row["大分類"] or "未分類") in large_options else 0,
            )
            small_category = st.selectbox(
                "子分類",
                small_options,
                index=small_options.index(str(row["小分類"] or "")) if str(row["小分類"] or "") in small_options else 0,
            )
            edit_cols = st.columns([1, 1])
            with edit_cols[0]:
                new_handling = st.selectbox("扱い", CARD_EDIT_HANDLINGS, index=CARD_EDIT_HANDLINGS.index(current_handling))
            with edit_cols[1]:
                new_split_count = st.selectbox("人数", list(range(2, 11)), index=max(0, min(split_count, 10) - 2))
            person = st.text_input("相手", value=str(row["相手"] or ""))
            collected = st.checkbox("回収済み", value=bool(row["回収済み"]))
            memo = st.text_area("メモ", value=str(row["メモ"] or ""), height=80)
            submitted = st.form_submit_button("スプレッドシートへ保存", type="primary", use_container_width=True)

        if submitted:
            try:
                post_card_history_update(
                    {
                        "rowNumber": row_number,
                        "largeCategory": large_category,
                        "smallCategory": small_category,
                        "handling": new_handling,
                        "splitCount": new_split_count,
                        "person": person,
                        "collected": collected,
                        "memo": memo,
                    }
                )
                load_card_history.clear()
                st.success("保存しました。")
                st.rerun()
            except Exception as exc:
                st.error(f"保存できませんでした: {exc}")


def card_select_options(series: pd.Series, presets: list[str], current: str) -> list[str]:
    values = [str(value).strip() for value in series.dropna().unique()]
    options: list[str] = []
    for value in [current, *presets, *values]:
        if value not in options:
            options.append(value)
    return options or [current]


def page_card_category_summary(df: pd.DataFrame) -> None:
    st.markdown("#### 分類別")
    if df.empty:
        st.info("集計できる明細がありません。")
        return
    grouped = (
        df.groupby("大分類", dropna=False)
        .agg(金額=("金額", "sum"), 自分負担額=("自分負担額", "sum"), 件数=("金額", "count"))
        .reset_index()
        .sort_values("自分負担額", ascending=False)
    )
    for _, row in grouped.iterrows():
        st.markdown(
            f"""
            <div class="money-table-row">
              <div><div class="label">{escape(str(row['大分類']))}</div><div class="sub">{int(row['件数'])}件 / 合計 {card_money(row['金額'])}</div></div>
              <div class="value">{card_money(row['自分負担額'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def page_card_handling_summary(df: pd.DataFrame) -> None:
    st.markdown("#### 扱い別")
    if df.empty:
        st.info("集計できる明細がありません。")
        return
    grouped = (
        df.groupby("扱い", dropna=False)
        .agg(金額=("金額", "sum"), 自分負担額=("自分負担額", "sum"), 相手負担額=("相手負担額", "sum"), 件数=("金額", "count"))
        .reset_index()
    )
    order = {name: index for index, name in enumerate(["自分の支出", "割り勘", "立替", "お使い", "不明"])}
    grouped["order"] = grouped["扱い"].map(lambda value: order.get(str(value), 99))
    grouped = grouped.sort_values(["order", "扱い"])
    for _, row in grouped.iterrows():
        st.markdown(
            f"""
            <div class="money-table-row">
              <div><div class="label">{handling_badge(str(row['扱い']))}</div><div class="sub">{int(row['件数'])}件 / 相手負担 {card_money(row['相手負担額'])}</div></div>
              <div class="value">{card_money(row['自分負担額'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def page_upload() -> None:
    st.markdown("<div class='app-title'>スクリーンショットをアップロード</div>", unsafe_allow_html=True)
    tesseract_ready = find_tesseract_executable() is not None
    openai_ready = bool(os.getenv("OPENAI_API_KEY"))
    if not tesseract_ready and not openai_ready:
        st.warning("画像解析エンジンが未設定です。OpenAI Vision用のAPIキーを設定するか、Tesseract本体をインストールしてください。")
    elif openai_ready:
        st.info("OpenAI Vision が利用可能です。複雑なスマホ画面は OpenAI Vision 推奨です。")
    elif tesseract_ready:
        st.info("pytesseract が利用可能です。読み取りが弱い場合は OpenAI Vision を使ってください。")

    st.markdown("<div class='upload-box'>", unsafe_allow_html=True)
    uploaded = st.file_uploader("画像を選択する", type=["png", "jpg", "jpeg"], label_visibility="collapsed")
    engines = ["OpenAI Vision", "pytesseract"] if os.getenv("OPENAI_API_KEY") else ["pytesseract", "OpenAI Vision"]
    engine = st.radio("OCR方式", engines, horizontal=True)
    st.caption("対応形式: PNG / JPG / JPEG")
    st.markdown("</div>", unsafe_allow_html=True)

    if uploaded:
        upload_signature = f"{uploaded.name}:{uploaded.size}:{engine}"
        if st.session_state.get("last_upload_signature") != upload_signature:
            filename, image_path = save_uploaded_image(uploaded)
            ocr_text = run_ocr(image_path, engine)
            used_engine = engine
            if is_ocr_error(ocr_text) and engine == "pytesseract" and os.getenv("OPENAI_API_KEY"):
                ocr_text = run_openai_vision(image_path)
                used_engine = "OpenAI Vision"
            extracted = extract_point_fields(ocr_text, filename)
            st.session_state["pending_image"] = {"filename": filename, "path": str(image_path)}
            st.session_state["ocr_text"] = ocr_text
            st.session_state["extracted"] = extracted
            st.session_state["last_upload_signature"] = upload_signature
            st.session_state["last_ocr_engine"] = used_engine

        pending_image = st.session_state.get("pending_image", {})
        ocr_text = st.session_state.get("ocr_text", "")
        if is_ocr_error(ocr_text):
            st.error("OCRに失敗したため、自動入力できませんでした。Tesseract本体を入れるか、OPENAI_API_KEYを設定してOpenAI Visionを選んでください。")
        else:
            st.success(f"{st.session_state.get('last_ocr_engine', engine)} で読み取り、確認フォームへ自動入力しました。")
            extracted = st.session_state.get("extracted", {})
            if extracted:
                st.caption(
                    f"解析結果: {extracted.get('service_name', 'その他')} / "
                    f"{int(extracted.get('total_points') or 0):,} pt / "
                    f"期間限定 {int(extracted.get('limited_points') or 0):,} pt"
                )
        image_path = Path(pending_image.get("path", ""))
        st.image(str(image_path), use_container_width=True)

    page_review()

    st.markdown("#### アップロード履歴")
    history = load_records().head(8)
    if history.empty:
        st.caption("保存済み画像はまだありません。")
    for _, row in history.iterrows():
        cols = st.columns([1, 2, 1])
        with cols[0]:
            if row["image_path"] and Path(row["image_path"]).exists():
                st.image(row["image_path"], width=88)
        with cols[1]:
            st.write(f"**{row['service_name']}**")
            st.caption(f"{row['image_filename'] or '-'} / {row['updated_at']}")
        with cols[2]:
            if st.button("削除", key=f"delete-upload-{row['id']}"):
                delete_record(int(row["id"]))
                st.rerun()


def page_review() -> None:
    st.markdown("#### OCR結果の確認・修正")
    pending = st.session_state.get("pending_image")
    extracted = st.session_state.get("extracted", {})
    ocr_text = st.session_state.get("ocr_text", "")

    if not pending:
        st.caption("画像をアップロードすると確認フォームが表示されます。")
        return

    with st.expander("読み取ったテキスト", expanded=False):
        st.text_area("OCRテキスト", value=ocr_text, height=160, key="ocr_text_editor")
        if st.button("このテキストから再入力", use_container_width=True):
            st.session_state["ocr_text"] = st.session_state.get("ocr_text_editor", ocr_text)
            st.session_state["extracted"] = extract_point_fields(st.session_state["ocr_text"], pending["filename"])
            st.rerun()

    col_reparse, col_revision = st.columns(2)
    with col_reparse:
        if st.button("画像を再解析", use_container_width=True):
            image_path = Path(pending["path"])
            engine = "OpenAI Vision" if os.getenv("OPENAI_API_KEY") else "pytesseract"
            ocr_text = run_ocr(image_path, engine)
            st.session_state["ocr_text"] = ocr_text
            st.session_state["extracted"] = extract_point_fields(ocr_text, pending["filename"])
            st.session_state["last_ocr_engine"] = engine
            st.rerun()
    with col_revision:
        st.caption(f"使用エンジン: {st.session_state.get('last_ocr_engine', '-')}")

    if is_ocr_error(ocr_text):
        st.warning(
            "OCRエンジンが動いていないため、下のフォームは初期値のままです。"
            "Windowsでは `winget install UB-Mannheim.TesseractOCR` の実行後、アプリを再起動してください。"
        )
    elif not has_meaningful_extraction(extracted):
        st.warning("画像解析結果からポイント残高を特定できませんでした。OCRテキストを確認するか、OpenAI Visionで再解析してください。")

    with st.form("point_review_form"):
        service = st.selectbox("サービス名", SERVICE_NAMES, index=SERVICE_NAMES.index(extracted.get("service_name", "その他")))
        total_points = st.number_input("ポイント残高", min_value=0, step=1, value=int(extracted.get("total_points", 0)))
        normal_points = st.number_input("通常ポイント", min_value=0, step=1, value=int(extracted.get("normal_points", 0)))
        limited_points = st.number_input("期間限定ポイント", min_value=0, step=1, value=int(extracted.get("limited_points", 0)))
        exp_value = parse_iso_date(extracted.get("expiration_date"))
        upd_value = parse_iso_date(extracted.get("updated_at")) or date.today()
        expiration_date = st.date_input("有効期限", value=exp_value, format="YYYY/MM/DD")
        no_expiration = st.checkbox("有効期限なし・不明", value=exp_value is None)
        updated_at = st.date_input("最終更新日", value=upd_value, format="YYYY/MM/DD")
        memo = st.text_area("メモ", value=extracted.get("memo", ""), placeholder="任意で入力できます")
        submitted = st.form_submit_button("保存する", type="primary", use_container_width=True)

    if submitted:
        save_record(
            {
                "service_name": service,
                "total_points": total_points,
                "normal_points": normal_points,
                "limited_points": limited_points,
                "expiration_date": "" if no_expiration else expiration_date.isoformat(),
                "updated_at": updated_at.isoformat(),
                "image_filename": pending["filename"],
                "image_path": pending["path"],
                "memo": memo,
                "ocr_text": st.session_state.get("ocr_text_editor", ocr_text),
            }
        )
        st.session_state.pop("pending_image", None)
        st.session_state.pop("ocr_text", None)
        st.session_state.pop("extracted", None)
        st.success("SQLiteに保存しました。")
        st.rerun()


def page_points() -> None:
    st.markdown("<div class='app-title'>ポイント一覧</div>", unsafe_allow_html=True)
    df = load_latest_by_service()
    if df.empty:
        st.info("保存されたポイントがありません。")
        return

    view = df[["service_name", "normal_points", "limited_points", "total_points", "expiration_date", "updated_at"]].copy()
    view.columns = ["サービス名", "通常", "期間限定", "残高", "有効期限", "最終更新日"]
    st.dataframe(view, use_container_width=True, hide_index=True)
    st.markdown(f"<div class='hero'><div class='label'>合計（円換算）</div><div class='amount'>¥{int(round(yen_total(df))):,}</div></div>", unsafe_allow_html=True)


def page_expiring() -> None:
    st.markdown("<div class='app-title'>失効予定のポイント</div>", unsafe_allow_html=True)
    expiring = expiration_df(load_latest_by_service())
    if expiring.empty:
        st.success("30日以内に失効する期間限定ポイントは登録されていません。")
        return

    total = int(expiring["limited_points"].sum())
    st.markdown(f"<div class='card danger'>30日以内に {total:,} pt が失効します</div>", unsafe_allow_html=True)
    for _, row in expiring.iterrows():
        st.markdown(
            f"""
            <div class="card row">
              <div class="service">
                {service_badge(row['service_name'])}
                <div>
                  <div class="name">{row['service_name']}（期間限定）</div>
                  <div class="sub">有効期限: {row['expiration_date']}</div>
                </div>
              </div>
              <div><div class="points">{int(row['limited_points']):,} pt</div><div class="danger">あと{int(row['days_left'])}日</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div class='tip'>期限限定ポイントは少額でも早めに使い切ると失効を防げます。</div>", unsafe_allow_html=True)


def page_ai_memo() -> None:
    st.markdown("<div class='app-title'>AI交換提案メモ</div>", unsafe_allow_html=True)
    latest = load_latest_by_service()
    expiring = expiration_df(latest)
    summary = make_ai_summary(latest, expiring)

    st.markdown(
        "<div class='hero'><div class='label'>あなたへのおすすめ交換プラン</div><div style='font-weight:800;margin-top:8px;'>失効予定と残高から判断するためのメモ</div></div>",
        unsafe_allow_html=True,
    )
    st.text_area("AI用の要約テキスト", value=summary, height=220)

    st.markdown("#### おすすめプラン")
    for suggestion in make_exchange_suggestions(latest, expiring):
        st.markdown(
            f"<div class='card'><div class='name'>{suggestion['title']}</div><div class='sub'>{suggestion['body']}</div></div>",
            unsafe_allow_html=True,
        )


def show_trend_chart(df: pd.DataFrame) -> None:
    if df.empty:
        return
    chart_df = df.copy()
    chart_df["month"] = pd.to_datetime(chart_df["updated_at"], errors="coerce").dt.strftime("%Y-%m")
    chart_df = chart_df.dropna(subset=["month"])
    if chart_df.empty:
        return
    monthly = chart_df.groupby(["month", "service_name"], as_index=False)["total_points"].sum()
    chart = (
        alt.Chart(monthly)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:N", title="月"),
            y=alt.Y("total_points:Q", title="ポイント"),
            color=alt.Color("service_name:N", title="サービス"),
            tooltip=["month", "service_name", "total_points"],
        )
        .properties(height=240)
    )
    st.markdown("#### サービス別・月別の推移")
    st.altair_chart(chart, use_container_width=True)


def app_nav() -> str:
    labels = ["家計簿", "ポイント", "追加", "一覧", "失効", "AI"]
    page_map = {
        "家計簿": "カード家計簿",
        "ポイント": "ホーム",
        "追加": "アップロード",
        "一覧": "ポイント一覧",
        "失効": "失効予定",
        "AI": "AI提案",
    }
    st.markdown("<div class='nav-card'>", unsafe_allow_html=True)
    if hasattr(st, "segmented_control"):
        selected = st.segmented_control("Navigation", labels, default="家計簿", label_visibility="collapsed")
    else:
        selected = st.radio("Navigation", labels, horizontal=True, label_visibility="collapsed")
    st.markdown("</div>", unsafe_allow_html=True)
    return page_map[selected or "家計簿"]


def main() -> None:
    st.set_page_config(page_title="お金管理", page_icon="💠", layout="centered")
    require_app_password()
    init_storage()
    css()

    page = app_nav()
    if page == "カード家計簿":
        page_card_budget()
    elif page == "ホーム":
        page_dashboard()
    elif page == "アップロード":
        page_upload()
    elif page == "ポイント一覧":
        page_points()
    elif page == "失効予定":
        page_expiring()
    elif page == "AI提案":
        page_ai_memo()


if __name__ == "__main__":
    main()
