# Daily global news digest

This workflow runs every day at 12:00 Asia/Shanghai, uses the OpenAI Responses API with web search to prepare a Chinese global-news digest, and sends it through Resend.

Add these repository secrets before the first run:

- `OPENAI_API_KEY`
- `OPENAI_MODEL` (for example, `gpt-5.5`)
- `RESEND_API_KEY`
- `NEWS_TO` (the recipient email address)
- `NEWS_FROM` (a sender address verified with Resend)

Use the **Run workflow** button once to test the setup before relying on the daily schedule.
