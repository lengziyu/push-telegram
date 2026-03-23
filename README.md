# GitHub Trending Telegram Bot

一个简单的 Python 脚本，用于：

1. 抓取 [GitHub Trending](https://github.com/trending)
2. 提取前 8 个仓库的名称、简介、语言、今日 Star
3. 用 OpenAI API 把简介翻译为中文
4. 通过 Telegram Bot API 发送到指定 `chat_id`
5. 夜间任务自动同步一篇博客到 `admin.lengziyu.cn`

## 环境要求

- Python 3.10+

## 安装依赖

```bash
pip3 install -r requirements.txt
```

## 配置环境变量

复制示例文件并填写：

```bash
cp .env.example .env
```

`.env` 需要包含：

```env
OPENAI_API_KEY=your_openai_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

如果你使用的是 OpenAI 兼容代理，还可以加：

```env
OPENAI_BASE_URL=https://your-proxy-domain/v1
OPENAI_MODEL=gpt-5-mini
```

说明：
- `OPENAI_BASE_URL` 不填时默认直连官方 OpenAI。
- 代理常常要求特定模型名，如果报模型相关错误，把 `OPENAI_MODEL` 改成代理支持的模型。

如果要开启夜间自动发博客，还需要：

```env
ADMIN_BASE_URL=https://admin.lengziyu.cn
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_admin_password
RUN_NIGHT_BLOG=false
```

说明：
- `RUN_NIGHT_BLOG=true` 时会登录 admin 后台并写入 `blog_posts`。
- 工作流里只在北京时间 `19:30` 自动开启该功能（`09:00` 仅推送 Telegram）。

### OpenRouter 免费路由示例

```env
OPENAI_API_KEY=sk-or-v1-your_openrouter_key
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=openrouter/free

# 可选（OpenRouter 推荐）
OPENROUTER_SITE_URL=
OPENROUTER_APP_NAME=push-telegram
```

## 本地运行

正常发送到 Telegram：

```bash
python3 main.py
```

仅预览消息（不发送）：

```bash
python3 main.py --dry-run
```

也可以直接用脚本（自动处理 venv 和依赖）：

```bash
./run.sh
./run.sh --dry-run
```

## 日志与健壮性

- 使用标准 `logging` 输出清晰日志
- 对网络请求和运行时异常做了捕获
- Telegram 文本会自动分段，避免超过单条长度限制（4096 字符）

## GitHub Actions 定时执行

项目包含工作流文件：

- `.github/workflows/trending.yml`

默认每天定时执行两次（北京时间）并支持手动触发：

- `09:00`
- `19:30`

在 GitHub 仓库 `Settings -> Secrets and variables -> Actions` 中添加以下 Secrets：

- `OPENAI_API_KEY`（或 `OPENROUTER_API_KEY` 二选一）
- `OPENAI_BASE_URL`（可选，不填默认 `https://openrouter.ai/api/v1`）
- `OPENAI_MODEL`（可选，不填默认 `openrouter/free`）
- `OPENROUTER_SITE_URL`（可选）
- `OPENROUTER_APP_NAME`（可选）
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ADMIN_BASE_URL`（夜间发博客必填）
- `ADMIN_USERNAME`（夜间发博客必填）
- `ADMIN_PASSWORD`（夜间发博客必填）
