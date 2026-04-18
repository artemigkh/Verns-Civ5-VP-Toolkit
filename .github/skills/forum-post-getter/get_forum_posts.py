#!/usr/bin/env python3
"""
Forum Post Getter - Extract the first post from a Xenforo forum thread
Fetches a thread URL, parses the first post, and returns structured data
"""

import json
import sys
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin
import logging

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: Required packages not found.")
    print("Install with: pip install requests beautifulsoup4")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class ForumPostGetter:
    """Fetches and parses the first post from a Xenforo forum thread"""
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch_thread(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch and parse a forum thread"""
        try:
            logger.info(f"Fetching thread: {url}")
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            logger.error(f"Failed to fetch URL: {e}")
            return None
    
    def extract_first_post(self, soup: BeautifulSoup) -> Optional[Dict]:
        """Extract the first post from parsed HTML"""
        # Look for post containers - finds articles with both 'message' and 'post' classes
        post_elements = soup.find_all('article',
                                     class_=lambda x: x and 'message' in str(x) and 'post' in str(x))

        if not post_elements:
            logger.warning("No posts found. HTML structure may differ from expected Xenforo format.")
            return None

        return self._parse_single_post(post_elements[0])
    
    def _parse_single_post(self, element) -> Optional[Dict]:
        """Parse a single post element"""
        try:
            # Extract username - try h4.username first, then fall back to data-author attribute
            username_el = element.find('h4', class_='username')
            if username_el:
                username = username_el.get_text(strip=True)
            else:
                username = element.get('data-author', 'Unknown')
            
            # Extract post content from message-main div
            msg_main = element.find('div', class_='message-main')
            content = msg_main.get_text(strip=True) if msg_main else ""
            
            # Extract post ID from data-content attribute or id attribute
            post_id = element.get('data-content', element.get('id', ''))
            
            # Extract timestamp if available
            timestamp_el = element.find('time')
            timestamp = timestamp_el.get('datetime', '') if timestamp_el else ""
            
            return {
                'username': username,
                'content': content,
                'post_id': post_id,
                'timestamp': timestamp
            }
        except Exception as e:
            logger.warning(f"Error parsing post: {e}")
            return None
    
    def get_first_post(self, url: str) -> Optional[Dict]:
        """Main method: fetch and return the first post"""
        soup = self.fetch_thread(url)
        if not soup:
            return None
        return self.extract_first_post(soup)


def main():
    if len(sys.argv) < 2:
        print("Usage: python get_forum_posts.py <thread_url>")
        print("Example: python get_forum_posts.py 'https://forums.example.com/threads/topic.123/'")
        sys.exit(1)
    
    thread_url = sys.argv[1]

    getter = ForumPostGetter()
    post = getter.get_first_post(thread_url)

    # Output as JSON
    print(json.dumps(post, indent=2))

    return 0 if post else 1


if __name__ == '__main__':
    sys.exit(main())
