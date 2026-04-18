---
name: forum-post-getter
description: "Use when: fetching forum post content for textual analysis, retrieving Xenforo thread data, parsing user posts, or analyzing forum discussions. Helps retrieve and parse the first post of a forum thread to extract structured post data."
---

# Forum Post Getter Skill

This skill provides a workflow for fetching and analyzing the first post of a Xenforo forum thread. It enables extracting the opening post content for further analysis, processing, and archival.

## When to Use

- Retrieving the first post from a forum thread for textual analysis
- Extracting structured forum data (user, post content, metadata) for the opening post
- Building tools that analyze the original post of a discussion thread
- Archiving or processing forum thread opening posts

## Workflow

### Step 1: Provide Thread URL
The user provides a Xenforo thread URL to analyze.

**Example:** `https://forums.civfanatics.com/threads/10-041-hero-worship-rework.702632/`

### Step 2: Fetch and Parse Thread
The skill uses the provided script to:
- Download the thread HTML
- Parse the first post in the thread
- Extract user information and post content

### Step 3: Return Structured Data
Returns a single JSON object containing:
- `username`: The author of the post
- `content`: The post content (plain text or HTML)
- `post_id`: Unique post identifier
- `timestamp`: When the post was made (if available)

## Usage

1. Call the fetch script with your thread URL:
   ```bash
   python get_forum_posts.py "https://forums.example.com/threads/topic.123/"
   ```

2. The script outputs a single JSON object with the first post:
   ```json
   {
     "username": "user1",
     "content": "Post content here...",
     "post_id": "123",
     "timestamp": "2024-01-15T10:30:00Z"
   }
   ```

## See Also

- Bundled script: `get_forum_posts.py` — Main fetching and parsing script
- Requires: Python 3.8+, requests, beautifulsoup4
