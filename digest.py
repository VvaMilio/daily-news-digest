import html
import json
import os
import re
import smtplib
from datetime import datetime
from email.utils import parsedate_to_datetime
from email.message import EmailMessage
from email.utils import formataddr
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests
from openai import OpenAI


TIMEZONE = ZoneInfo("Asia/Shanghai")
GITHUB_API = "https://api.github.com/search/repositories"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def as_html(text: str) -> str:
    escaped = html.escape(text)
    linked = re.sub(
        r"(https?://[^\s<]+)",
        r'<a href="\1">\1</a>',
        escaped,
    )
    return linked.replace("\n", "<br>\n")


def parse_recipients(raw: str) -> list[str]:
    recipients = [item.strip() for item in re.split(r"[,;\n]+", raw) if item.strip()]
    if not recipients:
        raise ValueError("NEWS_TO must contain at least one email address")
    return recipients


def build_openai_client() -> OpenAI:
    options = {"api_key": os.environ["OPENAI_API_KEY"]}
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        options["base_url"] = base_url.rstrip("/")
    return OpenAI(**options)


def strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def fetch_news_feed(query: str) -> list[dict[str, str]]:
    response = requests.get(
        GOOGLE_NEWS_RSS,
        params={
            "q": f"{query} when:1d",
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        },
        headers={"User-Agent": "daily-news-digest/1.0"},
        timeout=30,
    )
    response.raise_for_status()

    root = ElementTree.fromstring(response.content)
    items = []
    for node in root.findall("./channel/item"):
        title = strip_html(node.findtext("title", default=""))
        link = (node.findtext("link", default="") or "").strip()
        if not title or not link:
            continue

        published = node.findtext("pubDate", default="")
        try:
            published_dt = parsedate_to_datetime(published)
            published = published_dt.astimezone(TIMEZONE).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OverflowError):
            published = "时间未提供"

        source = strip_html(node.findtext("source", default=""))
        if not source:
            source = title.rsplit(" - ", 1)[-1] if " - " in title else "来源未标注"
        items.append(
            {
                "title": title,
                "source": source,
                "published": published,
                "snippet": strip_html(node.findtext("description", default=""))[:700],
                "url": link,
            }
        )
    return items


def collect_news() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    general = []
    for query in ("world", "global economy", "international politics"):
        general.extend(fetch_news_feed(query))

    ai = []
    for query in (
        '"artificial intelligence"',
        "generative AI OR machine learning",
    ):
        ai.extend(fetch_news_feed(query))

    def deduplicate(items: list[dict[str, str]]) -> list[dict[str, str]]:
        unique = []
        seen = set()
        for item in items:
            key = re.sub(r"[^a-z0-9]+", "", item["title"].lower())
            if key and key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:30]

    general, ai = deduplicate(general), deduplicate(ai)
    if not general or not ai:
        raise RuntimeError(
            f"News RSS feeds returned insufficient results (global={len(general)}, AI={len(ai)})."
        )
    return general, ai


def news_lines(items: list[dict[str, str]]) -> str:
    return json.dumps(items, ensure_ascii=False, indent=2)


def generate_news_digest(
    client: OpenAI,
    model: str,
    date_label: str,
    general: list[dict[str, str]],
    ai: list[dict[str, str]],
) -> str:
    prompt = f"""
你是新闻编辑。请根据下面由新闻 RSS 源提供的候选内容，生成 {date_label}（北京时间）的中文日报。

第一部分必须是“全球综合热点”，列出 5 条最重要的全球新闻；第二部分必须是“AI 热点”，列出 5 条与人工智能直接相关的新闻。
每条包含：标题、简短事实摘要、来源名称、发布时间和候选数据中对应的完整 URL。
只能使用候选数据中实际提供的事实、来源和 URL；不要补充猜测、外部信息或编造细节。优先选择重要且来源较可靠的不同事件，两部分不要重复。
如果某一部分候选不足 5 条，列出能核实的条目，并简短说明当天没有足够重大更新；不要为了凑数编造新闻。
直接输出纯文本，保留完整 URL，方便邮件客户端识别为链接。

全球综合新闻候选：
{news_lines(general)}

AI 新闻候选：
{news_lines(ai)}
"""
    response = client.responses.create(model=model, input=prompt)
    return response.output_text.strip()


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "daily-news-digest",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def search_repositories(query: str, per_page: int) -> list[dict]:
    response = requests.get(
        GITHUB_API,
        params={
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": per_page,
        },
        headers=github_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("items", [])


def choose_unique(items: list[dict], limit: int, excluded: set[str] | None = None) -> list[dict]:
    excluded = excluded or set()
    chosen = []
    seen = set(excluded)
    for item in items:
        name = item.get("full_name")
        if not name or name in seen:
            continue
        seen.add(name)
        chosen.append(item)
        if len(chosen) == limit:
            break
    return chosen


def collect_github_projects() -> tuple[list[dict], list[dict]]:
    popular = choose_unique(search_repositories("stars:>1000", 10), 5)

    ai_candidates = []
    for query in (
        '"artificial intelligence" in:name,description,readme stars:>500',
        '"machine learning" in:name,description,readme stars:>500',
        '"large language model" in:name,description,readme stars:>500',
    ):
        ai_candidates.extend(search_repositories(query, 10))
    if len(ai_candidates) < 5:
        ai_candidates.extend(search_repositories("AI stars:>500", 20))
    ai_candidates.sort(key=lambda item: item.get("stargazers_count", 0), reverse=True)
    ai = choose_unique(ai_candidates, 5)
    return popular, ai


def repository_lines(items: list[dict]) -> str:
    lines = []
    for index, item in enumerate(items, start=1):
        topics = ", ".join(item.get("topics") or []) or "无"
        lines.append(
            "\n".join(
                [
                    f"{index}. {item.get('full_name', '')}",
                    f"描述：{item.get('description') or '无描述'}",
                    f"Stars：{item.get('stargazers_count', 0)}；Forks：{item.get('forks_count', 0)}；主要语言：{item.get('language') or '未标注'}",
                    f"Topics：{topics}",
                    f"链接：{item.get('html_url', '')}",
                ]
            )
        )
    return "\n\n".join(lines)


def generate_github_digest(
    client: OpenAI,
    model: str,
    date_label: str,
    popular: list[dict],
    ai: list[dict],
) -> str:
    prompt = f"""
请根据下面的 GitHub 公开数据，生成一封中文项目推荐邮件，日期为 {date_label}。

邮件必须分成两个部分：
1. “热门 GitHub 项目”：准确介绍下面 5 个项目。
2. “AI GitHub 项目”：准确介绍下面 5 个项目。

每个项目包含：项目名、解决什么问题、值得关注的亮点、Stars 数、主要语言和完整链接。
只使用提供的数据，不要编造功能、作者、许可证或网址。语言简洁，适合约 10 分钟阅读。

热门 GitHub 项目：
{repository_lines(popular)}

AI GitHub 项目：
{repository_lines(ai)}
"""
    response = client.responses.create(model=model, input=prompt)
    return response.output_text.strip()


def send_email(
    gmail_address: str,
    gmail_app_password: str,
    recipients: list[str],
    subject: str,
    body: str,
) -> None:
    message = EmailMessage()
    message["From"] = formataddr(("每日资讯摘要", gmail_address))
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    message.add_alternative(as_html(body), subtype="html")

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(gmail_address, gmail_app_password)
        smtp.send_message(message, from_addr=gmail_address, to_addrs=recipients)


def main() -> None:
    now = datetime.now(TIMEZONE)
    date_label = now.strftime("%Y-%m-%d")
    model = os.getenv("OPENAI_MODEL") or "gpt-6-astra"
    recipients = parse_recipients(os.environ["NEWS_TO"])
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]

    client = build_openai_client()
    general_news, ai_news = collect_news()
    news_digest = generate_news_digest(client, model, date_label, general_news, ai_news)
    popular_projects, ai_projects = collect_github_projects()
    github_digest = generate_github_digest(
        client, model, date_label, popular_projects, ai_projects
    )

    send_email(
        gmail_address,
        gmail_app_password,
        recipients,
        f"全球热点与 AI 新闻摘要｜{date_label}",
        news_digest,
    )
    send_email(
        gmail_address,
        gmail_app_password,
        recipients,
        f"热门 GitHub 项目与 AI 项目推荐｜{date_label}",
        github_digest,
    )
    print(f"Sent two digests to {len(recipients)} recipient(s)")


if __name__ == "__main__":
    main()
