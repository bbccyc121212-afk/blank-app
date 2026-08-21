# Shopify CSV Translator

Shopify CSV 翻译工具的 Streamlit 部署版。

## 使用

1. 上传 Shopify 导出的 CSV。
2. 选择目标语言。
3. 选择翻译接口：千问 Qwen、DeepSeek、OpenAI 或免费翻译。
4. 点击开始翻译。
5. 下载翻译后的 CSV，再导回 Shopify。

## Streamlit Secrets

在 Streamlit App settings -> Secrets 里填写：

```toml
APP_PASSWORD = "你自己设置的访问密码"
DASHSCOPE_API_KEY = "千问 API Key"
DEEPSEEK_API_KEY = "DeepSeek API Key"
OPENAI_API_KEY = "OpenAI API Key"
```

只用其中一个平台时，只填对应的 Key 即可。
