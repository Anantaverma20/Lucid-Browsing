"""
Web scraper using Browserbase to extract article information from URLs.
Removes ads and extracts: article links, images, titles, and content.
Stores results in Redis and returns JSON.
"""

import os
import json
import hashlib
import sys
import asyncio
import traceback
from typing import Dict, List, Optional
from urllib.parse import urljoin
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from browserbase import Browserbase
import redis
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

class WebScraper:
    def __init__(self):
        self.browserbase_api_key = os.getenv("BROWSERBASE_API_KEY")
        self.browserbase_project_id = os.getenv("BROWSERBASE_PROJECT_ID")
        
        # Initialize Browserbase
        self.bb = Browserbase(api_key=self.browserbase_api_key)
        
        # Initialize Redis
        # Try Redis URL first (for Redis Cloud), then fall back to individual params
        redis_url = os.getenv("REDIS_URL")
        self.redis_client = None
        
        try:
            if redis_url:
                # Use Redis URL (for Redis Cloud)
                self.redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True
                )
                self.redis_client.ping()  # Test connection
                print("Redis connection successful (Redis Cloud)")
            else:
                # Use individual connection parameters (for local Redis)
                redis_host = os.getenv("REDIS_HOST")
                redis_port = os.getenv("REDIS_PORT")
                
                # Only try to connect if Redis host is explicitly configured
                if redis_host and redis_host != "localhost":
                    redis_port = int(redis_port) if redis_port else 6379
                    redis_password = os.getenv("REDIS_PASSWORD", "")
                    redis_db = int(os.getenv("REDIS_DB", 0))
                    
                    redis_kwargs = {
                        "host": redis_host,
                        "port": redis_port,
                        "db": redis_db,
                        "decode_responses": True
                    }
                    if redis_password:
                        redis_kwargs["password"] = redis_password
                    
                    self.redis_client = redis.Redis(**redis_kwargs)
                    self.redis_client.ping()  # Test connection
                    print("Redis connection successful (Local)")
                else:
                    print("Redis not configured - caching disabled")
                    print("To enable Redis caching, add REDIS_URL to .env file")
        except Exception as e:
            print(f"Warning: Redis connection failed: {e}")
            print("Continuing without Redis caching...")
            self.redis_client = None
    
    def _get_cache_key(self, url: str) -> str:
        """Generate a cache key for the URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return f"scrape:{url_hash}"
    
    def _check_cache(self, url: str) -> Optional[Dict]:
        """Check if URL is cached in Redis."""
        if not self.redis_client:
            return None
        
        try:
            cache_key = self._get_cache_key(url)
            cached_data = self.redis_client.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            print(f"Cache check error: {e}")
        return None
    
    def _save_to_cache(self, url: str, data: Dict):
        """Save scraped data to Redis cache."""
        if not self.redis_client:
            return
        
        try:
            cache_key = self._get_cache_key(url)
            # Cache for 24 hours (86400 seconds)
            self.redis_client.setex(
                cache_key,
                86400,
                json.dumps(data, ensure_ascii=False)
            )
        except Exception as e:
            print(f"Cache save error: {e}")
    
    def _is_ad_element(self, element) -> bool:
        """Check if an element is likely an ad."""
        # Check if element is None or doesn't have get method
        if element is None or not hasattr(element, 'get'):
            return False
        
        # Common ad-related class names and IDs
        ad_indicators = [
            'ad', 'advertisement', 'ads', 'advert', 'sponsored',
            'promo', 'promotion', 'banner-ad', 'sidebar-ad',
            'google-ad', 'ad-container', 'ad-wrapper', 'ad-box'
        ]
        
        try:
            # Check class names
            classes = element.get('class', [])
            if isinstance(classes, str):
                classes = [classes]
            
            class_str = ' '.join(classes).lower()
            id_str = element.get('id', '').lower()
            
            for indicator in ad_indicators:
                if indicator in class_str or indicator in id_str:
                    return True
        except Exception:
            # If any error occurs, assume it's not an ad
            return False
        
        return False
    
    def _remove_ads(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Remove ad elements from the HTML."""
        if not soup:
            return soup
        
        # Find and remove common ad containers
        ad_selectors = [
            '[class*="ad"]',
            '[id*="ad"]',
            '[class*="advertisement"]',
            '[id*="advertisement"]',
            '[class*="sponsored"]',
            '[id*="sponsored"]',
            '[class*="promo"]',
            'iframe[src*="ads"]',
            'iframe[src*="advertisement"]',
        ]
        
        for selector in ad_selectors:
            try:
                elements = soup.select(selector)
                if not elements:
                    continue
                
                for element in elements:
                    if element is None:
                        continue
                    
                    if self._is_ad_element(element):
                        try:
                            element.decompose()
                        except Exception:
                            # If decompose fails, try to remove parent or skip
                            pass
            except Exception:
                # If selector fails, continue to next selector
                continue
        
        # Remove script and style tags (ads often loaded via scripts)
        try:
            for script in soup.find_all(['script', 'style', 'noscript']):
                if script is not None:
                    try:
                        script.decompose()
                    except Exception:
                        pass
        except Exception:
            pass
        
        return soup
    
    def _extract_article_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract article links from the page with associated images."""
        article_links = []
        
        if not soup:
            return article_links
        
        seen_urls = set()
        
        # More comprehensive link extraction - check all links on the page
        try:
            # Get all links from the page
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                if link is None:
                    continue
                
                try:
                    href = link.get('href', '') if hasattr(link, 'get') else ''
                    if not href:
                        continue
                    
                    # Skip common non-content links
                    skip_patterns = [
                        '#', 'javascript:', 'mailto:', 'tel:', 
                        '/#', 'void(0)', 'void(0);'
                    ]
                    if any(pattern in href.lower() for pattern in skip_patterns):
                        continue
                    
                    # Convert relative URLs to absolute
                    absolute_url = urljoin(base_url, href)
                    
                    # Skip if already seen, same page, or external domains that are clearly not content
                    if absolute_url in seen_urls:
                        continue
                    
                    if absolute_url == base_url or absolute_url == base_url + '/':
                        continue
                    
                    # Get link text
                    try:
                        text = link.get_text(strip=True) if hasattr(link, 'get_text') else ''
                    except Exception:
                        text = ''
                    
                    # Also try to get text from child elements (for styled links)
                    if not text or len(text) < 3:
                        try:
                            # Try to find text in child elements
                            child_text = link.find(string=True, recursive=True)
                            if child_text:
                                text = str(child_text).strip()
                        except Exception:
                            pass
                    
                    # Get title attribute as fallback
                    if not text or len(text) < 3:
                        text = link.get('title', '') if hasattr(link, 'get') else ''
                    
                    # Skip navigation/social/media links
                    skip_classes = ['nav', 'menu', 'social', 'share', 'footer', 'header', 'logo']
                    link_classes = link.get('class', []) if hasattr(link, 'get') else []
                    if isinstance(link_classes, str):
                        link_classes = [link_classes]
                    class_str = ' '.join(link_classes).lower()
                    
                    if any(skip in class_str for skip in skip_classes):
                        continue
                    
                    # Find associated image for this link
                    image_url = ""
                    try:
                        # Look for image within the link or in parent/sibling elements
                        img_in_link = link.find('img')
                        if img_in_link:
                            src = (img_in_link.get('src') or 
                                  img_in_link.get('data-src') or 
                                  img_in_link.get('data-lazy-src') or 
                                  img_in_link.get('data-original'))
                            if src and not src.startswith('data:'):
                                image_url = urljoin(base_url, src)
                        else:
                            # Check parent element for images
                            parent = link.parent
                            if parent:
                                parent_img = parent.find('img')
                                if parent_img:
                                    src = (parent_img.get('src') or 
                                          parent_img.get('data-src') or 
                                          parent_img.get('data-lazy-src'))
                                    if src and not src.startswith('data:'):
                                        image_url = urljoin(base_url, src)
                    except Exception:
                        pass
                    
                    # Only add if we have meaningful text or it looks like a content link
                    if text and len(text) > 3:
                        article_links.append({
                            "url": absolute_url,
                            "title": text[:200],
                            "image_url": image_url
                        })
                        seen_urls.add(absolute_url)
                    elif '/event' in absolute_url.lower() or '/article' in absolute_url.lower() or '/post' in absolute_url.lower():
                        # Include event/article/post links even without text
                        article_links.append({
                            "url": absolute_url,
                            "title": text[:200] if text else "Link",
                            "image_url": image_url
                        })
                        seen_urls.add(absolute_url)
                        
                except Exception:
                    continue
                    
        except Exception as e:
            print(f"Error extracting links: {e}")
        
        return article_links[:100]  # Increased limit to 100 links
    
    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract images from the page."""
        images = []
        seen_srcs = set()
        
        if not soup:
            return images
        
        # Get all img tags
        img_tags = soup.find_all('img')
        
        # Also check for images in background-image CSS or data attributes
        all_elements = soup.find_all(True)  # Get all elements
        
        for img in img_tags:
            if img is None:
                continue
            
            # Try multiple src attributes (for lazy loading)
            src = (img.get('src') or 
                   img.get('data-src') or 
                   img.get('data-lazy-src') or 
                   img.get('data-original') or
                   img.get('data-image'))
            
            if not src:
                continue
            
            # Skip data URLs and very small images
            if src.startswith('data:'):
                continue
            
            # Convert relative URLs to absolute
            absolute_url = urljoin(base_url, src)
            
            if absolute_url in seen_srcs:
                continue
            
            # Skip very small images (likely icons/sprites) - but be more lenient
            width = img.get('width') if img else None
            height = img.get('height') if img else None
            if width and height:
                try:
                    w, h = int(width), int(height)
                    if w < 30 or h < 30:  # More lenient threshold
                        continue
                except (ValueError, TypeError):
                    pass
            
            # Skip common icon/logo patterns
            src_lower = absolute_url.lower()
            skip_patterns = ['icon', 'logo', 'sprite', 'avatar', 'favicon']
            if any(pattern in src_lower for pattern in skip_patterns):
                # Only skip if it's clearly an icon (small or in specific paths)
                if '/icon' in src_lower or '/logo' in src_lower:
                    continue
            
            alt_text = img.get('alt', '') if img else ''
            # Also try title attribute
            if not alt_text:
                alt_text = img.get('title', '') if img else ''
            
            images.append({
                "url": absolute_url,
                "alt": alt_text[:200] if alt_text else ""
            })
            seen_srcs.add(absolute_url)
        
        return images[:50]  # Increased limit to 50 images
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract page title."""
        if not soup:
            return "Untitled"
        
        # Try multiple sources for title
        title = None
        
        # Try og:title
        try:
            og_title = soup.find('meta', attrs={'property': 'og:title'})
            if og_title and hasattr(og_title, 'get'):
                title = og_title.get('content', '').strip()
        except Exception:
            pass
        
        # Try title tag
        if not title:
            try:
                title_tag = soup.find('title')
                if title_tag:
                    title = title_tag.get_text(strip=True)
            except Exception:
                pass
        
        # Try h1
        if not title:
            try:
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text(strip=True)
            except Exception:
                pass
        
        return title or "Untitled"
    
    def _extract_content(self, soup: BeautifulSoup) -> str:
        """Extract main content from the page."""
        if not soup:
            return ""
        
        # Try to find main content areas with more comprehensive selectors
        content_selectors = [
            'article',
            'main',
            '[role="main"]',
            '.content',
            '.post-content',
            '.entry-content',
            '.article-content',
            '.story-content',
            '[class*="content"]',
            '[class*="main"]',
            '[class*="event"]',
            '[class*="card"]',
            '[class*="item"]',
        ]
        
        content_text = ""
        
        for selector in content_selectors:
            try:
                elements = soup.select(selector)
                for element in elements:
                    if element is None:
                        continue
                    
                    # Remove ad elements from content
                    try:
                        for ad in element.find_all(class_=lambda x: x and 'ad' in x.lower()):
                            ad.decompose()
                    except Exception:
                        pass
                    
                    try:
                        text = element.get_text(separator=' ', strip=True)
                        if len(text) > len(content_text):
                            content_text = text
                    except Exception:
                        pass
            except Exception:
                continue
        
        # If no main content found, get body text but filter out navigation/menus
        if not content_text or len(content_text) < 100:
            try:
                body = soup.find('body')
                if body:
                    # Remove navigation, header, footer, script, style
                    for tag in body.find_all(['nav', 'header', 'footer', 'aside', 'script', 'style', 'noscript']):
                        try:
                            tag.decompose()
                        except Exception:
                            pass
                    
                    content_text = body.get_text(separator=' ', strip=True)
            except Exception:
                pass
        
        # Clean up whitespace and remove excessive newlines
        content_text = ' '.join(content_text.split())
        
        # Remove very short content that's likely not meaningful
        if len(content_text) < 50:
            content_text = ""
        
        return content_text[:15000]  # Increased limit to 15000 characters
    
    async def scrape(self, url: str) -> Dict:
        """Scrape a URL and return structured data."""
        # Check cache first
        cached_data = self._check_cache(url)
        if cached_data:
            print(f"Returning cached data for {url}")
            return cached_data
        
        print(f"Scraping {url}...")
        
        async def run_scraper():
            try:
                # Create a Browserbase session
                try:
                    session = self.bb.sessions.create(project_id=self.browserbase_project_id)
                except Exception as e:
                    raise Exception(f"Failed to create Browserbase session: {str(e)}")
                
                if not session:
                    raise Exception("Browserbase session creation returned None")
                
                # Try different ways to access connect_url (snake_case and camelCase)
                connect_url = None
                try:
                    if hasattr(session, 'connect_url') and session.connect_url:
                        connect_url = session.connect_url
                    elif hasattr(session, 'connectUrl') and session.connectUrl:
                        connect_url = session.connectUrl
                    elif isinstance(session, dict) and session:
                        connect_url = session.get('connect_url') or session.get('connectUrl')
                    else:
                        # Try to get it as an attribute or from a response object
                        try:
                            if hasattr(session, 'data') and session.data:
                                data = session.data
                                if isinstance(data, dict) and data:
                                    connect_url = data.get('connect_url') or data.get('connectUrl')
                                elif hasattr(data, 'connect_url') and data.connect_url:
                                    connect_url = data.connect_url
                                elif hasattr(data, 'connectUrl') and data.connectUrl:
                                    connect_url = data.connectUrl
                        except Exception:
                            pass
                except AttributeError as e:
                    print(f"Error accessing session attributes: {e}")
                    connect_url = None
                
                if not connect_url:
                    # Debug: print what we got
                    try:
                        session_attrs = [attr for attr in dir(session) if not attr.startswith('_')]
                        session_info = f"Session type: {type(session)}, attributes: {session_attrs[:10]}"
                    except:
                        session_info = f"Session type: {type(session)}"
                    raise Exception(f"Failed to get connect URL from Browserbase session. {session_info}")
                
                # Connect to the remote browser using async Playwright
                async with async_playwright() as playwright:
                    chromium = playwright.chromium
                    browser = await chromium.connect_over_cdp(connect_url)
                    
                    if not browser:
                        raise Exception("Failed to connect to browser via CDP")
                    
                    # Get or create context and page
                    if browser.contexts and len(browser.contexts) > 0:
                        context = browser.contexts[0]
                        if context.pages and len(context.pages) > 0:
                            page = context.pages[0]
                        else:
                            page = await context.new_page()
                    else:
                        context = await browser.new_context()
                        page = await context.new_page()
                    
                    if not page:
                        raise Exception("Failed to get or create page")
                    
                    # Navigate to the URL
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    
                    # Wait for page to be fully loaded and JavaScript to execute
                    await page.wait_for_load_state("networkidle", timeout=60000)
                    
                    # Wait longer for dynamic content to load (React/SPA sites need more time)
                    await page.wait_for_timeout(8000)
                    
                    # Scroll to trigger lazy loading of images and content
                    await page.evaluate("""
                        async () => {
                            await new Promise((resolve) => {
                                let totalHeight = 0;
                                const distance = 100;
                                const timer = setInterval(() => {
                                    const scrollHeight = document.body.scrollHeight;
                                    window.scrollBy(0, distance);
                                    totalHeight += distance;
                                    
                                    if(totalHeight >= scrollHeight || totalHeight > 10000){
                                        clearInterval(timer);
                                        resolve();
                                    }
                                }, 100);
                            });
                        }
                    """)
                    
                    # Wait a bit more after scrolling for content to load
                    await page.wait_for_timeout(5000)
                    
                    # Try to wait for common content selectors to appear
                    try:
                        # Wait for at least some content to appear
                        await page.wait_for_selector('body', timeout=10000)
                    except Exception:
                        pass
                    
                    # Get page title directly from Playwright (more reliable)
                    page_title = await page.title()
                    
                    # Get page HTML and timestamp before closing
                    html_content = await page.content()
                    if not html_content:
                        raise Exception("Failed to get page content")
                    
                    # Also get text content directly from Playwright as fallback
                    try:
                        body_text = await page.evaluate("""
                            () => {
                                // Remove script, style, nav, header, footer
                                const elementsToRemove = document.querySelectorAll('script, style, noscript, nav, header, footer');
                                elementsToRemove.forEach(el => el.remove());
                                
                                // Get main content areas
                                const mainContent = document.querySelector('main') || 
                                                   document.querySelector('article') || 
                                                   document.querySelector('[role="main"]') ||
                                                   document.body;
                                
                                return mainContent ? mainContent.innerText : document.body.innerText;
                            }
                        """)
                    except Exception:
                        body_text = ""
                    
                    # Get all links directly from Playwright with associated images
                    try:
                        page_links = await page.evaluate("""
                            () => {
                                const links = [];
                                const linkElements = document.querySelectorAll('a[href]');
                                const seen = new Set();
                                
                                linkElements.forEach(link => {
                                    const href = link.getAttribute('href');
                                    if (!href || href.startsWith('#') || href.startsWith('javascript:')) {
                                        return;
                                    }
                                    
                                    const absoluteUrl = new URL(href, window.location.href).href;
                                    if (seen.has(absoluteUrl)) return;
                                    seen.add(absoluteUrl);
                                    
                                    const text = link.innerText.trim() || link.textContent.trim() || link.getAttribute('title') || '';
                                    
                                    // Find associated image
                                    let imageUrl = '';
                                    const imgInLink = link.querySelector('img');
                                    if (imgInLink) {
                                        const src = imgInLink.src || imgInLink.getAttribute('data-src') || imgInLink.getAttribute('data-lazy-src');
                                        if (src && !src.startsWith('data:')) {
                                            imageUrl = new URL(src, window.location.href).href;
                                        }
                                    } else {
                                        // Check parent for images
                                        const parent = link.parentElement;
                                        if (parent) {
                                            const parentImg = parent.querySelector('img');
                                            if (parentImg) {
                                                const src = parentImg.src || parentImg.getAttribute('data-src');
                                                if (src && !src.startsWith('data:')) {
                                                    imageUrl = new URL(src, window.location.href).href;
                                                }
                                            }
                                        }
                                    }
                                    
                                    if (text.length > 3 || href.includes('/event') || href.includes('/article') || href.includes('/post')) {
                                        links.push({
                                            url: absoluteUrl, 
                                            title: text.substring(0, 200),
                                            image_url: imageUrl
                                        });
                                    }
                                });
                                
                                return links;
                            }
                        """)
                    except Exception:
                        page_links = []
                    
                    scraped_at = await page.evaluate("() => new Date().toISOString()")
                    
                    # Close browser
                    await browser.close()
                
                # Use Playwright-extracted data as primary (works better for JS-heavy sites)
                # Fallback to BeautifulSoup parsing if Playwright extraction failed
                
                # Use page_title from Playwright if available
                final_title = page_title if page_title and page_title != "Untitled" else None
                final_links = page_links if page_links else []
                final_content = body_text if body_text else ""
                
                # Parse HTML with BeautifulSoup as fallback/enhancement
                soup = None
                try:
                    soup = BeautifulSoup(html_content, 'lxml')
                except Exception:
                    pass
                
                # If Playwright extraction didn't get much, try BeautifulSoup
                if not final_title or final_title == "Untitled":
                    if soup:
                        final_title = self._extract_title(soup)
                
                if not final_links or len(final_links) == 0:
                    if soup:
                        final_links = self._extract_article_links(soup, url)
                
                # Ensure all links have image_url field (add empty string if missing)
                for link in final_links:
                    if 'image_url' not in link:
                        link['image_url'] = ''
                
                if not final_content or len(final_content) < 100:
                    if soup:
                        # Remove ads before extracting content
                        soup = self._remove_ads(soup)
                        soup_content = self._extract_content(soup)
                        # Use BeautifulSoup content if it's longer/better
                        if len(soup_content) > len(final_content):
                            final_content = soup_content
                
                # Ensure we have at least something
                if not final_title or final_title == "Untitled":
                    final_title = page_title or "Untitled"
                
                if not final_content:
                    final_content = body_text or ""
                
                result = {
                    "url": url,
                    "title": final_title,
                    "article_links": final_links[:100],  # Limit to 100
                    "content": final_content[:15000],  # Limit content length
                    "scraped_at": scraped_at
                }
                
                # Save to cache
                self._save_to_cache(url, result)
                
                return result
                
            except Exception as e:
                print(f"Error during scraping: {e}")
                traceback.print_exc()
                raise
        
        # Run the scraper
        result = await run_scraper()
        return result


async def main():
    """Main function to handle user input."""
    scraper = WebScraper()
    
    # Get URL from user
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = input("\nEnter URL to scrape: ").strip()
    
    if not url:
        print("Error: URL is required")
        return
    
    # Ensure URL has protocol
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    print(f"\nScraping: {url}")
    print("Using Browserbase for browser automation...")
    
    try:
        # Scrape the URL (this uses Browserbase and saves to Redis)
        result = await scraper.scrape(url)
        
        # Create output directory if it doesn't exist
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        
        # Generate filename from URL and timestamp
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"scrape_{timestamp}_{url_hash}.json"
        filepath = output_dir / filename
        
        # Save JSON to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print("\n" + "="*50)
        print("SCRAPING COMPLETE")
        print("="*50)
        print(f"Title: {result.get('title', 'N/A')}")
        print(f"Article Links Found: {len(result.get('article_links', []))}")
        print(f"Content Length: {len(result.get('content', ''))} characters")
        print(f"\n✅ Results saved to: {filepath}")
        print(f"✅ Results cached in Redis (24 hours)")
        print("="*50)
        
        # Optionally show a preview of the JSON
        print("\nJSON Preview:")
        print(json.dumps(result, indent=2, ensure_ascii=False)[:500] + "...")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
