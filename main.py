import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import List

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import AuthenticationError, OpenAI

TRENDING_URL = "https://github.com/trending"
TOP_N = 8
TELEGRAM_MAX_LEN = 4096
TELEGRAM_SAFE_LEN = 3800
FEISHU_TEXT_SAFE_LEN = 3000
WECOM_MARKDOWN_SAFE_BYTES = 3800
REQUEST_TIMEOUT = 30
CN_TZ = timezone(timedelta(hours=8))
SUPPORTED_PUSH_CHANNELS = ("telegram", "feishu", "wecom")

logger = logging.getLogger("trending_bot")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def normalize_repo_name(raw_text: str) -> str:
    return "/".join(part.strip() for part in raw_text.split("/"))


def fetch_trending(top_n: int = TOP_N) -> List[dict]:
    logger.info("Fetching GitHub Trending page...")
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(TRENDING_URL, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    repos = []
    articles = soup.select("article.Box-row")

    for article in articles:
        link_el = article.select_one("h2 a")
        if not link_el:
            continue

        repo_name = normalize_repo_name(link_el.get_text(" ", strip=True))
        desc_el = article.select_one("p")
        lang_el = article.select_one('[itemprop="programmingLanguage"]')
        stars_today_el = article.select_one("span.d-inline-block.float-sm-right")

        repos.append(
            {
                "repo": repo_name,
                "url": f"https://github.com/{repo_name}",
                "desc": desc_el.get_text(" ", strip=True) if desc_el else "",
                "lang": lang_el.get_text(strip=True) if lang_el else "Unknown",
                "stars_today": stars_today_el.get_text(" ", strip=True) if stars_today_el else "N/A",
            }
        )
        if len(repos) >= top_n:
            break

    if len(repos) < top_n:
        logger.warning("Only parsed %s repositories from trending page.", len(repos))
    else:
        logger.info("Parsed top %s repositories.", top_n)

    if not repos:
        raise RuntimeError("No repositories parsed from GitHub Trending.")

    return repos


def build_translation_input(items: List[dict]) -> str:
    return "\n".join(f"{idx}. {item['desc'] or '(No description)'}" for idx, item in enumerate(items, 1))


def fallback_descriptions(items: List[dict]) -> List[str]:
    return [item["desc"] or "(No description)" for item in items]


def parse_json_from_model(text: str):
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```") and lines[-1].strip() == "```":
            candidate = "\n".join(lines[1:-1]).strip()
    return json.loads(candidate)


def parse_translation_list(text: str, expected_count: int) -> List[str]:
    try:
        parsed = parse_json_from_model(text)
        if isinstance(parsed, list) and len(parsed) == expected_count:
            return [str(x).strip() for x in parsed]
    except json.JSONDecodeError:
        pass

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned_lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip() for line in lines]
    cleaned_lines = [line for line in cleaned_lines if line]
    if len(cleaned_lines) == expected_count:
        logger.warning("Model output is not JSON; parsed as numbered lines fallback.")
        return cleaned_lines

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    cleaned_paras = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", p).strip() for p in paragraphs]
    cleaned_paras = [p for p in cleaned_paras if p]
    if len(cleaned_paras) == expected_count:
        logger.warning("Model output is not JSON; parsed as paragraph fallback.")
        return cleaned_paras

    raise RuntimeError(
        f"Failed to parse translations. expected={expected_count}, preview={text[:160]}"
    )


def extract_text_from_openai_response(response) -> str:
    if response is None:
        return ""

    if isinstance(response, str):
        return response.strip()

    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    if isinstance(response, dict):
        if isinstance(response.get("output_text"), str):
            return response["output_text"].strip()
        if isinstance(response.get("text"), str):
            return response["text"].strip()
        if isinstance(response.get("content"), str):
            return response["content"].strip()
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()

    choices = getattr(response, "choices", None)
    if isinstance(choices, list) and choices:
        message = getattr(choices[0], "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content.strip()

    return str(response).strip()


def translate_descriptions(
    items: List[dict],
    api_key: str,
    model: str = "gpt-5-mini",
    base_url: str | None = None,
    default_headers: dict | None = None,
) -> List[str]:
    logger.info("Translating descriptions with OpenAI (%s)...", model)
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
        logger.info("Using OpenAI base URL: %s", base_url)
    if default_headers:
        client_kwargs["default_headers"] = default_headers
    client = OpenAI(**client_kwargs)
    raw_desc = build_translation_input(items)
    prompt = (
        "请把下面每一条项目简介翻译成简洁自然的中文。\n"
        "要求：\n"
        "1. 严格保持原顺序和条数。\n"
        "2. 仅返回 JSON 数组字符串，例如 [\"译文1\",\"译文2\"]。\n"
        "3. 不要返回 markdown，不要解释。\n\n"
        f"{raw_desc}"
    )
    response = client.responses.create(model=model, input=prompt)
    text = extract_text_from_openai_response(response)

    # Some OpenAI-compatible proxies only fully support chat.completions.
    if not text:
        logger.warning("Empty text from /responses API. Falling back to /chat/completions.")
        chat_resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        text = extract_text_from_openai_response(chat_resp)

    if not text:
        raise RuntimeError("OpenAI translation returned empty output.")

    translations = parse_translation_list(text, len(items))
    logger.info("Translation completed for %s items.", len(translations))
    return translations


def format_message(items: List[dict], desc_zh_list: List[str]) -> str:
    lines = ["GitHub Trending 中文速递", ""]
    for idx, (item, desc_zh) in enumerate(zip(items, desc_zh_list), 1):
        lines.extend(
            [
                f"{idx}. {item['repo']}",
                f"语言: {item['lang']}",
                f"今日 Star: {item['stars_today']}",
                f"简介: {desc_zh or '（无）'}",
                item["url"],
                "",
            ]
        )
    return "\n".join(lines).strip()


def format_blog_markdown(items: List[dict], desc_zh_list: List[str], date_str: str) -> str:
    lines = [f"# {date_str} GitHub Trending 中文速递", ""]
    for idx, (item, desc_zh) in enumerate(zip(items, desc_zh_list), 1):
        lines.extend(
            [
                f"## {idx}. [{item['repo']}]({item['url']})",
                f"- 语言：{item['lang']}",
                f"- 今日 Star：{item['stars_today']}",
                f"- 简介：{desc_zh or '（无）'}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def short_summary(text: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", (text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def parse_bool_env(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def parse_push_channels(raw: str | None) -> List[str]:
    candidate = (raw or "telegram").strip()
    if not candidate:
        candidate = "telegram"

    channels = []
    seen = set()
    for token in re.split(r"[,\s]+", candidate):
        channel = token.strip().lower()
        if not channel or channel in seen:
            continue
        if channel not in SUPPORTED_PUSH_CHANNELS:
            raise RuntimeError(
                f"Unsupported channel in PUSH_CHANNELS: {channel}. "
                f"Supported: {','.join(SUPPORTED_PUSH_CHANNELS)}"
            )
        seen.add(channel)
        channels.append(channel)

    if not channels:
        raise RuntimeError("No valid channel found in PUSH_CHANNELS.")
    return channels


def create_admin_session(base_url: str, username: str, password: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    url = f"{base_url.rstrip('/')}/api/admin/auth/login"
    response = session.post(
        url,
        json={"username": username, "password": password},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    logger.info("Admin login succeeded.")
    return session


def get_blog_posts(session: requests.Session, base_url: str) -> List[dict]:
    url = f"{base_url.rstrip('/')}/api/admin/list/blog_posts"
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return data.get("items") if isinstance(data, dict) and isinstance(data.get("items"), list) else []


def upsert_blog_post(
    session: requests.Session,
    base_url: str,
    slug: str,
    title: str,
    summary: str,
    content: str,
    date_str: str,
) -> None:
    posts = get_blog_posts(session, base_url)
    updated = False

    for item in posts:
        if str(item.get("slug", "")).strip() == slug:
            item["title"] = title
            item["summary"] = summary
            item["content"] = content
            item["published"] = True
            item["published_at"] = date_str
            item["tags"] = ["github", "trending", "daily"]
            item["category"] = item.get("category") or None
            updated = True
            break

    if not updated:
        max_order = 0
        for item in posts:
            try:
                max_order = max(max_order, int(item.get("order") or 0))
            except (TypeError, ValueError):
                continue
        posts.append(
            {
                "title": title,
                "slug": slug,
                "summary": summary,
                "content": content,
                "cover": "",
                "tags": ["github", "trending", "daily"],
                "category": None,
                "published": True,
                "published_at": date_str,
                "order": max_order + 1,
            }
        )

    for idx, item in enumerate(posts, 1):
        item["order"] = idx

    url = f"{base_url.rstrip('/')}/api/admin/list/blog_posts"
    response = session.put(url, json={"items": posts}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    logger.info("Blog post %s with slug=%s", "updated" if updated else "created", slug)


def maybe_publish_blog_post(items: List[dict], desc_zh_list: List[str], dry_run: bool) -> None:
    if not parse_bool_env("RUN_NIGHT_BLOG", default=False):
        return

    date_str = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    title = f"{date_str} GitHub Trending 中文速递"
    slug = f"github-trending-{date_str}"
    content = format_blog_markdown(items, desc_zh_list, date_str)
    summary = short_summary("；".join(desc_zh_list), limit=170)

    if dry_run:
        logger.info("Dry-run mode: skip blog publish. title=%s slug=%s", title, slug)
        return

    admin_base_url = (os.getenv("ADMIN_BASE_URL") or "").strip()
    admin_username = (os.getenv("ADMIN_USERNAME") or "").strip()
    admin_password = os.getenv("ADMIN_PASSWORD") or ""

    if not admin_base_url or not admin_username or not admin_password:
        raise RuntimeError(
            "RUN_NIGHT_BLOG=true but missing ADMIN_BASE_URL / ADMIN_USERNAME / ADMIN_PASSWORD."
        )

    session = create_admin_session(admin_base_url, admin_username, admin_password)
    upsert_blog_post(
        session=session,
        base_url=admin_base_url,
        slug=slug,
        title=title,
        summary=summary,
        content=content,
        date_str=date_str,
    )


def split_message(text: str, max_len: int = TELEGRAM_SAFE_LEN) -> List[str]:
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""
    paragraphs = text.split("\n\n")

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_len:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(paragraph) <= max_len:
            current = paragraph
            continue

        start = 0
        while start < len(paragraph):
            end = start + max_len
            chunks.append(paragraph[start:end])
            start = end
        current = ""

    if current:
        chunks.append(current)

    return chunks


def split_message_by_utf8_bytes(text: str, max_bytes: int) -> List[str]:
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    chunks = []
    current = ""
    paragraphs = text.split("\n\n")

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
            continue

        flush()
        if len(paragraph.encode("utf-8")) <= max_bytes:
            current = paragraph
            continue

        part = ""
        for char in paragraph:
            next_part = f"{part}{char}"
            if len(next_part.encode("utf-8")) <= max_bytes:
                part = next_part
                continue
            if part:
                chunks.append(part)
            part = char
        if part:
            chunks.append(part)

    flush()
    return chunks


def send_telegram_messages(messages: List[str], bot_token: str, chat_id: str) -> None:
    if not bot_token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for index, message in enumerate(messages, 1):
        if len(message) > TELEGRAM_MAX_LEN:
            raise RuntimeError(f"Message chunk {index} still exceeds Telegram max length.")

        logger.info("Sending Telegram message part %s/%s", index, len(messages))
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()


def build_feishu_sign(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def parse_json_response(response: requests.Response) -> dict:
    try:
        return response.json() if response.content else {}
    except ValueError:
        return {}


def send_feishu_messages(messages: List[str], webhook_url: str, sign_secret: str | None = None) -> None:
    if not webhook_url:
        raise RuntimeError("Missing FEISHU_WEBHOOK_URL.")

    for index, message in enumerate(messages, 1):
        payload = {
            "msg_type": "text",
            "content": {"text": message},
        }
        if sign_secret:
            now = int(time.time())
            payload["timestamp"] = str(now)
            payload["sign"] = build_feishu_sign(now, sign_secret)

        logger.info("Sending Feishu message part %s/%s", index, len(messages))
        response = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = parse_json_response(response)
        code = data.get("code")
        if code not in (None, 0):
            raise RuntimeError(f"Feishu webhook failed: code={code}, msg={data.get('msg')}")


def send_wecom_messages(messages: List[str], webhook_url: str) -> None:
    if not webhook_url:
        raise RuntimeError("Missing WECOM_WEBHOOK_URL.")

    for index, message in enumerate(messages, 1):
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": message},
        }
        logger.info("Sending WeCom message part %s/%s", index, len(messages))
        response = requests.post(webhook_url, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = parse_json_response(response)
        errcode = data.get("errcode")
        if errcode not in (None, 0):
            raise RuntimeError(f"WeCom webhook failed: errcode={errcode}, errmsg={data.get('errmsg')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch GitHub trending and push to multiple channels.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print message to stdout without sending to push channels.",
    )
    return parser.parse_args()


def main() -> int:
    setup_logging()
    load_dotenv()
    args = parse_args()

    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_base_url = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
    openai_model_raw = (os.getenv("OPENAI_MODEL") or "").strip()
    if openai_model_raw:
        openai_model = openai_model_raw
    elif openai_base_url and "openrouter.ai" in openai_base_url:
        openai_model = "openrouter/free"
    else:
        openai_model = "gpt-5-mini"

    default_headers = {}
    if openai_base_url and "openrouter.ai" in openai_base_url:
        openrouter_site_url = (os.getenv("OPENROUTER_SITE_URL") or "").strip()
        openrouter_app_name = (os.getenv("OPENROUTER_APP_NAME") or "push-telegram").strip()
        if openrouter_site_url:
            default_headers["HTTP-Referer"] = openrouter_site_url
        if openrouter_app_name:
            default_headers["X-Title"] = openrouter_app_name
        if default_headers:
            logger.info("Using OpenRouter headers: %s", ",".join(sorted(default_headers.keys())))

    try:
        push_channels = parse_push_channels(os.getenv("PUSH_CHANNELS"))
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    logger.info("Enabled push channels: %s", ",".join(push_channels))

    telegram_bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    telegram_chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    feishu_webhook_url = (os.getenv("FEISHU_WEBHOOK_URL") or "").strip()
    feishu_sign_secret = (os.getenv("FEISHU_SIGN_SECRET") or "").strip()
    wecom_webhook_url = (os.getenv("WECOM_WEBHOOK_URL") or "").strip()

    if not args.dry_run:
        if "telegram" in push_channels and (not telegram_bot_token or not telegram_chat_id):
            logger.error("Channel telegram enabled but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing.")
            return 1
        if "feishu" in push_channels and not feishu_webhook_url:
            logger.error("Channel feishu enabled but FEISHU_WEBHOOK_URL is missing.")
            return 1
        if "wecom" in push_channels and not wecom_webhook_url:
            logger.error("Channel wecom enabled but WECOM_WEBHOOK_URL is missing.")
            return 1

    try:
        items = fetch_trending(TOP_N)
        if not openai_api_key:
            logger.warning("Missing OPENAI_API_KEY. Skipping translation and using original descriptions.")
            desc_zh_list = fallback_descriptions(items)
        else:
            try:
                desc_zh_list = translate_descriptions(
                    items,
                    openai_api_key,
                    model=openai_model,
                    base_url=openai_base_url,
                    default_headers=default_headers or None,
                )
            except Exception as exc:
                logger.exception(
                    "Translation failed, fallback to original descriptions. error=%s",
                    exc,
                )
                desc_zh_list = fallback_descriptions(items)

        final_message = format_message(items, desc_zh_list)
        preview_chunks = split_message(final_message)
        logger.info("Prepared %s preview chunk(s).", len(preview_chunks))

        if args.dry_run:
            logger.info("Dry-run mode enabled. No push messages will be sent.")
            for idx, chunk in enumerate(preview_chunks, 1):
                print(f"\n===== MESSAGE {idx}/{len(preview_chunks)} =====\n{chunk}\n")
        else:
            if "telegram" in push_channels:
                telegram_chunks = split_message(final_message, max_len=TELEGRAM_SAFE_LEN)
                send_telegram_messages(telegram_chunks, telegram_bot_token, telegram_chat_id)
                logger.info("Telegram messages sent successfully.")
            if "feishu" in push_channels:
                feishu_chunks = split_message(final_message, max_len=FEISHU_TEXT_SAFE_LEN)
                send_feishu_messages(feishu_chunks, feishu_webhook_url, feishu_sign_secret or None)
                logger.info("Feishu messages sent successfully.")
            if "wecom" in push_channels:
                wecom_chunks = split_message_by_utf8_bytes(final_message, max_bytes=WECOM_MARKDOWN_SAFE_BYTES)
                send_wecom_messages(wecom_chunks, wecom_webhook_url)
                logger.info("WeCom messages sent successfully.")

        maybe_publish_blog_post(items, desc_zh_list, dry_run=args.dry_run)
        return 0
    except requests.RequestException as exc:
        logger.exception("Network request failed: %s", exc)
        return 1
    except AuthenticationError as exc:
        logger.error(
            "OpenAI authentication failed. Check OPENAI_API_KEY and OPENAI_BASE_URL. %s",
            exc,
        )
        return 1
    except Exception as exc:
        logger.exception("Program failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
