import csv
import io
import json
import re
import time

import requests
import streamlit as st

st.set_page_config(page_title="Shopify CSV Translator", page_icon="CSV", layout="wide")

LANGUAGE_OPTIONS = [
    "日语 Japanese", "韩语 Korean", "英语 English", "德语 German", "法语 French",
    "西班牙语 Spanish", "意大利语 Italian", "葡萄牙语 Portuguese", "荷兰语 Dutch",
    "瑞典语 Swedish", "挪威语 Norwegian", "丹麦语 Danish", "芬兰语 Finnish",
    "波兰语 Polish", "捷克语 Czech", "匈牙利语 Hungarian", "罗马尼亚语 Romanian",
    "保加利亚语 Bulgarian", "希腊语 Greek", "土耳其语 Turkish", "俄语 Russian",
    "乌克兰语 Ukrainian", "阿拉伯语 Arabic", "希伯来语 Hebrew", "印地语 Hindi",
    "泰语 Thai", "越南语 Vietnamese", "印尼语 Indonesian", "马来语 Malay",
    "菲律宾语 Filipino", "简体中文 Simplified Chinese", "繁体中文 Traditional Chinese",
]

LANGUAGE_CODES = {
    "english": "en", "英语": "en", "japanese": "ja", "日语": "ja", "日文": "ja",
    "korean": "ko", "韩语": "ko", "german": "de", "德语": "de", "french": "fr", "法语": "fr",
    "spanish": "es", "西班牙语": "es", "italian": "it", "意大利语": "it",
    "portuguese": "pt", "葡萄牙语": "pt", "dutch": "nl", "荷兰语": "nl",
    "swedish": "sv", "norwegian": "no", "danish": "da", "finnish": "fi", "polish": "pl",
    "czech": "cs", "hungarian": "hu", "匈牙利语": "hu", "romanian": "ro", "bulgarian": "bg",
    "greek": "el", "turkish": "tr", "russian": "ru", "俄语": "ru", "ukrainian": "uk",
    "arabic": "ar", "阿拉伯语": "ar", "hebrew": "iw", "hindi": "hi", "thai": "th", "泰语": "th",
    "vietnamese": "vi", "越南语": "vi", "indonesian": "id", "malay": "ms", "filipino": "tl",
    "simplified chinese": "zh-CN", "简体中文": "zh-CN", "traditional chinese": "zh-TW", "繁体中文": "zh-TW",
}

TRANSLATABLE_COLUMNS = {
    "title", "body (html)", "body html", "body", "description", "content", "seo title",
    "seo description", "meta title", "meta description", "page title", "page description",
    "option1 value", "option2 value", "option3 value",
}

NEVER_TRANSLATE_COLUMNS = {
    "handle", "id", "variant sku", "sku", "vendor", "type", "tags", "published", "status",
    "image src", "image alt text", "gift card", "variant barcode", "variant price",
    "image", "image position", "variant image", "media", "media src", "media image",
    "media image url", "media image src", "media preview image", "media content type",
    "media host", "external video url", "model 3d source", "video source",
    "variant compare at price", "variant inventory qty", "variant inventory tracker",
    "variant inventory policy", "variant fulfillment service", "variant requires shipping",
    "variant taxable", "variant grams", "variant weight unit", "product category",
    "google shopping / google product category", "google shopping / gender",
    "google shopping / age group", "google shopping / condition", "google shopping / custom product",
}


def get_secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def parse_csv(uploaded_file):
    text = uploaded_file.getvalue().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    rows = [{header: row.get(header, "") for header in headers} for row in reader]
    return headers, rows


def serialize_csv(headers, rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + output.getvalue()).encode("utf-8-sig")


def norm(header):
    return str(header).lower().strip()


def has_column(headers, name):
    return any(norm(header) == name.lower() for header in headers)


def is_translate_adapt(headers):
    return has_column(headers, "Default content") and has_column(headers, "Translated content")


def is_translatable_column(header):
    name = norm(header)
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
    return norm(header) in {"body (html)", "body html", "body"}


def is_media_column(header):
    name = norm(header)
    return any(word in name for word in ("image", "media", "thumbnail", "video", "model 3d")) or name in {
        "src", "url", "preview",
    }


def detect_plan(headers):
    if is_translate_adapt(headers):
        return [{"source": "Default content", "target": "Translated content", "in_place": False}]
    return [{"source": h, "target": h, "in_place": True} for h in headers if is_translatable_column(h)]


def looks_non_translatable(text):
    value = str(text).strip()
    if not value:
        return True
    if looks_media_value(value):
        return True
    if re.match(r"^https?://", value, re.I):
        return True
    if re.match(r"^[\w-]+/[\w/-]+$", value):
        return True
    if re.match(r"^[\d\s.,:%+$€£¥()-]+$", value):
        return True
    if re.match(r"^[A-Z0-9_-]{2,}$", value):
        return True
    return False


def looks_media_value(text):
    value = str(text).strip()
    if not value:
        return False
    lower = value.lower()
    media_ext = r"\.(?:jpe?g|png|gif|webp|svg|avif|bmp|tiff?|mp4|mov|webm|m4v|glb|gltf)(?:[?#].*)?$"
    if "cdn.shopify.com" in lower or "/cdn/shop/" in lower or "shopifycdn.net" in lower:
        return True
    if re.search(media_ext, lower):
        return True
    if re.match(r"^(?:https?:)?//", lower) and any(token in lower for token in ("/image", "/media", "/files/", "/videos/")):
        return True
    if lower.startswith(("<img", "<picture", "<video", "<source")):
        return True
    if lower.startswith(("{", "[")) and any(token in lower for token in ("image", "media", "src", "url", "preview_image")):
        return True
    parts = [part.strip() for part in re.split(r"[,|;\n]+", lower) if part.strip()]
    if len(parts) > 1 and all(looks_media_value(part) for part in parts):
        return True
    return False


def row_mentions_media(row):
    for key, value in row.items():
        key_text = norm(key)
        value_text = str(value).lower()
        if key_text in {"field", "key", "name", "type", "content type", "resource type"}:
            if any(word in value_text for word in ("image", "media", "video", "thumbnail", "src", "url")):
                return True
    return False


def preserve_padding(original, translated):
    leading = re.match(r"^\s*", str(original)).group(0)
    trailing = re.search(r"\s*$", str(original)).group(0)
    return f"{leading}{str(translated).strip()}{trailing}"


def html_text_segments(html):
    segments = []
    pos = 0
    muted_depth = 0
    muted_tags = {"script", "style", "noscript", "svg"}

    for match in re.finditer(r"<[^>]*>", html):
        if muted_depth == 0 and match.start() > pos:
            text = html[pos:match.start()]
            if not looks_non_translatable(text):
                segments.append({"start": pos, "end": match.start(), "text": text})

        tag = match.group(0)
        tag_name_match = re.match(r"</?\s*([a-zA-Z0-9:-]+)", tag)
        if tag_name_match:
            tag_name = tag_name_match.group(1).lower()
            if tag_name in muted_tags:
                if tag.startswith("</"):
                    muted_depth = max(0, muted_depth - 1)
                elif not tag.endswith("/>"):
                    muted_depth += 1
        pos = match.end()

    if muted_depth == 0 and pos < len(html):
        text = html[pos:]
        if not looks_non_translatable(text):
            segments.append({"start": pos, "end": len(html), "text": text})
    return segments


def rebuild_html(original, segments, translations):
    output = []
    pos = 0
    for index, segment in enumerate(segments):
        output.append(original[pos:segment["start"]])
        output.append(translations.get(index, segment["text"]))
        pos = segment["end"]
    output.append(original[pos:])
    return "".join(output)


def make_html_items(row, row_index, column):
    html = row.get(column["source"], "")
    if not html.strip():
        return [], None
    segments = html_text_segments(html)
    key = f"{row_index}:{column['target']}"
    items = []
    for index, segment in enumerate(segments):
        items.append({
            "id": f"{key}:html:{index}", "text": segment["text"], "mode": "html", "html_key": key,
            "segment_index": index, "row_index": row_index, "target_column": column["target"],
            "source_column": column["source"],
        })
    return items, {
        "original": html,
        "segments": segments,
        "translations": {},
        "row_index": row_index,
        "target_column": column["target"],
    }


def make_items(headers, rows, empty_only, skip_machine_text):
    items, html_cells = [], {}
    for row_index, row in enumerate(rows):
        for column in detect_plan(headers):
            if is_media_column(column["source"]) or is_media_column(column["target"]):
                continue
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
            if looks_media_value(text) or (row_mentions_media(row) and looks_media_value(text)):
                continue
            if not column["in_place"] and empty_only and target.strip():
                continue
            if skip_machine_text and looks_non_translatable(text):
                continue
            items.append({
                "id": f"{row_index}:{column['target']}", "text": text, "mode": "cell",
                "row_index": row_index, "target_column": column["target"], "source_column": column["source"],
            })
    return items, html_cells


def language_code(language):
    raw = str(language).strip()
    if re.match(r"^[a-z]{2,3}(-[A-Z]{2})?$", raw):
        return raw
    lower = raw.lower()
    for name, code in LANGUAGE_CODES.items():
        if name.lower() in lower:
            return code
    return "en"


def parse_json(raw):
    try:
        return json.loads(raw)
    except Exception:
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.I)
        if fenced:
            return parse_json(fenced.group(1))
        for left, right in [("[", "]"), ("{", "}")]:
            start, end = raw.find(left), raw.rfind(right)
            if start >= 0 and end > start:
                return json.loads(raw[start:end + 1])
    raise RuntimeError("翻译接口返回的内容不是 JSON。")


def normalize_translations(parsed):
    if isinstance(parsed, list):
        records = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        records = parsed["items"]
    elif isinstance(parsed, dict) and isinstance(parsed.get("translations"), list):
        records = parsed["translations"]
    else:
        raise RuntimeError("翻译接口没有返回译文数组。")
    return {x["id"]: x.get("translation", "") for x in records if isinstance(x, dict) and "id" in x}


def provider_defaults(provider):
    if provider == "千问 Qwen":
        return "qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"
    if provider == "DeepSeek":
        return "deepseek-v4-flash", "https://api.deepseek.com", "DEEPSEEK_API_KEY"
    return "gpt-5.6", "https://api.openai.com/v1", "OPENAI_API_KEY"


def api_key_for(provider, manual_key):
    if manual_key:
        return manual_key
    return get_secret(provider_defaults(provider)[2], "")


def translate_chat(provider, api_key, model, base_url, source_language, target_language, glossary, items):
    if not api_key:
        raise RuntimeError("缺少 API Key：请在左侧填写，或在 Streamlit Secrets 里保存。")
    url = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"sourceLanguage": source_language, "targetLanguage": target_language, "glossary": glossary, "items": items}

    if provider == "OpenAI":
        if not url.endswith("/responses"):
            url += "/responses"
        body = {
            "model": model,
            "instructions": "Translate Shopify ecommerce text. Preserve HTML, URLs, Liquid syntax, SKU-like codes, measurements, and brand names. Return only JSON array items with id and translation.",
            "input": json.dumps(payload, ensure_ascii=False),
        }
        response = requests.post(url, headers=headers, json=body, timeout=180)
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            err = data.get("error", {})
            raise RuntimeError(err.get("message") if isinstance(err, dict) else err or f"接口返回 HTTP {response.status_code}")
        raw = data.get("output_text", "") or "\n".join(
            c.get("text", "") for o in data.get("output", []) for c in o.get("content", []) if c.get("text")
        )
        return normalize_translations(parse_json(raw))

    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    system = "Translate Shopify ecommerce text. Preserve HTML, URLs, Liquid syntax, SKU-like codes, measurements, and brand names. Return only JSON: {\"items\":[{\"id\":\"same id\",\"translation\":\"translated text\"}]}"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": 0.1,
    }
    if provider == "DeepSeek" and model.startswith("deepseek-v4"):
        body["thinking"] = {"type": "disabled"}
    response = requests.post(url, headers=headers, json=body, timeout=180)
    data = response.json() if response.content else {}
    if response.status_code >= 400:
        err = data.get("error", {})
        raise RuntimeError(err.get("message") if isinstance(err, dict) else err or f"接口返回 HTTP {response.status_code}")
    return normalize_translations(parse_json(data.get("choices", [{}])[0].get("message", {}).get("content", "")))


def translate_free(target_language, items):
    translations = {}
    for item in items:
        response = requests.get("https://translate.googleapis.com/translate_a/single", params={
            "client": "gtx", "sl": "auto", "tl": language_code(target_language), "dt": "t", "q": item["text"],
        }, timeout=60)
        data = response.json()
        translations[item["id"]] = "".join(part[0] for part in data[0] if part and part[0])
    return translations


def apply_translation(rows, html_cells, item, translation):
    if not translation or not str(translation).strip():
        return False
    if item["mode"] == "html":
        cell = html_cells.get(item["html_key"])
        if not cell:
            return False
        segment = cell["segments"][item["segment_index"]]
        cell["translations"][item["segment_index"]] = preserve_padding(segment["text"], translation)
        rows[cell["row_index"]][cell["target_column"]] = rebuild_html(
            cell["original"],
            cell["segments"],
            cell["translations"],
        )
        return True
    rows[item["row_index"]][item["target_column"]] = translation
    return True


def slug(text):
    return re.sub(r"\s+", "-", re.sub(r'[\\/:*?"<>|]+', "", text.strip().lower())) or "translated"


password = get_secret("APP_PASSWORD", "")
if password and st.text_input("访问密码", type="password") != password:
    st.stop()

st.title("Shopify CSV 一键翻译")
st.caption("上传 CSV，选择语言，翻译后下载 Shopify 可导入的 CSV。")

with st.sidebar:
    provider = st.selectbox("翻译接口", ["千问 Qwen", "DeepSeek", "OpenAI", "免费翻译"])
    default_model, default_base_url, _ = provider_defaults(provider)
    selected_language = st.selectbox("目标语言（可输入搜索）", LANGUAGE_OPTIONS, index=0)
    custom_language = st.text_input("自定义语言（可选）", value="", placeholder="例如 Croatian / 克罗地亚语")
    target_language = custom_language.strip() or selected_language
    source_language = st.selectbox("源语言", ["auto"] + LANGUAGE_OPTIONS, index=0)
    model = st.text_input("模型", value=default_model, disabled=provider == "免费翻译")
    base_url = st.text_input("API 地址", value=default_base_url, disabled=provider == "免费翻译")
    manual_key = st.text_input("API Key", type="password")
    empty_only = st.checkbox("只翻译目标列为空的行", value=True)
    skip_machine_text = st.checkbox("跳过链接、数字、短代码", value=True)
    glossary = st.text_area("术语表 / 品牌词", value="", height=90)

uploaded = st.file_uploader("放入 Shopify CSV", type=["csv"])
if not uploaded:
    st.info("请先上传 Shopify 导出的 CSV 文件。")
    st.stop()

headers, rows = parse_csv(uploaded)
items, html_cells = make_items(headers, rows, empty_only, skip_machine_text)
plan = detect_plan(headers)

left, right = st.columns([2, 1])
with left:
    st.subheader("预览")
    st.dataframe(rows[:50], use_container_width=True, height=420)
with right:
    st.subheader("识别结果")
    st.write(f"文件：`{uploaded.name}`")
    st.write(f"目标语言：`{target_language}`")
    st.write(f"行数：`{len(rows)}`")
    st.write(f"列数：`{len(headers)}`")
    st.write(f"待翻译：`{len(items)}`")
    for column in plan:
        st.code(f"{column['source']} -> {column['target']}")

if "translated_csv" not in st.session_state:
    st.session_state.translated_csv = None
    st.session_state.translated_name = None

if st.button("开始翻译", type="primary", disabled=not items):
    progress = st.progress(0)
    status = st.empty()
    done = 0
    try:
        for start in range(0, len(items), 10):
            batch = items[start:start + 10]
            simple_batch = [{"id": x["id"], "text": x["text"]} for x in batch]
            if provider == "免费翻译":
                translations = translate_free(target_language, simple_batch)
            else:
                translations = translate_chat(provider, api_key_for(provider, manual_key), model, base_url, source_language, target_language, glossary, simple_batch)
            for item in batch:
                if apply_translation(rows, html_cells, item, translations.get(item["id"], "")):
                    done += 1
            progress.progress(done / max(len(items), 1))
            status.write(f"已完成 {done} / {len(items)}")
            time.sleep(0.05)
        base = re.sub(r"\.csv$", "", uploaded.name, flags=re.I)
        st.session_state.translated_name = f"{base}-{slug(target_language)}-shopify.csv"
        st.session_state.translated_csv = serialize_csv(headers, rows)
        st.success("翻译完成，可以下载 CSV。")
    except Exception as exc:
        st.error(str(exc))

if st.session_state.translated_csv:
    st.download_button("下载翻译后的 CSV", st.session_state.translated_csv, st.session_state.translated_name, "text/csv")
