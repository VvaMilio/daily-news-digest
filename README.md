# Daily global news digest

This workflow runs every day at 08:00 Asia/Shanghai. It sends two separate emails through Gmail SMTP: one with 5 global hot news items and 5 AI news items, and one with 5 popular GitHub projects and 5 AI-related GitHub projects.

Add these repository secrets before the first run:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL` (for example, `https://telangpuai.com/v1`)
- `OPENAI_MODEL` (for example, `gpt-6-astra`)
- `GMAIL_ADDRESS` (the Gmail account used to send the message)
- `GMAIL_APP_PASSWORD` (a Google app password, not the normal Gmail password)
- `NEWS_TO` (one or more recipient email addresses separated by commas, semicolons, or new lines)

GitHub Actions supplies a temporary `GITHUB_TOKEN` automatically to read GitHub's public repository search API. Use the **Run workflow** button once to test the setup before relying on the daily schedule.
