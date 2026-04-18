# Forum Post Getter Skill

This skill provides tools and guidance for fetching and analyzing content from Xenforo forum threads.

## Files

- **SKILL.md** — Skill definition with workflow description
- **get_forum_posts.py** — Python script to fetch and parse forum threads

## Setup

### Requirements

- Python 3.8 or later
- `requests` library
- `beautifulsoup4` library

### Installation

```bash
pip install requests beautifulsoup4
```

## Quick Start

```bash
python get_forum_posts.py "https://forums.example.com/threads/topic-title.123/"
```

## Output Format

The script returns JSON with an array of post objects:

```json
[
  {
    "username": "forum_user",
    "content": "Post text content...",
    "post_id": "post_12345",
    "timestamp": "2024-01-15T10:30:00Z"
  }
]
```

## Customization

Edit `get_forum_posts.py` to:
- Change CSS selectors for different Xenforo versions
- Add additional metadata extraction
- Handle pagination for large threads
- Save output to file instead of stdout

## Notes

- The script respects standard web scraping practices with delays
- Some forums may require authentication — add cookies/auth headers as needed
- HTML structure varies by Xenforo theme — CSS selectors may need adjustment
