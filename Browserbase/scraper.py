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
from urllib.parse import urljoin, urlparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from browserbase import Browserbase
import redis
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

# Load environment variables
load_dotenv()

class WebScraper:
    def __init__(self):
        self.browserbase_api_key = os.getenv("BROWSERBASE_API_KEY")
        self.browserbase_project_id = os.getenv("BROWSERBASE_PROJECT_ID")
        
        # Initialize Browserbase
        self.bb = Browserbase(api_key=self.browserbase_api_key)
        
        # Initialize OpenAI client (for LLM-based ad selector generation)
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openai_client = None
        if self.openai_api_key:
            self.openai_client = AsyncOpenAI(api_key=self.openai_api_key)
            print("OpenAI client initialized for LLM-based ad removal")
        else:
            print("Warning: OPENAI_API_KEY not found - LLM-based ad removal disabled")
        
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
    
    def _should_block_request(self, request_url: str, resource_type: str) -> bool:
        """Check if a network request should be blocked (ads, trackers, etc.)."""
        if not request_url:
            return False
        
        request_url_lower = request_url.lower()
        
        # Block ad-related domains and paths
        ad_domains = [
            'doubleclick.net', 'googleadservices.com', 'googlesyndication.com',
            'google-analytics.com', 'googletagmanager.com', 'facebook.com/tr',
            'adsafeprotected.com', 'adnxs.com', 'adsrvr.org', 'adtechus.com',
            'amazon-adsystem.com', 'advertising.com', 'adform.net', 'adzerk.net',
            'outbrain.com', 'taboola.com', 'criteo.com', 'media.net',
            'adsystem', 'adserver', 'advertising', 'advertisement',
            'adservice', 'adtech', 'advertising', 'advert', 'ads.'
        ]
        
        # Block tracking/analytics
        tracking_domains = [
            'analytics', 'tracking', 'tracker', 'pixel', 'beacon',
            'facebook.net', 'facebook.com/tr', 'scorecardresearch.com',
            'quantserve.com', '2mdn.net', 'moatads.com'
        ]
        
        # Block social media widgets/embeds
        social_domains = [
            'facebook.com/plugins', 'twitter.com/widgets', 'instagram.com/embed',
            'linkedin.com/embed', 'pinterest.com/pin'
        ]
        
        # Block fonts and images from ad domains (optional - can be commented out if needed)
        # if resource_type in ['font', 'image']:
        #     for domain in ad_domains:
        #         if domain in request_url_lower:
        #             return True
        
        # Block scripts, stylesheets, and iframes from ad/tracking domains
        if resource_type in ['script', 'stylesheet', 'iframe', 'fetch', 'xhr']:
            for domain in ad_domains + tracking_domains + social_domains:
                if domain in request_url_lower:
                    return True
        
        # Block common ad URL patterns
        ad_patterns = [
            '/ads/', '/ad/', '/advertisement/', '/advert/', '/sponsor/',
            '/tracking/', '/track/', '/pixel', '/beacon', '/analytics',
            '?ad=', '&ad=', '/ads.', '/ad.', 'banner', 'popup'
        ]
        
        for pattern in ad_patterns:
            if pattern in request_url_lower:
                return True
        
        return False
    
    def _filter_ad_links(self, links: List[Dict]) -> List[Dict]:
        """Filter out ad-related links that slipped through network blocking."""
        if not links:
            return links
        
        # Patterns that indicate ad/sponsored content in URLs
        ad_url_patterns = [
            '/ad/', '/ads/', '/advertisement/', '/advert/', '/sponsor/',
            '/promo/', '/promotion/', '/affiliate/', '/click/', '/track/',
            '/redirect/', '/out/', '/go/', '/partner/', '/ref=',
            'doubleclick', 'googlesyndication', 'googleadservices',
            'facebook.com/tr', 'amazon-adsystem', 'taboola', 'outbrain',
            'criteo', 'adnxs', 'advertising', 'banner', 'popup',
            'sponsored', 'promoted', 'paid-post'
        ]
        
        # Patterns in link titles that indicate ads
        ad_title_patterns = [
            'advertisement', 'sponsored', 'promoted', 'paid post',
            'partner content', 'ad:', '[ad]', '(ad)', 'promo',
            'affiliate', 'shop now', 'buy now', 'special offer',
            'limited time', 'click here'
        ]
        
        filtered_links = []
        for link in links:
            url_lower = link.get('url', '').lower()
            title_lower = link.get('title', '').lower()
            
            # Check if URL contains ad patterns
            is_ad_url = any(pattern in url_lower for pattern in ad_url_patterns)
            
            # Check if title contains ad patterns
            is_ad_title = any(pattern in title_lower for pattern in ad_title_patterns)
            
            # Keep link only if it's not an ad
            if not is_ad_url and not is_ad_title:
                filtered_links.append(link)
        
        return filtered_links
    
    async def _remove_ads(self, soup: BeautifulSoup, url: str = "") -> BeautifulSoup:
        """Remove ad elements from the HTML using rule-based and LLM-generated selectors."""
        if not soup:
            return soup
        
        # Step 1: Apply LLM-generated selectors (if OpenAI is configured)
        if self.openai_client and url:
            soup = await self._remove_ads_with_llm_selectors(soup, url)
        
        # Step 2: Apply rule-based selectors (fallback and baseline)
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
    
    def _extract_html_structure_sample(self, soup: BeautifulSoup, max_length: int = 3000) -> str:
        """Extract a sample of HTML structure (classes, IDs, tags) for LLM analysis."""
        if not soup:
            return ""
        
        structure_parts = []
        
        # Extract unique class names and IDs
        classes = set()
        ids = set()
        tags = set()
        
        try:
            # Get all elements with classes or IDs
            for element in soup.find_all(True):  # All elements
                if element is None:
                    continue
                
                # Get classes
                element_classes = element.get('class', [])
                if isinstance(element_classes, list):
                    classes.update(element_classes)
                elif isinstance(element_classes, str):
                    classes.add(element_classes)
                
                # Get IDs
                element_id = element.get('id', '')
                if element_id:
                    ids.add(element_id)
                
                # Get tag names
                if hasattr(element, 'name') and element.name:
                    tags.add(element.name)
                
                # Limit to avoid too much data
                if len(classes) > 100 or len(ids) > 100:
                    break
        except Exception:
            pass
        
        # Build structure summary
        structure_parts.append(f"Tags found: {', '.join(sorted(list(tags))[:50])}")
        structure_parts.append(f"\nClasses found: {', '.join(sorted(list(classes))[:100])}")
        structure_parts.append(f"\nIDs found: {', '.join(sorted(list(ids))[:50])}")
        
        structure = '\n'.join(structure_parts)
        
        # Limit total length
        if len(structure) > max_length:
            structure = structure[:max_length] + "..."
        
        return structure
    
    async def _llm_generate_ad_selectors(self, html_structure: str, domain: str) -> List[str]:
        """Use OpenAI GPT-3.5-turbo to generate CSS selectors for ad removal."""
        if not self.openai_client:
            return []
        
        try:
            prompt = f"""Analyze this HTML structure from {domain} and generate CSS selectors to identify and remove advertisement elements.

HTML Structure:
{html_structure}

Generate CSS selectors (like '[class*="ad"]', '#ad-container', etc.) that would match:
1. Advertisement containers
2. Sponsored content
3. Promotional banners
4. Ad-related iframes
5. Marketing widgets

Return ONLY a JSON array of CSS selector strings, nothing else. Example format:
["[class*='ad']", "[id*='advertisement']", ".sponsored", "#ad-container"]

Selectors:"""

            response = await self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",  # Cheapest and fast model
                messages=[
                    {"role": "system", "content": "You are a CSS selector expert. Return only valid CSS selectors as a JSON array."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temperature for more consistent results
                max_tokens=500,  # Limit tokens to keep cost low
            )
            
            # Extract selectors from response
            content = response.choices[0].message.content.strip()
            
            # Try to parse JSON array
            try:
                # Remove markdown code blocks if present
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.strip()
                
                selectors = json.loads(content)
                if isinstance(selectors, list):
                    # Validate selectors are strings
                    selectors = [s for s in selectors if isinstance(s, str) and len(s) > 0]
                    print(f"Generated {len(selectors)} ad selectors using LLM for {domain}")
                    return selectors
            except json.JSONDecodeError:
                # Try to extract selectors from text
                import re
                selector_pattern = r'["\']([^"\']+)["\']'
                selectors = re.findall(selector_pattern, content)
                if selectors:
                    print(f"Extracted {len(selectors)} ad selectors from LLM response for {domain}")
                    return selectors
            
            print(f"Warning: Could not parse LLM response for {domain}")
            return []
            
        except Exception as e:
            print(f"Error generating LLM selectors for {domain}: {e}")
            return []
    
    def _get_domain_from_url(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except Exception:
            return "unknown"
    
    async def _get_ad_selectors_for_domain(self, domain: str, html_structure: str) -> List[str]:
        """Get cached ad selectors for domain, or generate if not cached."""
        if not self.redis_client:
            # If no Redis, generate selectors directly (no caching)
            return await self._llm_generate_ad_selectors(html_structure, domain)
        
        cache_key = f"ad_selectors:{domain}"
        
        try:
            # Check cache first (instant, 0ms latency)
            cached = self.redis_client.get(cache_key)
            if cached:
                selectors = json.loads(cached)
                print(f"Using cached ad selectors for {domain} ({len(selectors)} selectors)")
                return selectors
        except Exception as e:
            print(f"Cache read error for {domain}: {e}")
        
        # Generate if not cached
        selectors = await self._llm_generate_ad_selectors(html_structure, domain)
        
        # Cache for 24 hours (86400 seconds)
        if selectors and self.redis_client:
            try:
                self.redis_client.setex(
                    cache_key,
                    86400,
                    json.dumps(selectors)
                )
                print(f"Cached ad selectors for {domain} (24 hours)")
            except Exception as e:
                print(f"Cache write error for {domain}: {e}")
        
        return selectors
    
    async def _remove_ads_with_llm_selectors(self, soup: BeautifulSoup, url: str) -> BeautifulSoup:
        """Remove ads using LLM-generated selectors (Option 6) - optimized for speed."""
        if not soup or not self.openai_client:
            return soup
        
        try:
            # Add timeout to prevent blocking the main scraping flow
            # If LLM takes too long, skip it and continue
            return await asyncio.wait_for(
                self._remove_ads_with_llm_selectors_impl(soup, url),
                timeout=15.0  # 15 second timeout for LLM operations (increased from 2s)
            )
        except asyncio.TimeoutError:
            print("LLM ad removal timed out after 15s, skipping...")
            return soup
        except Exception as e:
            print(f"Error in LLM ad removal: {e}")
            return soup
    
    async def _remove_ads_with_llm_selectors_impl(self, soup: BeautifulSoup, url: str) -> BeautifulSoup:
        """Implementation of LLM-based ad removal."""
        if not soup or not self.openai_client:
            return soup
        
        try:
            # Extract domain
            domain = self._get_domain_from_url(url)
            
            # Check cache first (instant, 0ms latency)
            cache_key = f"ad_selectors:{domain}"
            llm_selectors = None
            
            if self.redis_client:
                try:
                    cached = self.redis_client.get(cache_key)
                    if cached:
                        llm_selectors = json.loads(cached)
                        print(f"Using cached LLM selectors for {domain} ({len(llm_selectors)} selectors)")
                except Exception:
                    pass
            
            # If not cached, generate in background (non-blocking for first request)
            if not llm_selectors:
                # Extract HTML structure sample (lightweight, ~500-2000 tokens)
                html_structure = self._extract_html_structure_sample(soup, max_length=1500)  # Reduced from 2000
                
                if html_structure:
                    # Try to get selectors, but don't block if it takes too long
                    try:
                        # Use asyncio.wait_for to timeout LLM call if it's slow
                        llm_selectors = await asyncio.wait_for(
                            self._get_ad_selectors_for_domain(domain, html_structure),
                            timeout=12.0  # 12 seconds for LLM call (increased from 2s)
                        )
                    except asyncio.TimeoutError:
                        print(f"LLM selector generation timed out for {domain}, using rule-based removal")
                        llm_selectors = []
                    except Exception as e:
                        print(f"LLM selector generation error for {domain}: {e}")
                        llm_selectors = []
            
            # Apply LLM-generated selectors (fast, synchronous operation)
            if llm_selectors:
                for selector in llm_selectors:
                    try:
                        elements = soup.select(selector)
                        for element in elements:
                            if element is not None:
                                try:
                                    element.decompose()
                                except Exception:
                                    pass
                    except Exception:
                        # Invalid selector, skip
                        continue
            
            return soup
            
        except Exception as e:
            print(f"Error in LLM-based ad removal: {e}")
            # Fall back to regular ad removal
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
    
    async def scrape(self, url: str, refresh_cache: bool = False) -> Dict:
        """Scrape a URL and return structured data."""
        # Check cache first unless refresh is requested
        if refresh_cache and self.redis_client:
            try:
                cache_key = self._get_cache_key(url)
                self.redis_client.delete(cache_key)
                print(f"Cache refreshed for {url}")
            except Exception as e:
                print(f"Cache refresh error: {e}")
        else:
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
                    # Set shorter timeout for CDP connection
                    browser = await chromium.connect_over_cdp(connect_url, timeout=30000)  # 30s instead of default 60s
                    
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
                    
                    # Set default timeout for page actions to 15s (instead of 30s default)
                    page.set_default_timeout(15000)
                    page.set_default_navigation_timeout(30000)  # 30s for navigation
                    
                    if not page:
                        raise Exception("Failed to get or create page")
                    
                    # Set up network-level ad blocking using page.route()
                    # Optimized: Use block list instead of checking every request
                    blocked_patterns = [
                        "*://*doubleclick.net/*",
                        "*://*googlesyndication.com/*",
                        "*://*googleadservices.com/*",
                        "*://*google-analytics.com/*",
                        "*://*googletagmanager.com/*",
                        "*://*facebook.com/tr*",
                        "*://*facebook.net/*",
                        "*://*adsafeprotected.com/*",
                        "*://*adnxs.com/*",
                        "*://*adsrvr.org/*",
                        "*://*adtechus.com/*",
                        "*://*amazon-adsystem.com/*",
                        "*://*advertising.com/*",
                        "*://*adform.net/*",
                        "*://*outbrain.com/*",
                        "*://*taboola.com/*",
                        "*://*criteo.com/*",
                    ]
                    
                    async def route_handler(route):
                        """Optimized route handler - faster blocking."""
                        request = route.request
                        request_url = request.url.lower()
                        
                        # Quick pattern matching (faster than function call)
                        if any(pattern.replace('*://*', '').replace('/*', '') in request_url for pattern in blocked_patterns):
                            await route.abort()
                        elif self._should_block_request(request_url, request.resource_type):
                            await route.abort()
                        else:
                            await route.continue_()
                    
                    # Enable route interception to block ads at network level
                    await page.route("**/*", route_handler)
                    print("Network-level ad blocking enabled (optimized)")
                    
                    # Navigate to the URL with optimized timeout handling
                    try:
                        # Try to navigate with domcontentloaded (faster)
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)  # Reduced from 45s
                    except Exception as e:
                        # If domcontentloaded times out, try with commit (even faster)
                        print(f"Navigation timeout, trying commit state: {e}")
                        try:
                            await page.goto(url, wait_until="commit", timeout=20000)  # Reduced from 30s
                        except Exception:
                            # Last resort: just navigate without waiting much
                            print("Commit state timeout, minimal wait navigation")
                            await page.goto(url, timeout=15000, wait_until="commit")  # Reduced from 20s
                    
                    # Wait for page to be fully loaded with shorter timeout
                    # Use "load" state but don't wait too long
                    try:
                        await page.wait_for_load_state("load", timeout=10000)  # Reduced from 15s to 10s
                    except Exception:
                        # If load state times out, continue anyway (page might be ready)
                        print("Load state timeout, continuing with current page state")
                    
                    # Adaptive wait for dynamic content - check if content is already loaded
                    # This reduces wait time if content loads quickly
                    try:
                        # Check if main content exists (article, main, or body with substantial content)
                        content_ready = await page.evaluate("""
                            () => {
                                const main = document.querySelector('main, article, [role="main"]');
                                const body = document.body;
                                const hasContent = (main && main.innerText.length > 200) || 
                                                  (body && body.innerText.length > 500);
                                return hasContent;
                            }
                        """)
                        
                        if not content_ready:
                            # Only wait if content isn't ready yet
                            await page.wait_for_timeout(1500)  # Reduced from 2s to 1.5s
                        else:
                            # Content already loaded, minimal wait
                            await page.wait_for_timeout(300)  # Reduced from 0.5s to 0.3s
                    except Exception:
                        # Fallback: wait 1.5s if check fails
                        await page.wait_for_timeout(1500)
                    
                    # Instant scroll to bottom (much faster than incremental scrolling)
                    # Only scroll if page is longer than viewport
                    try:
                        await page.evaluate("""
                            () => {
                                const scrollHeight = document.body.scrollHeight;
                                const viewportHeight = window.innerHeight;
                                
                                // Only scroll if content is longer than viewport
                                if (scrollHeight > viewportHeight * 1.5) {
                                    // Instant scroll to bottom to trigger lazy loading
                                    window.scrollTo(0, scrollHeight);
                                    // Small delay for lazy-loaded content
                                    return new Promise(resolve => setTimeout(resolve, 200));  // Reduced from 300ms
                                }
                                return Promise.resolve();
                            }
                        """)
                    except Exception:
                        # If scroll fails, continue anyway
                        pass
                    
                    # Minimal wait after scroll (reduced from 0.5s to 0.3s)
                    await page.wait_for_timeout(300)
                    
                    # Extract data in parallel for better performance
                    async def get_title():
                        try:
                            return await asyncio.wait_for(page.title(), timeout=5.0)
                        except asyncio.TimeoutError:
                            return "Untitled"
                    
                    async def get_content():
                        try:
                            html = await asyncio.wait_for(page.content(), timeout=15.0)
                            return html or ""
                        except asyncio.TimeoutError:
                            print("get_content: page.content() timed out after 15s")
                            return ""
                        except Exception as e:
                            print(f"get_content: {type(e).__name__}: {e}")
                            return ""
                    
                    async def get_body_text():
                        try:
                            return await asyncio.wait_for(page.evaluate("""
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
                            """), timeout=8.0)
                        except (asyncio.TimeoutError, Exception):
                            return ""
                    
                    async def get_links():
                        try:
                            return await asyncio.wait_for(page.evaluate("""
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
                            """), timeout=10.0)
                        except (asyncio.TimeoutError, Exception):
                            return []
                    
                    async def get_timestamp():
                        try:
                            return await asyncio.wait_for(page.evaluate("() => new Date().toISOString()"), timeout=2.0)
                        except (asyncio.TimeoutError, Exception):
                            return datetime.now().isoformat()
                    
                    # Execute all data extraction in parallel
                    page_title, html_content, body_text, page_links, scraped_at = await asyncio.gather(
                        get_title(),
                        get_content(),
                        get_body_text(),
                        get_links(),
                        get_timestamp()
                    )
                    
                    if not html_content:
                        raise Exception(
                            "Failed to get page content: page.content() returned empty or timed out. "
                            "Possible causes: slow/heavy page, load timeout, bot blocking, or network issue. "
                            "Try again or use a different URL."
                        )
                    
                    # Close browser
                    await browser.close()
                
                # Use Playwright-extracted data as primary (works better for JS-heavy sites)
                
                # Use page_title from Playwright if available
                final_title = page_title if page_title and page_title != "Untitled" else None
                final_links = page_links if page_links else []
                final_content = body_text if body_text else ""
                
                # ALWAYS parse HTML for LLM ad removal (second filter after network blocking)
                # This catches any ads that slipped through the network-level filter
                soup = None
                try:
                    soup = BeautifulSoup(html_content, 'lxml')
                    print(f"Parsing HTML for LLM ad removal (second filter)...")
                except Exception as e:
                    print(f"Failed to parse HTML: {e}")
                
                # Run LLM ad removal as second filter (always, not just for fallback)
                if soup and self.openai_client:
                    print("Running LLM ad removal as second filter...")
                    soup = await self._remove_ads(soup, url)
                    
                    # Re-extract content from cleaned HTML for better quality
                    cleaned_content = self._extract_content(soup)
                    if cleaned_content and len(cleaned_content) > 100:
                        # Use cleaned content if it's substantial
                        final_content = cleaned_content
                        print(f"Using LLM-cleaned content ({len(final_content)} chars)")
                    
                    # Filter links to remove any ad-related URLs that slipped through
                    if final_links:
                        original_link_count = len(final_links)
                        final_links = self._filter_ad_links(final_links)
                        filtered_count = original_link_count - len(final_links)
                        if filtered_count > 0:
                            print(f"Filtered {filtered_count} ad-related links")
                
                # Fallback to BeautifulSoup extraction if Playwright data is incomplete
                needs_fallback = (
                    (not final_title or final_title == "Untitled") or
                    (not final_links or len(final_links) == 0) or
                    (not final_content or len(final_content) < 100)
                )
                
                if needs_fallback and soup:
                    print("Using BeautifulSoup fallback for missing data...")
                    
                    # If Playwright extraction didn't get much, try BeautifulSoup
                    if (not final_title or final_title == "Untitled"):
                        final_title = self._extract_title(soup)
                    
                    if (not final_links or len(final_links) == 0):
                        final_links = self._extract_article_links(soup, url)
                    
                    if (not final_content or len(final_content) < 100):
                        soup_content = self._extract_content(soup)
                        # Use BeautifulSoup content if it's longer/better
                        if len(soup_content) > len(final_content):
                            final_content = soup_content
                
                # Ensure all links have image_url field (add empty string if missing)
                for link in final_links:
                    if 'image_url' not in link:
                        link['image_url'] = ''
                
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
        
        # Run the scraper with a timeout to prevent hanging
        try:
            result = await asyncio.wait_for(run_scraper(), timeout=90.0)  # 90 second total timeout
            return result
        except asyncio.TimeoutError:
            raise Exception("Scraping timeout: Operation took longer than 90 seconds")


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
