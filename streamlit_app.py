import csv
import io
import json
import re
import time
from html import escape

import requests
import streamlit as st
from bs4 import BeautifulSoup, NavigableString


st.set_page_config(page_title="Shopify CSV Translator", page_icon="CSV", layout="wide")

TRANSLATABLE_COLUMNS = {
    "title",
    "body (html)",
    "body html",
    "body",
    "description",
    "content",
    "seo title",
    "seo description",
    "meta title",
    "meta description",
    "page title",
    "page description",
    "option1 value",
    "option2 value",
    "option3 value",
}

NEVER_TRANSLATE_COLUMNS = {
    "handle",
    "id",
    "variant sku",
    "sku",
    "vendor",
    "type",
    "tags",
    "published",
    "status",
    "image src",
    "image alt text",
    "gift card",
    "variant barcode",
    "variant price",
    "variant compare at price",
    "variant inventory qty",
    "variant inventory tracker",
    "variant inventory policy",
    "variant fulfillment service",
    "variant requires shipping",
    "variant taxable",
    "variant grams",
    "variant weight unit",
    "product category",
    "google shopping / google product category",
    "google shopping / gender",
    "google shopping / age group",
    "google shopping / condition",
    "google shopping / custom product",
}

LANGUAGE_CODES = {
    "english": "en", "英文": "en", "japanese": "ja", "日文": "ja", "日语": "ja",
    "chinese": "zh-CN", "中文": "zh-CN", "简体中文": "zh-CN",
    "traditional chinese": "zh-TW", "繁体中文": "zh-TW", "korean": "ko", "韩文": "ko", "韩语": "ko",
    "german": "de", "德文": "de", "德语": "de", "french": "fr", "法文": "fr", "法语": "fr",
    "spanish": "es", "西班牙文": "es", "西班牙语": "es", "italian": "it", "意大利文": "it", "意大利语": "it",
    "portuguese": "pt", "葡萄牙文": "pt", "葡萄牙语": "pt", "dutch": "nl", "荷兰文": "nl", "荷兰语": "nl",
    "swedish": "sv", "瑞典文": "sv", "norwegian": "no", "挪威文": "no", "danish": "da", "丹麦文": "da",
    "finnish": "fi", "芬兰文": "fi", "polish": "pl", "波兰文": "pl", "czech": "cs", "捷克文": "cs",
    "hungarian": "hu", "匈牙利文": "hu", "匈牙利语": "hu", "romanian": "ro", "罗马尼亚文": "ro",
    "bulgarian": "bg", "保加利亚文": "bg", "greek": "el", "希腊文": "el", "turkish": "tr", "土耳其文": "tr",
    "russian": "ru", "俄文": "ru", "俄语": "ru", "ukrainian": "uk", "乌克兰文": "uk",
    "arabic": "ar", "阿拉伯文": "ar", "thai": "th", "泰文": "th", "vietnamese": "vi", "越南文": "vi",
    "indonesian": "id", "印尼文": "id", "malay": "ms", "马来文": "ms",
}


def secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def require_password():
    password = secret("APP_PASSWORD", "")
    if not password:
        return True
    entered = st.text_input("访问密码", type="password")
    if entered == password:
        return True
    st.stop()


def parse_csv(uploaded_file):
    raw = uploaded_file.getvalue()
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    rows = []
    for row in reader:
        rows.append({header: row.get(header, "") for header in headers})
    return headers, rows


def serialize_csv(headers, rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + output.getvalue()).encode("utf-8-sig")


def normalized(header):
    return header.lower().strip()


def has_column(headers, name):
    return any(normalized(header) == name.lower() for header in headers)


def is_translate_adapt_csv(headers):
    return has_column(headers, "Default content") and has_column(headers, "Translated content")


def is_translatable_column(header):
    name = normalized(header)
    if name in NEVER_TRANSLATE_COLUMNS:
        return False
    if name in TRANSLATABLE_COLUMNS:
        return True
    if name.startswith("seo ") and "description" in name:
        return True
    if name.startswith("metafield") and re.search(r"title|description|content|text", header, re.I):
        return True
    return False


def is_html_column(header):
    return normalized(header) in {"body (html)", "body html", "body"}


def detect_plan(headers):
    if is_translate_adapt_csv(headers):
        return [{"source": "Default content", "target": "Translated content", "in_place": False}]
    return [
        {"source": header, "target": header, "in_place": True}
        for header in headers
        if is_translatable_column(header)
    ]


def looks_non_translatable(text):
    value = text.strip()
    if not value:
        return True
    if re.match(r"^https?://", value, re.I):
        return True
    if re.match(r"^[\w-]+/[\w-/]+$", value):
        return True
    if re.match(r"^[\d\s.,:%+$€£¥()-]+$", value):
        return True
    if re.match(r"^[A-Z0-9_-]{2,}$", value):
        return True
    return False


def preserve_padding(original, translation):
    leading = re.match(r"^\s*", original).group(0)
    trailing = re.search(r"\s*$", original).group(0)
    return f"{leading}{translation.strip()}{trailing}"


def make_html_items(row, row_index, column):
    html = row.get(column["source"], "")
    if not html.strip():
        return [], None
    soup = BeautifulSoup(html, "html.parser")
    nodes = []
    for node in soup.find_all(string=True):
        parent = (node.parent.name or "").lower() if node.parent else ""
        if parent in {"script", "style", "noscript", "svg"}:
            continue
        if looks_non_translatable(str(node)):
            continue
        nodes.append(node)
    items = []
    html_key = f"{row_index}:{column['target']}"
    for index, node in enumerate(nodes):
        items.append({
            "id": f"{html_key}:html:{index}",
            "text": str(node),
            "row_index": row_index,
            "source_column": column["source"],
            "target_column": column["target"],
            "mode": "html",
            "html_key": html_key,
            "segment_index": index,
        })
    return items, {"soup": soup, "nodes": nodes, "row_index": row_index, "target_column": column["target"]}


def make_work_items(headers, rows, empty_only=True, skip_machine_text=True):
    plan = detect_plan(headers)
    html_cells = {}
    items = []
    for row_index, row in enumerate(rows):
        for column in plan:
            if is_html_column(column["source"]):
                html_items, html_cell = make_html_items(row, row_index, column)
                if html_cell and html_items:
                    html_cells[html_items[0]["html_key"]] = html_cell
                items.extend(html_items)
                continue
            text = row.get(column["source"], "")
            target = row.get(column["target"], "")
            if not text.strip():
                continue
            if not column["in_place"] and empty_only and target.strip():
                continue
            if skip_machine_text and looks_non_translatable(text):
                continue
            items.append({
                "id": f"{row_index}:{column['target']}",
                "text": text,
                "row_index": row_index,
                "source_column": column["source"],
                "target_column": column["target"],
                "mode": "cell",
            })
    return items, html_cells


def resolve_language_code(language):
    raw = language.strip()
    if re.match(r"^[a-z]{2,3}(-[A-Z]{2})?$", raw):
        return raw
    lower = raw.lower()
    for name, code in LANGUAGE_CODES.items():
        if name.lower() in lower:
            return code
    return "en"


def parse_json_payload(raw):
    try:
        return json.loads(raw)
    except Exception:
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.I)
        if fenced:
            return parse_json_payload(fenced.group(1))
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
        raise ValueError("翻译接口返回的内容不是 JSON。")


def normalize_translation_array(parsed):
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        return parsed["items"]
    if isinstance(parsed, dict) and isinstance(parsed.get("translations"), list):
        return parsed["translations"]
    raise ValueError("翻译接口没有返回译文数组。")


def chat_provider_defaults(provider):
    if provider == "千问 Qwen":
        return "qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if provider == "DeepSeek":
        return "deepseek-v4-flash", "https://api.deepseek.com"
    return "gpt-5.6", "https://api.openai.com/v1"


def provider_key(provider, manual_key):
    if manual_key:
        return manual_key
    if provider == "千问 Qwen":
        return secret("DASHSCOPE_API_KEY", "")
    if provider == "DeepSeek":
        return secret("DEEPSEEK_API_KEY", "")
    if provider == "OpenAI":
        return secret("OPENAI_API_KEY", "")
    return ""


def extract_openai_output_text(data):
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def translate_with_openai(api_key, model, base_url, source_language, target_language, glossary, items):
    if not api_key:
        raise RuntimeError("缺少 OpenAI API Key：请在左侧填写，或在 Streamlit Secrets 里保存。")
    url = base_url.rstrip("/")
    if not url.endswith("/responses"):
        url = f"{url}/responses"
    instructions = (
        "You are a professional ecommerce localization translator for Shopify stores. "
        "Translate source text into the target language naturally for shoppers. "
        "Preserve HTML tags, attributes, URLs, Liquid syntax such as {{ value }} and {% tag %}, "
        "SKU-like codes, measurements, and brand names. Do not add explanations. "
        'Return only a JSON array. Each item must be {"id":"same id","translation":"translated text"}.'
    )
    body = {
        "model": model,
        "instructions": instructions,
        "input": json.dumps({
            "sourceLanguage": source_language or "auto",
            "targetLanguage": target_language,
            "glossary": glossary or "",
            "items": [{"id": item["id"], "text": item["text"]} for item in items],
        }, ensure_ascii=False),
    }
    response = requests.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body, timeout=180)
    data = response.json() if response.content else {}
    if response.status_code >= 400:
        message = data.get("error", {}).get("message") if isinstance(data.get("error"), dict) else data.get("error")
        raise RuntimeError(message or f"接口返回 HTTP {response.status_code}")
    parsed = normalize_translation_array(parse_json_payload(extract_openai_output_text(data)))
    return {item["id"]: item.get("translation", "") for item in parsed if isinstance(item, dict)}


def translate_with_chat_api(provider, api_key, model, base_url, source_language, target_language, glossary, items):
    if not api_key:
        raise RuntimeError("缺少 API Key：请在左侧填写，或在 Streamlit Secrets 里保存。")
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url = f"{url}/chat/completions"
    system = (
        "You are a professional ecommerce localization translator for Shopify stores. "
        "Translate source text into the target language naturally for shoppers. "
        "Preserve HTML tags, attributes, URLs, Liquid syntax such as {{ value }} and {% tag %}, "
        "SKU-like codes, measurements, and brand names. Do not add explanations. "
        'Return only JSON in this shape: {"items":[{"id":"same id","translation":"translated text"}]}.'
    )
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({
                "sourceLanguage": source_language or "auto",
                "targetLanguage": target_language,
                "glossary": glossary or "",
                "items": [{"id": item["id"], "text": item["text"]} for item in items],
            }, ensure_ascii=False)},
        ],
        "temperature": 0.1,
    }
    if provider == "DeepSeek" and model.startswith("deepseek-v4"):
        body["thinking"] = {"type": "disabled"}
    response = requests.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body, timeout=180)
    data = response.json() if response.content else {}
    if response.status_code >= 400:
        message = data.get("error", {}).get("message") if isinstance(data.get("error"), dict) else data.get("error")
        raise RuntimeError(message or f"接口返回 HTTP {response.status_code}")
    raw = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    parsed = normalize_translation_array(parse_json_payload(raw))
    return {item["id"]: item.get("translation", "") for item in parsed if isinstance(item, dict)}


def translate_with_free_service(target_language, items):
    target_code = resolve_language_code(target_language)
    translations = {}
    for item in items:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "auto", "tl": target_code, "dt": "t", "q": item["text"]}
        response = requests.get(url, params=params, timeout=60)
        try:
            data = response.json()
            translations[item["id"]] = "".join(part[0] for part in data[0] if part and part[0])
        except Exception as exc:
            raise RuntimeError("免费翻译失败或被限制，请改用 Qwen / DeepSeek / OpenAI。") from exc
    return translations


def apply_translation(rows, html_cells, item, translation):
    if not translation or not translation.strip():
        return False
    if item["mode"] == "html":
        html_cell = html_cells.get(item["html_key"])
        if not html_cell:
            return False
        node = html_cell["nodes"][item["segment_index"]]
        node.replace_with(NavigableString(preserve_padding(str(node), translation)))
        rows[html_cell["row_index"]][html_cell["target_column"]] = str(html_cell["soup"])
        return True
    row_index = item["row_index"]
    target_column = item["target_column"]
    if row_index < 0 or row_index >= len(rows):
        return False
    rows[row_index][target_column] = translation
    return True


def slug(text):
    value = re.sub(r'[\\/:*?"<>|]+', "", text.strip().lower())
    return re.sub(r"\s+", "-", value) or "translated"


require_password()

st.title("Shopify CSV 一键翻译")
st.caption("上传 CSV，选择语言，翻译后下载 Shopify 可导入的 CSV。")

with st.sidebar:
    provider = st.selectbox("翻译接口", ["千问 Qwen", "DeepSeek", "OpenAI", "免费翻译"])
    default_model, default_base_url = chat_provider_defaults(provider)
    target_language = st.text_input("目标语言", value="Japanese")
    source_language = st.text_input("源语言", value="auto")
    model = st.text_input("模型", value=default_model, disabled=provider == "免费翻译")
    base_url = st.text_input("API 地址", value=default_base_url, disabled=provider == "免费翻译")
    manual_key = st.text_input("API Key", type="password", help="部署后建议放到 Streamlit Secrets。")
    empty_only = st.checkbox("只翻译目标列为空的行", value=True)
    skip_machine_text = st.checkbox("跳过链接、数字、短代码", value=True)
    glossary = st.text_area("术语表 / 品牌词", value="", height=100)

uploaded = st.file_uploader("放入 Shopify CSV", type=["csv"])

if not uploaded:
    st.info("请先上传 Shopify 导出的 CSV 文件。")
    st.stop()

headers, rows = parse_csv(uploaded)
plan = detect_plan(headers)
items, html_cells = make_work_items(headers, rows, empty_only, skip_machine_text)

left, right = st.columns([2, 1])
with left:
    st.subheader("预览")
    st.dataframe(rows[:50], use_container_width=True, height=420)
with right:
    st.subheader("识别结果")
    st.write(f"文件：`{escape(uploaded.name)}`")
    st.write(f"行数：`{len(rows)}`")
    st.write(f"列数：`{len(headers)}`")
    st.write(f"待翻译：`{len(items)}`")
    st.write("列：")
    for column in plan:
        st.code(f"{column['source']} -> {column['target']}", language=None)

if "translated_csv" not in st.session_state:
    st.session_state.translated_csv = None
if "translated_name" not in st.session_state:
    st.session_state.translated_name = None

if st.button("开始翻译", type="primary", disabled=not items):
    progress = st.progress(0)
    status = st.empty()
    logs = st.container()
    completed = 0
    try:
        for start in range(0, len(items), 10):
            batch = items[start : start + 10]
            if provider == "免费翻译":
                translations = translate_with_free_service(target_language, batch)
            elif provider == "OpenAI":
                translations = translate_with_openai(provider_key(provider, manual_key), model, base_url, source_language, target_language, glossary, batch)
            else:
                translations = translate_with_chat_api(provider, provider_key(provider, manual_key), model, base_url, source_language, target_language, glossary, batch)
            for item in batch:
                if apply_translation(rows, html_cells, item, translations.get(item["id"], "")):
                    completed += 1
            progress.progress(completed / max(len(items), 1))
            status.write(f"已完成 {completed} / {len(items)}")
            time.sleep(0.05)
        base_name = re.sub(r"\.csv$", "", uploaded.name, flags=re.I)
        st.session_state.translated_name = f"{base_name}-{slug(target_language)}-shopify.csv"
        st.session_state.translated_csv = serialize_csv(headers, rows)
        logs.success("翻译完成，可以下载 CSV。")
    except Exception as exc:
        st.error(str(exc))

if st.session_state.translated_csv:
    st.download_button("下载翻译后的 CSV", data=st.session_state.translated_csv, file_name=st.session_state.translated_name, mime="text/csv")
