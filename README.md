# Daily global news digest

This workflow runs every day at 12:00 Asia/Shanghai, uses the OpenAI Responses API with web search to prepare a Chinese global-news digest, and sends it through Gmail SMTP.

Add these repository secrets before the first run:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL` (for example, `https://telangpuai.com/v1`)
- `OPENAI_MODEL` (for example, `gpt-6-astra`)
- `GMAIL_ADDRESS` (the Gmail account used to send the message)
- `GMAIL_APP_PASSWORD` (a Google app password, not the normal Gmail password)
- `NEWS_TO` (the recipient email address)

Use the **Run workflow** button once to test the setup before relying on the daily schedule.
