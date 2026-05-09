# GitHub Trending Push Bot

一个简单的 Python 脚本，用于：

1. 抓取 [GitHub Trending](https://github.com/trending)
2. 提取前 8 个仓库的名称、简介、语言、今日 Star
3. 用 OpenAI API 把简介翻译为中文
4. 推送到一个或多个平台（Telegram / 飞书 / 企业微信）
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

`.env` 至少需要包含：

```env
OPENAI_API_KEY=your_openai_api_key
PUSH_CHANNELS=telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

`PUSH_CHANNELS` 支持多个平台，逗号分隔，例如：

```env
PUSH_CHANNELS=telegram,feishu,wecom
```

如果启用了飞书：

```env
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
# 可选：若飞书机器人开启签名校验
FEISHU_SIGN_SECRET=your_feishu_sign_secret
```

如果启用了企业微信：

```env
WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
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
- 工作流里只在北京时间 `19:30` 自动开启该功能（`09:00` 仅推送消息，不发布博客）。

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

正常发送（按 `PUSH_CHANNELS` 推送）：

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

平台连通性测试脚本：

```bash
./test_telegram.sh "telegram test ok"
./test_feishu.sh "feishu test ok"
./test_wecom.sh "wecom test ok"
```

## 日志与健壮性

- 使用标准 `logging` 输出清晰日志
- 对网络请求和运行时异常做了捕获
- Telegram 文本会自动分段，避免超过单条长度限制（4096 字符）
- 企业微信 markdown 推送会按 UTF-8 字节自动分段，避免超过单条长度限制

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
- `PUSH_CHANNELS`（可选，默认 `telegram`）
- `TELEGRAM_BOT_TOKEN`（当启用 `telegram` 必填）
- `TELEGRAM_CHAT_ID`（当启用 `telegram` 必填）
- `FEISHU_WEBHOOK_URL`（当启用 `feishu` 必填）
- `FEISHU_SIGN_SECRET`（可选，飞书签名校验启用时填写）
- `WECOM_WEBHOOK_URL`（当启用 `wecom` 必填）
- `ADMIN_BASE_URL`（夜间发博客必填）
- `ADMIN_USERNAME`（夜间发博客必填）
- `ADMIN_PASSWORD`（夜间发博客必填）
