## LLM
LLM url: http://localhost:6655
API key: ***REDACTED***


Under http://localhost:6655, it provide multiple LLMs

Anthropic-Compatible - For tools supporting Anthropic API
OpenAI-Compatible - For tools supporting OpenAI API
Google Gemini - For tools supporting Gemini API
LiteLLM - Unified interface using SAP AI Core's Harmonized API


---

### LLM Providers and Endpoints

Different LLM providers expose different base URLs and API endpoints.

| Provider  | Base URL                             | Chat / Completion Endpoint               | Embeddings Endpoint                   | Models Endpoint  |
| --------- | ------------------------------------ | ---------------------------------------- | ------------------------------------- | ---------------- |
| Anthropic | `http://localhost:6655/anthropic/v1` | `/messages`                              | N/A                                   | `/models`        |
| OpenAI    | `http://localhost:6655/openai/v1`    | `/chat/completions`                      | `/embeddings`                         | `/models`        |
| Gemini    | `http://localhost:6655/gemini`       | `/v1beta/models/{model}:generateContent` | `/v1beta/models/{model}:embedContent` | `/v1beta/models` |
| LiteLLM   | `http://localhost:6655/litellm/v1`   | `/chat/completions`                      | `/embeddings`                         | `/models`        |

---

### Available Models

Different LLM models are provided by different providers and can be accessed through their respective endpoints.

When using the **LiteLLM endpoint**, all models from all providers are accessible through a **single OpenAI-compatible interface**.

**Endpoint**

```
http://localhost:6655/litellm/v1
```

---

## Model List

| Model Name             | Technical Name                 | Provider  | Type       |
| ---------------------- | ------------------------------ | --------- | ---------- |
| Claude 4.6 Sonnet      | `anthropic--claude-4.6-sonnet` | Anthropic | Chat       |
| Claude 4.6 Opus        | `anthropic--claude-4.6-opus`   | Anthropic | Chat       |
| Claude 4.5 Haiku       | `anthropic--claude-4.5-haiku`  | Anthropic | Chat       |
| Claude 4.5 Sonnet      | `anthropic--claude-4.5-sonnet` | Anthropic | Chat       |
| Claude 4.5 Opus        | `anthropic--claude-4.5-opus`   | Anthropic | Chat       |
| Claude 4 Sonnet        | `anthropic--claude-4-sonnet`   | Anthropic | Chat       |
| GPT-5                  | `gpt-5`                        | OpenAI    | Chat       |
| GPT-5 Mini             | `gpt-5-mini`                   | OpenAI    | Chat       |
| GPT-4.1                | `gpt-4.1`                      | OpenAI    | Chat       |
| GPT-4.1 Mini           | `gpt-4.1-mini`                 | OpenAI    | Chat       |
| Text Embedding 3 Small | `text-embedding-3-small`       | OpenAI    | Embeddings |
| Text Embedding 3 Large | `text-embedding-3-large`       | OpenAI    | Embeddings |
| Gemini 2.5 Pro         | `gemini-2.5-pro`               | Gemini    | Chat       |
| Gemini 2.5 Flash       | `gemini-2.5-flash`             | Gemini    | Chat       |
| Gemini 2.5 Flash Lite  | `gemini-2.5-flash-lite`        | Gemini    | Chat       |
| Gemini Embedding       | `gemini-embedding`             | Gemini    | Embeddings |




## LLM rate limit
1. 目前使用的LLM有20 requests per minute的限制，严谨超过这一限制，可以限制在16 requests per minute




## 搜索

1. 搜索可以使用ddgr（DuckDuckGo的命令行界面）来替代传统的搜索引擎，本地已经安装。
2. ddgr得到的结果如果有多余HTML字符可以自行使用库去清除
3. 使用proxy部分提供的proxy来绕过网络限制


## 网络问题

使用proxy来绕过网络限制，优先使用`http://proxy.sin.sap.corp:8080`代理。完整的命令如下：

```bash
proxy_on() {
  local proxy_url

  # Determine which proxy to use
  case "$1" in
    "my")
      proxy_url="http://localhost:7899"
      echo "✓ Using personal proxy: $proxy_url"
      ;;
    "sap"|"")
      proxy_url="http://proxy.sin.sap.corp:8080"
      echo "✓ Using SAP proxy: $proxy_url"
      ;;
    *)
      proxy_url="$1"
      echo "✓ Using custom proxy: $proxy_url"
      ;;
  esac

  # Set environment variables for system-wide proxy
  export http_proxy="$proxy_url"
  export https_proxy="$proxy_url"
  export NO_PROXY="localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.cluster.local,.local"
  export no_proxy="$NO_PROXY"

  # Configure git
  git config --global http.proxy "$proxy_url" 2>/dev/null
  git config --global https.proxy "$proxy_url" 2>/dev/null

  # Configure npm
  npm config set proxy "$proxy_url" 2>/dev/null
  npm config set https-proxy "$proxy_url" 2>/dev/null

  # Configure pnpm
  pnpm config set proxy "$proxy_url" 2>/dev/null
  pnpm config set https-proxy "$proxy_url" 2>/dev/null

  # Configure pip
  pip config set global.proxy "$proxy_url" 2>/dev/null

  echo "✓ Proxy enabled for: git, npm, pnpm, pip, and system environment"
}

proxy_off() {
  # Unset environment variables
  unset http_proxy
  unset https_proxy
  unset NO_PROXY no_proxy

  # Remove git proxy
  git config --global --unset http.proxy 2>/dev/null
  git config --global --unset https.proxy 2>/dev/null

  # Remove npm proxy
  npm config delete proxy 2>/dev/null
  npm config delete https-proxy 2>/dev/null

  # Remove pnpm proxy
  pnpm config delete proxy 2>/dev/null
  pnpm config delete https-proxy 2>/dev/null

  # Remove pip proxy
  pip config unset global.proxy 2>/dev/null

  echo "✓ Proxy disabled for all tools"
}
```