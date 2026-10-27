import html
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from openai import OpenAI


TIMEZONE = ZoneInfo("Asia/Shanghai")


def as_html(text: str) -> str:
    escaped = html.escape(text)
    url_pattern = r"(https?://[^\s<]+)"
    linked = re.sub(
        url_pattern,
        r'<a href="\1">\1</a>',
        escaped,
    )
    return linked.replace("\n", "<br>\n")


def main() -> None:
    now = datetime.now(TIMEZONE)
    date_label = now.strftime("%Y-%m-%d")
    model = os.getenv("OPENAI_MODEL", "gpt-5.5")

    prompt = f"""
你是新闻编辑。请检索 {date_label}（北京时间）前 24 小时内的全球综合热点新闻，
生成一份中文日报，供读者约 10 分钟阅读。

要求：
- 只列 10 条最重要、相互尽量不重复的新闻。
- 每条包含：标题、两三句事实摘要、影响或背景、来源名称和完整 URL。
- 优先使用可靠的一手或主流媒体来源，不要编造事实或网址。
- 如果没有足够重大的新闻，也要输出一份简短说明。
- 直接输出纯文本，保留完整 URL，方便邮件客户端识别为链接。
"""

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.responses.create(
        model=model,
        tools=[{"type": "web_search"}],
        tool_choice="required",
        input=prompt,
    )
    digest = response.output_text.strip()

    to_address = os.environ["NEWS_TO"]
    from_address = os.environ["NEWS_FROM"]
    subject = f"全球热点新闻摘要｜{date_label}"

    result = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "from": from_address,
            "to": [to_address],
            "subject": subject,
            "text": digest,
            "html": as_html(digest),
        },
        timeout=30,
    )
    result.raise_for_status()
    print(f"Sent {subject} to {to_address}")


if __name__ == "__main__":
    main()
