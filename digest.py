import html
import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo

import requests
from openai import OpenAI


TIMEZONE = ZoneInfo("Asia/Shanghai")
GITHUB_API = "https://api.github.com/search/repositories"


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


def generate_news_digest(client: OpenAI, model: str, date_label: str) -> str:
    prompt = f"""
你是新闻编辑。请检索 {date_label}（北京时间）前 24 小时内的新闻，生成一封中文日报。

第一部分必须是“全球综合热点”，列出 5 条最重要的全球新闻；第二部分必须是“AI 热点”，列出 5 条与人工智能直接相关的新闻。
每条包含：标题、两三句事实摘要、影响或背景、来源名称和完整 URL。
优先使用可靠的一手或主流媒体来源，不要编造事实或网址。两部分的新闻尽量互不重复。
如果当天没有足够重大的新闻，也要说明原因，但仍尽量给出可核实的更新。
直接输出纯文本，保留完整 URL，方便邮件客户端识别为链接。
"""
    response = client.responses.create(
        model=model,
        tools=[{"type": "web_search"}],
        tool_choice="required",
        input=prompt,
    )
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
    news_digest = generate_news_digest(client, model, date_label)
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
