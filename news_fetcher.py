#!/usr/bin/env python3
"""
AI News Fetcher - Fetch AI news from multiple sources
Uses web search to get real news
"""

import requests
import json
from datetime import datetime, timedelta
import re
import os
import subprocess

def deduplicate_similar_news(news_list):
    """Use Qwen AI to identify and merge duplicate reports about the same event"""
    if len(news_list) <= 1:
        return news_list

    api_key = os.environ.get('QWEN_API_KEY', '')
    if not api_key:
        return news_list

    # 构造标题列表让AI识别重复组
    lines = []
    for i, item in enumerate(news_list):
        lines.append(f"{i}|{item.get('title', '')}")

    prompt = f"""你是新闻去重助手。以下是一批AI行业新闻标题，不同媒体可能用不同标题报道了同一事件。

请找出报道同一事件的标题，将它们分组。
每行输出一组，格式: 序号1,序号2,序号3
只输出有重复的组（2条及以上），不重复的不要输出。
不要输出任何解释。

{chr(10).join(lines)}"""

    try:
        resp = requests.post(
            'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'qwen-turbo',
                'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': 1000,
                'temperature': 0.1
            },
            timeout=30
        )

        if resp.status_code == 200:
            content = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')

            # 解析分组结果
            merged_ids = set()
            merge_groups = []
            for line in content.strip().split('\n'):
                line = line.strip()
                if not line:
                    continue
                try:
                    ids = [int(x.strip()) for x in re.findall(r'\d+', line)]
                    ids = [i for i in ids if 0 <= i < len(news_list)]
                    if len(ids) >= 2:
                        merge_groups.append(ids)
                        merged_ids.update(ids)
                except:
                    continue

            if not merge_groups:
                return news_list

            # 合并每组，保留重要性最高的
            result = []
            used = set()

            for group_ids in merge_groups:
                group = [news_list[i] for i in group_ids]
                group.sort(key=lambda x: x.get('importance', 0), reverse=True)
                best = group[0].copy()

                # 合并描述和来源
                all_descs = [n.get('description', '') for n in group if n.get('description')]
                if len(all_descs) > 1:
                    best['description'] = all_descs[0][:300]
                best['merged_count'] = len(group)
                best['sources'] = list(set(n.get('source', '') for n in group))

                result.append(best)
                used.update(group_ids)

            # 加上没被合并的
            for i, item in enumerate(news_list):
                if i not in used:
                    result.append(item)

            merged_total = sum(len(g) for g in merge_groups) - len(merge_groups)
            print(f"  AI dedup: merged {merged_total} duplicate articles into {len(merge_groups)} groups")
            return result

    except Exception as e:
        print(f"AI dedup error: {e}")

    return news_list

def rewrite_news_professional(title, description, date_full='', max_chars=280):
    """Rewrite news in professional tone using Qwen API"""
    import os
    api_key = os.environ.get('QWEN_API_KEY', '')
    if not api_key:
        # Fallback: just truncate
        text = f"{title}：{date_full}，{description}" if date_full else f"{title}：{description}"
        return text[:max_chars] if len(text) > max_chars else text
    
    try:
        original = f"{title}。{description}" if description else title
        
        # Ensure date is in correct format
        date_instruction = ""
        if date_full:
            date_instruction = '\n8. 【重要】正文必须以"' + date_full + '"开头，这是事件的实际发生日期，不要修改或编造其他日期'
        
        prompt = f"""请将以下AI行业新闻改写为专业、商业、中立的风格，用于企业周报PPT。

要求：
1. 总字数控制在250-300字（含标题），不能超过300字
2. 【最重要】只能基于原文提供的信息改写，严禁编造、杜撰任何原文中没有的数据、价格、参数、功能、时间线。如果原文信息不足，就简短概括原文内容即可，宁可写短也不能瞎编
3. 去除营销号/标题党风格，使用专业中立的表述
4. 格式：事件标题（15-25字）+中文冒号"："+ 正文描述
5. 必须以完整句子结尾，以句号"。"收尾，绝不能中途截断
6. 标题必须准确反映事件性质（如原文说"关停"就写关停，不要写成"发布"）{date_instruction}

原文：{original}
事件日期：{date_full if date_full else '未知'}

改写后："""

        response = requests.post(
            'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'qwen-turbo',
                'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': 400,
                'temperature': 0.7
            },
            timeout=15
        )
        
        if response.status_code == 200:
            result = response.json()
            rewritten = result['choices'][0]['message']['content'].strip()
            # Let AI handle length naturally - no hard truncation
            return rewritten
        else:
            return f"{title}：{description}"[:max_chars]
    except Exception as e:
        return f"{title}：{description}"[:max_chars]

def rewrite_news_batch(news_list, max_chars=220):
    """Rewrite multiple news items in parallel"""
    import concurrent.futures
    import os
    
    api_key = os.environ.get('QWEN_API_KEY', '')
    if not api_key:
        return news_list
    
    def rewrite_one(item):
        item = item.copy()
        rewritten = rewrite_news_professional(
            item.get('title', ''), 
            item.get('description', ''),
            item.get('date_full', ''),  # Pass actual event date
            max_chars
        )
        item['rewritten'] = rewritten
        return item
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(rewrite_one, news_list))
    
    return results

def fetch_article_image(url, timeout=5):
    """Fetch the main image from an article page"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code != 200:
            return None
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try og:image first (usually the best)
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get('content'):
            og_url = og_img.get('content')
            # Skip if it's a small placeholder
            if '100x100' not in og_url and 'logo' not in og_url.lower():
                return og_url
        
        # Look for article images - prefer larger ones
        candidates = []
        for img in soup.find_all('img'):
            src = img.get('src', '') or img.get('data-src', '') or img.get('data-original', '')
            if src and len(src) > 30:
                # Skip logos, icons, avatars, small placeholders
                skip_words = ['logo', 'icon', 'avatar', 'qrcode', 'head.jpg', 'footer', 'sidebar', '100x100', '200x', 'thumb', 'small']
                if any(w in src.lower() for w in skip_words):
                    continue
                # Prefer images with date patterns and full URLs
                if '/202' in src and ('i.qbitai.com' in src or 'uploads' in src):
                    # Make absolute URL if needed
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        src = f"{parsed.scheme}://{parsed.netloc}{src}"
                    candidates.append(src)
        
        # Return first good candidate (usually the main article image)
        if candidates:
            return candidates[0]
        
        return None
    except:
        return None

def enrich_news_with_images(news_list, max_fetch=20):
    """Fetch images for news items that don't have images"""
    import concurrent.futures
    
    items_to_fetch = []
    for i, item in enumerate(news_list[:max_fetch]):
        if not item.get('image') and item.get('url'):
            items_to_fetch.append((i, item))
    
    if not items_to_fetch:
        return news_list
    
    def fetch_one(args):
        idx, item = args
        img = fetch_article_image(item['url'])
        return idx, img
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_one, items_to_fetch))
    
    for idx, img in results:
        if img:
            news_list[idx]['image'] = img
    
    return news_list

def fetch_article_date(url, timeout=5):
    """Fetch publication date from article page"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code != 200:
            return None
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try common date selectors
        for selector in ['.date', '.publish-time', '.post-date', '.entry-date', 'time[datetime]', '.article-time']:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get('datetime', '') or elem.text.strip()
                # Try to parse date
                date_match = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', text)
                if date_match:
                    return f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
        
        # Fallback: search in page text
        text = soup.get_text()[:2000]
        date_match = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日]?', text)
        if date_match:
            return f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
        
        return None
    except:
        return None

def enrich_news_with_dates(news_list, max_fetch=30):
    """Fetch precise dates for news items that don't have dates"""
    import concurrent.futures
    
    # Only fetch for items without proper dates
    items_to_fetch = []
    for i, item in enumerate(news_list[:max_fetch]):
        date = item.get('date', '')
        # Skip if already has a proper date
        if date and re.match(r'\d{4}-\d{2}-\d{2}', date):
            continue
        if item.get('url'):
            items_to_fetch.append((i, item))
    
    if not items_to_fetch:
        return news_list
    
    # Fetch dates in parallel (faster)
    def fetch_one(args):
        idx, item = args
        date = fetch_article_date(item['url'])
        return idx, date
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(fetch_one, items_to_fetch))
    
    # Update news items with fetched dates
    for idx, date in results:
        if date:
            news_list[idx]['date'] = date
    
    return news_list

def fetch_article_content(url, max_chars=500):
    """Fetch and extract more content from a news article URL"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()
        
        # Try to find article content
        article = None
        for selector in ['article', '.article-content', '.post-content', '.entry-content', 
                         '.content', 'main', '[itemprop="articleBody"]']:
            article = soup.select_one(selector)
            if article:
                break
        
        if not article:
            article = soup.body
        
        if article:
            # Get text paragraphs
            paragraphs = article.find_all('p')
            text_parts = []
            total_len = 0
            
            for p in paragraphs:
                text = p.get_text().strip()
                if len(text) > 30:  # Skip very short paragraphs
                    text_parts.append(text)
                    total_len += len(text)
                    if total_len > max_chars:
                        break
            
            if text_parts:
                return ' '.join(text_parts)[:max_chars]
        
        return None
    except Exception as e:
        print(f"Fetch article error: {e}")
        return None

def expand_news_batch(news_list):
    """Fetch more content from article URLs for news items with short descriptions"""
    expanded_news = []
    
    for news in news_list:
        url = news.get('url', '')
        desc = news.get('description', '')
        
        # Only fetch more if description is short and we have a URL
        if len(desc) < 150 and url and url.startswith('http'):
            extra_content = fetch_article_content(url)
            if extra_content and len(extra_content) > len(desc):
                news = news.copy()
                news['description'] = extra_content
        
        expanded_news.append(news)
    
    return expanded_news

# Category keywords
# === Category 1: 模型动态 - 底层模型相关 ===
MODEL_NAMES = [
    'gpt-4', 'gpt-5', 'gpt4', 'gpt5', 'claude', 'gemini', 'llama', 'mistral', 
    'qwen', '千问', '通义千问', 'deepseek', 'glm', 'chatglm', '文心一言', 
    '混元', 'kimi', 'moonshot', 'sora', 'midjourney', 'stable diffusion',
    'dall-e', 'flux', 'cogvideo', 'kling', '可灵'
]

MODEL_KEYWORDS = [
    '大模型', 'llm', '语言模型', '多模态', 'multimodal', '开源模型',
    'parameter', '参数', 'benchmark', '基准测试', 'training', '训练',
    'fine-tune', '微调', 'weights', '权重', 'transformer', 'diffusion',
    'token', '上下文', 'context window', '架构', 'architecture',
    '模型发布', '模型升级', '开源', 'open source', '性能超越'
]

# === Category 2: 应用动态 - 基于模型的应用 ===
APP_KEYWORDS = [
    '元宝', 'chatgpt', '豆包app', 'copilot', 'ai助手', 'ai应用',
    '智能助手', '对话助手', '写作助手', '编程助手', 'ai搜索',
    '应用上线', '产品发布', '新功能', '用户数', '月活', 'dau',
    'app store', '下载量', '使用量', 'api调用', '插件', 'plugin',
    '接入', '集成', '落地应用', '商业化', 'to b', 'to c'
]

# === Category 3: 厂商&投融资动态 ===
COMPANY_KEYWORDS = [
    # 人员变动
    '跳槽', '加盟', '离职', '入职', '挖人', '高管', 'ceo', 'cto', 
    '创始人', '首席', '负责人', '团队',
    # 公司动态  
    '裁员', '招聘', '扩张', '业务', '战略', '合作', '收购', '并购',
    '拆分', '独立', '子公司', '新业务', '转型',
    # 投融资
    '融资', '投资', '估值', 'ipo', '上市', '亿美元', '亿元', 
    '轮融资', 'a轮', 'b轮', 'c轮', '种子轮', '天使轮',
    '投资方', '领投', '跟投'
]

# Legacy - keep for compatibility
INVEST_KEYWORDS = COMPANY_KEYWORDS

GAMING_KEYWORDS = [
    'game', 'gaming', '游戏', 'video game', '手游', '端游',
    'unity', 'unreal', 'epic games', 'ubisoft', 'npc对话', 'npc ai',
    '网易游戏', 'mihoyo', '米哈游', 'activision', 'ea games',
    'playstation', 'xbox', 'nintendo', 'steam',
    '原神', '王者荣耀', '逆水寒', '刺客信条'
]

def categorize_news(title, description):
    """Fallback: simple keyword-based categorization (used when AI API unavailable)"""
    text = (title + ' ' + description).lower()
    if any(k in text for k in ['融资', '投资', '上市', 'ipo', '估值', '亿元', '亿美元', '领投', '离职', '加盟', '裁员', '招聘']):
        return 'investment'
    if any(k in text for k in ['开源', '屠榜', '参数', '训练', '基准', 'benchmark', '大模型', 'llm', '权重', '推理']):
        return 'model'
    if any(name in text for name in MODEL_NAMES):
        return 'model'
    return 'application'

def ai_categorize_batch(news_list):
    """Use Qwen API to batch categorize news and filter out irrelevant content.

    Returns the news_list with updated 'category' field.
    Items marked as 'skip' are filtered out (ads, recruitment, irrelevant).
    """
    if not news_list:
        return news_list

    api_key = os.environ.get('QWEN_API_KEY', '')
    if not api_key:
        print("Qwen API key not found, using keyword-based categorization")
        for item in news_list:
            item['category'] = categorize_news(item.get('title', ''), item.get('description', ''))
        return news_list

    # 构造批量分类 prompt，每批最多40条避免超长
    batch_size = 40
    for batch_start in range(0, len(news_list), batch_size):
        batch = news_list[batch_start:batch_start + batch_size]

        lines = []
        for i, item in enumerate(batch):
            title = item.get('title', '')
            desc = item.get('description', '')[:100]
            lines.append(f"{i}|{title}|{desc}")

        prompt = f"""你是AI行业新闻分类助手。我们是游戏行业，关注通用AI技术进展，请对以下新闻逐条分类。

分类规则：
- model: 模型动态（模型发布/更新/开源/评测排行榜/屠榜/Arena竞技/性能对比/技术突破/论文/新架构/SOTA）。注意：只要涉及具体模型名称（如xxx-1.0）或评测基准（Arena/Benchmark），即使标题里有公司名，也应归为model
- application: 应用动态（AI产品/应用/功能上线/用户数据/商业落地/游戏AI应用/Agent/工具）
- investment: 厂商&投融资（融资/收购/上市/人事变动/公司战略/组织调整）
- skip: 仅跳过：招聘广告/编辑招募/征稿启事/课程推广。其他所有AI相关新闻都不要skip，即使是垂直行业的AI应用也保留

每行格式: 序号|标题|摘要
请只回复每行一个: 序号|分类
不要输出任何其他内容。

{chr(10).join(lines)}"""

        try:
            resp = requests.post(
                'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={
                    'model': 'qwen-turbo',
                    'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': 1000,
                    'temperature': 0.1
                },
                timeout=30
            )

            if resp.status_code == 200:
                content = resp.json().get('choices', [{}])[0].get('message', {}).get('content', '')
                # 解析结果
                for line in content.strip().split('\n'):
                    line = line.strip()
                    if '|' in line:
                        parts = line.split('|', 1)
                        try:
                            idx = int(parts[0].strip())
                            cat = parts[1].strip().lower()
                            if 0 <= idx < len(batch) and cat in ('model', 'application', 'investment', 'skip'):
                                batch[idx]['category'] = cat
                        except (ValueError, IndexError):
                            continue
            else:
                print(f"Qwen API error: HTTP {resp.status_code}")
        except Exception as e:
            print(f"Qwen categorize error: {e}")

        # Fallback: 未被AI分类的用关键词分类
        for item in batch:
            if 'category' not in item or item['category'] not in ('model', 'application', 'investment', 'skip'):
                item['category'] = categorize_news(item.get('title', ''), item.get('description', ''))

    # 过滤掉 skip 的垃圾内容
    before = len(news_list)
    news_list = [item for item in news_list if item.get('category') != 'skip']
    skipped = before - len(news_list)
    if skipped > 0:
        print(f"  AI filtered out {skipped} irrelevant articles (ads/recruitment/etc)")

    return news_list

def is_gaming_related(title, description):
    """Check if news is gaming/entertainment related"""
    text = (title + ' ' + description).lower()
    return any(k in text for k in GAMING_KEYWORDS)

def calculate_importance(news_item):
    """Calculate importance score (0-100) - focus on truly important news"""
    score = 30
    
    title = news_item.get('title', '')
    title_lower = title.lower()
    desc = news_item.get('description', '').lower()
    text = title_lower + ' ' + desc
    
    # === TIER 1: Major AI Companies (high weight) ===
    tier1_companies = ['openai', 'anthropic', 'google', 'deepmind', 'microsoft',
                       'meta', 'nvidia', 'apple',
                       '字节', 'bytedance', '百度', 'baidu', '阿里', 'alibaba',
                       '腾讯', 'tencent', '华为', 'huawei']
    tier1_found = sum(1 for co in tier1_companies if co in text)
    score += min(tier1_found * 12, 30)
    
    # === TIER 2: Important AI startups ===
    tier2_companies = ['deepseek', '深度求索', '智谱', 'zhipu', 'moonshot', '月之暗面',
                       '阶跃', 'minimax', '零一万物', 'mistral', 'cohere', 'perplexity',
                       '商汤', 'sensetime', '科大讯飞', 'iflytek']
    tier2_found = sum(1 for co in tier2_companies if co in text)
    score += min(tier2_found * 8, 15)
    
    # === Major Model Names ===
    models = ['gpt-4', 'gpt-5', 'gpt4', 'gpt5', 'claude', 'gemini', 'llama',
              'qwen', '千问', 'mistral', 'sora', 'midjourney', 'stable diffusion',
              '文心', '混元', '豆包', 'doubao', 'kimi', '通义']
    has_model = any(m in text for m in models)
    if has_model:
        score += 12
    
    # === Large Funding (reduced weight to avoid outranking major model releases) ===
    import re
    # Match patterns like "100亿", "10亿美元", "$1B", "1000万"
    if re.search(r'(\d+0亿|百亿|千亿|\$\d+[bB]|十亿|融资.{0,5}\d+亿)', title):
        score += 15
    elif re.search(r'(亿美元|亿元|亿|billion|million)', text):
        score += 8
    
    # === IPO/上市/收购 (big news) ===
    if any(x in text for x in ['ipo', '上市', '收购', 'acquisition', '并购', '合并']):
        score += 15
    
    # === New Product/Model Release or Major Change ===
    release_keywords = ['发布', '推出', '上线', 'release', 'launch', '开源',
                        '关停', '下线', '退场', '停服', '关闭', '弃用', '取消']
    has_release = any(x in title for x in release_keywords)
    if has_release:
        score += 12

    # === Compound bonus: Tier1 company + model name + release action ===
    # 要求发布动作和模型名在标题中紧密关联（如"发布GPT-5"、"开源Llama"）
    # 排除仅用于对比的情况（如"比肩GPT/Claude"）
    if tier1_found > 0 and has_model and has_release:
        # 检查模型名是否在"比肩/超越/对标/媲美/不如"等对比语境中
        compare_patterns = ['比肩', '超越', '对标', '媲美', '不如', '性能比', '力压', '碾压', '吊打']
        is_comparison_only = any(cp in title for cp in compare_patterns)
        if not is_comparison_only:
            score += 25
    
    # === Gaming/Entertainment (priority per Kiki) ===
    if is_gaming_related(title, desc):
        score += 12
    
    # === Technical breakthrough ===
    if any(x in text for x in ['突破', 'breakthrough', '首次', 'first', '超越', 'surpass',
                                '世界第一', '全球首', '最强', '最大']):
        score += 8
    
    # === Application metrics / User data (per Kiki) ===
    app_metrics = ['用户数', '日活', '月活', 'dau', 'mau', '活跃用户', 
                   '营收', '收入', 'revenue', 'arr', 'mrr', '下载量', 'downloads',
                   '付费用户', '订阅', 'subscribers', '增长', 'growth']
    if any(x in text for x in app_metrics):
        score += 10
    
    # === Major apps adding AI (per Kiki) ===
    major_apps = ['微信', 'wechat', '抖音', 'tiktok', '淘宝', '支付宝', 
                  'instagram', 'whatsapp', 'spotify', 'netflix', 'adobe',
                  'notion', 'figma', 'canva', 'slack', 'zoom', 'office', 'word', 'excel']
    if any(app in text for app in major_apps) and any(ai in text for ai in ['ai', '智能', '模型', 'gpt', 'copilot']):
        score += 12
    
    # === AI Policy/Regulation (per Kiki) ===
    policy_keywords = ['政策', '监管', '法规', '立法', '合规', 'regulation', 'policy',
                       '白宫', '国务院', '工信部', '网信办', '欧盟', 'eu ai act',
                       '安全法', '治理', 'governance', '规范']
    if any(x in text for x in policy_keywords):
        score += 10
    
    # === Penalize clickbait/low quality ===
    clickbait = ['震惊', '必看', '不敢相信', '99%的人', '你不知道', '竟然']
    if any(x in title for x in clickbait):
        score -= 15
    
    # === Penalize very short titles (likely low quality) ===
    if len(title) < 15:
        score -= 10
    
    return min(100, max(0, score))

def search_brave(query, count=10):
    """Search using Brave Search API"""
    api_key = os.environ.get('BRAVE_API_KEY', '')
    if not api_key:
        return []
    
    try:
        headers = {
            'X-Subscription-Token': api_key,
            'Accept': 'application/json'
        }
        params = {
            'q': query,
            'count': count,
            'freshness': 'pw'  # past week
        }
        
        response = requests.get(
            'https://api.search.brave.com/res/v1/news/search',
            headers=headers,
            params=params,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            results = []
            for r in data.get('results', []):
                results.append({
                    'title': r.get('title', ''),
                    'description': r.get('description', ''),
                    'url': r.get('url', ''),
                    'source': r.get('meta_url', {}).get('netloc', r.get('source', 'Unknown')),
                    'date': r.get('age', ''),
                    'image': r.get('thumbnail', {}).get('src', '') if isinstance(r.get('thumbnail'), dict) else ''
                })
            return results
    except Exception as e:
        print(f"Brave search error: {e}")
    
    return []

def search_web_general(query):
    """General web search fallback"""
    # Could integrate other search APIs here
    return []

def scrape_36kr(max_pages=10):
    """Scrape AI news from 36kr - multiple pages for historical coverage"""
    results = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        from bs4 import BeautifulSoup
        
        # Fetch many pages for historical coverage
        for page in range(1, max_pages + 1):
            try:
                url = f'https://36kr.com/information/AI/' if page == 1 else f'https://36kr.com/information/AI/?page={page}'
                r = requests.get(url, headers=headers, timeout=10)
                soup = BeautifulSoup(r.text, 'html.parser')
                
                # Find article items
                articles = soup.select('.article-item-info, .flow-item, .article-wrapper')
                for article in articles:
                    title_elem = article.select_one('.article-item-title, h2 a, .title a')
                    desc_elem = article.select_one('.article-item-description, .summary, .desc')
                    link_elem = article.select_one('a[href*="/p/"]')
                    time_elem = article.select_one('.time, .date, time')
                    
                    if title_elem:
                        title = title_elem.text.strip()
                        desc = desc_elem.text.strip() if desc_elem else ''
                        href = link_elem.get('href', '') if link_elem else ''
                        article_url = 'https://36kr.com' + href if href and not href.startswith('http') else href
                        date_text = time_elem.text.strip() if time_elem else ''
                        
                        if title and len(title) > 5:
                            results.append({
                                'title': title,
                                'description': desc,
                                'url': article_url,
                                'source': '36kr.com',
                                'date': date_text,
                                'image': ''
                            })
            except Exception as e:
                continue
    except Exception as e:
        print(f"36kr scrape error: {e}")
    
    # Deduplicate by title
    seen = set()
    unique = []
    for r in results:
        if r['title'] not in seen:
            seen.add(r['title'])
            unique.append(r)
    
    return unique

def scrape_qbitai(max_pages=10):
    """Scrape AI news from 量子位 - multiple pages for historical coverage"""
    results = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        from bs4 import BeautifulSoup
        import re
        
        seen = set()
        
        # Scrape multiple pages
        for page in range(1, max_pages + 1):
            try:
                url = f'https://www.qbitai.com/page/{page}' if page > 1 else 'https://www.qbitai.com/'
                r = requests.get(url, headers=headers, timeout=10)
                soup = BeautifulSoup(r.text, 'html.parser')
                
                # Find articles with date-based URLs
                for a in soup.find_all('a', href=True):
                    href = a.get('href', '')
                    text = a.text.strip()
                    
                    # Match article URLs like /2026/02/382934.html
                    if len(text) > 15 and re.search(r'/20\d{2}/\d{2}/\d+\.html', href):
                        if text not in seen:
                            seen.add(text)
                            # Extract year/month from URL (day not available, estimate from article ID)
                            date_match = re.search(r'/(\d{4})/(\d{2})/(\d+)\.html', href)
                            if date_match:
                                year, month, article_id = date_match.groups()
                                # Estimate day based on current page (rough approximation)
                                estimated_day = max(1, 28 - (page - 1) * 3)
                                date_str = f"{year}-{month}-{estimated_day:02d}"
                            else:
                                date_str = ''
                            
                            results.append({
                                'title': text,
                                'description': '',
                                'url': href if href.startswith('http') else 'https://www.qbitai.com' + href,
                                'source': 'qbitai.com',
                                'date': date_str,
                                'image': ''
                            })
            except:
                continue
    except Exception as e:
        print(f"qbitai scrape error: {e}")
    
    return results

def scrape_huxiu(max_pages=5):
    """Scrape AI news from 虎嗅 - multiple pages"""
    results = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        from bs4 import BeautifulSoup
        
        seen = set()
        
        # Try homepage and channel pages
        urls = ['https://www.huxiu.com/']
        for page in range(2, max_pages + 1):
            urls.append(f'https://www.huxiu.com/?page={page}')
        
        for page_url in urls:
            try:
                r = requests.get(page_url, headers=headers, timeout=15)
                soup = BeautifulSoup(r.text, 'html.parser')
                
                for a in soup.find_all('a', href=True):
                    href = a.get('href', '')
                    text = a.text.strip()
                    
                    if '/article/' in href and len(text) > 15:
                        if text not in seen:
                            seen.add(text)
                            url = href if href.startswith('http') else 'https://www.huxiu.com' + href
                            results.append({
                                'title': text,
                                'description': '',
                                'url': url,
                                'source': 'huxiu.com',
                                'date': '',
                                'image': ''
                            })
            except:
                continue
    except Exception as e:
        print(f"huxiu scrape error: {e}")
    
    return results

def scrape_jiqizhixin():
    """Scrape AI news from 机器之心"""
    results = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        from bs4 import BeautifulSoup
        # Try their article list API or homepage
        r = requests.get('https://www.jiqizhixin.com/articles', headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Find article links
        seen = set()
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.text.strip()
            
            if '/article/' in href and len(text) > 10:
                if text not in seen:
                    seen.add(text)
                    results.append({
                        'title': text,
                        'description': '',
                        'url': href if href.startswith('http') else 'https://www.jiqizhixin.com' + href,
                        'source': 'jiqizhixin.com',
                        'date': '',
                        'image': ''
                    })
                    if len(results) >= 10:
                        break
    except Exception as e:
        print(f"jiqizhixin scrape error: {e}")
    
    return results

def scrape_xinzhiyuan():
    """Scrape AI news from 新智元"""
    results = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        from bs4 import BeautifulSoup
        import re
        
        # 新智元的文章页面
        r = requests.get('https://www.xinzhiyuan.com/articleList', headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        seen = set()
        # 尝试多种选择器
        for article in soup.find_all(['article', 'div'], class_=re.compile(r'article|post|item|news')):
            a = article.find('a', href=True)
            if not a:
                continue
            
            href = a.get('href', '')
            title_elem = article.find(['h2', 'h3', 'h4', 'a'])
            title = title_elem.text.strip() if title_elem else a.text.strip()
            
            # 提取描述
            desc_elem = article.find(['p', 'div'], class_=re.compile(r'desc|summary|excerpt|content'))
            desc = desc_elem.text.strip()[:200] if desc_elem else ''
            
            if len(title) > 10 and title not in seen:
                seen.add(title)
                url = href if href.startswith('http') else 'https://www.xinzhiyuan.com' + href
                results.append({
                    'title': title,
                    'description': desc,
                    'url': url,
                    'source': 'xinzhiyuan.com',
                    'date': '',
                    'image': ''
                })
                if len(results) >= 15:
                    break
        
        # 如果上面没抓到，尝试备用方式
        if not results:
            for a in soup.find_all('a', href=True):
                href = a.get('href', '')
                text = a.text.strip()
                if '/article/' in href and len(text) > 15 and text not in seen:
                    seen.add(text)
                    results.append({
                        'title': text,
                        'description': '',
                        'url': href if href.startswith('http') else 'https://www.xinzhiyuan.com' + href,
                        'source': 'xinzhiyuan.com',
                        'date': '',
                        'image': ''
                    })
                    if len(results) >= 15:
                        break
                        
    except Exception as e:
        print(f"xinzhiyuan scrape error: {e}")
    
    return results

def fetch_rss_feed(url, source_name='RSS', max_items=200):
    """通用RSS订阅源抓取"""
    results = []
    try:
        import feedparser
        feed = feedparser.parse(url)
        
        for entry in feed.entries[:max_items]:
            title = entry.get('title', '')
            description = entry.get('summary', entry.get('description', ''))
            # 清理HTML标签
            description = re.sub(r'<[^>]+>', '', description)[:300]
            
            link = entry.get('link', '')
            pub_date = ''
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    pub_date = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d')
                except:
                    pass
            
            if title:
                results.append({
                    'title': title,
                    'description': description,
                    'url': link,
                    'source': source_name,
                    'date': pub_date,
                    'image': ''
                })
    except Exception as e:
        print(f"RSS fetch error ({source_name}): {e}")
    
    return results

# RSS源配置 - 使用本地 WeWe RSS 服务
WEWE_RSS_BASE = 'http://localhost:4000/feeds'

# 分类配置：已知ID的直接使用，未配置的用 PLACEHOLDER 占位
# 用户在 WeWe RSS 后台添加订阅后，将 PLACEHOLDER_xxx 替换为真实 ID
RSS_FEEDS = {
    # === AI 垂直媒体 ===
    '量子位': f'{WEWE_RSS_BASE}/MP_WXS_3236757533.rss',
    '机器之心': f'{WEWE_RSS_BASE}/MP_WXS_3073282833.rss',
    '新智元': f'{WEWE_RSS_BASE}/MP_WXS_3271041950.rss',
    '36氪AI频道': f'{WEWE_RSS_BASE}/PLACEHOLDER_36kr_ai.rss',
    'AI科技评论': f'{WEWE_RSS_BASE}/PLACEHOLDER_ai_tech_review.rss',
    'CSDN AI': f'{WEWE_RSS_BASE}/PLACEHOLDER_csdn_ai.rss',
    '雷峰网': f'{WEWE_RSS_BASE}/PLACEHOLDER_leiphone.rss',
    '极客公园': f'{WEWE_RSS_BASE}/PLACEHOLDER_geekpark.rss',
    'AI前线': f'{WEWE_RSS_BASE}/PLACEHOLDER_ai_front.rss',
    'InfoQ': f'{WEWE_RSS_BASE}/PLACEHOLDER_infoq.rss',

    # === 大厂官方号 ===
    'OpenAI': f'{WEWE_RSS_BASE}/PLACEHOLDER_openai.rss',
    'Google AI': f'{WEWE_RSS_BASE}/PLACEHOLDER_google_ai.rss',
    '百度AI': f'{WEWE_RSS_BASE}/PLACEHOLDER_baidu_ai.rss',
    '腾讯AI Lab': f'{WEWE_RSS_BASE}/PLACEHOLDER_tencent_ai.rss',
    '阿里达摩院': f'{WEWE_RSS_BASE}/PLACEHOLDER_damo_academy.rss',
    '华为AI': f'{WEWE_RSS_BASE}/PLACEHOLDER_huawei_ai.rss',
    '字节跳动技术': f'{WEWE_RSS_BASE}/PLACEHOLDER_bytedance_tech.rss',
    '微软中国': f'{WEWE_RSS_BASE}/PLACEHOLDER_microsoft_china.rss',

    # === 投资/行业号 ===
    '甲子光年': f'{WEWE_RSS_BASE}/PLACEHOLDER_jiazi.rss',
    '智能涌现': f'{WEWE_RSS_BASE}/PLACEHOLDER_ai_emergence.rss',
    'AI商业评论': f'{WEWE_RSS_BASE}/PLACEHOLDER_ai_biz_review.rss',
    '硅星人': f'{WEWE_RSS_BASE}/PLACEHOLDER_guixingren.rss',
    '晚点LatePost': f'{WEWE_RSS_BASE}/PLACEHOLDER_latepost.rss',
    '深响': f'{WEWE_RSS_BASE}/PLACEHOLDER_deepecho.rss',
}

def fetch_all_rss_feeds():
    """抓取所有配置的RSS源 + 自动发现 WeWe RSS 已订阅的公众号"""
    all_results = []
    fetched_ids = set()

    # 排除的公众号（内容不相关或质量不高）
    excluded_names = set()

    # 1. 先尝试从 WeWe RSS 自动获取所有已订阅公众号
    try:
        resp = requests.get(f'{WEWE_RSS_BASE}/../feeds/', timeout=5)
        if resp.status_code == 200:
            feeds_data = resp.json()
            print(f"WeWe RSS 发现 {len(feeds_data)} 个已订阅公众号")
            for feed in feeds_data:
                feed_id = feed.get('id', '')
                name = feed.get('name', feed_id)
                if name in excluded_names:
                    print(f"Skipping excluded: {name}")
                    continue
                if feed_id:
                    url = f'{WEWE_RSS_BASE}/{feed_id}.rss?limit=500'
                    print(f"Fetching RSS: {name}...")
                    results = fetch_rss_feed(url, name)
                    all_results.extend(results)
                    print(f"  Got {len(results)} articles")
                    fetched_ids.add(feed_id)
    except Exception as e:
        print(f"WeWe RSS auto-discover failed: {e}, falling back to config")

    # 2. 补充抓取配置中的源（跳过已抓取的和占位的）
    for name, url in RSS_FEEDS.items():
        if 'PLACEHOLDER_' in url:
            continue
        # 检查是否已通过自动发现抓取过
        already_fetched = any(fid in url for fid in fetched_ids)
        if already_fetched:
            continue
        # 加 limit 参数获取更多文章
        if '?limit=' not in url:
            url = url + '?limit=500'
        print(f"Fetching RSS: {name}...")
        results = fetch_rss_feed(url, name)
        all_results.extend(results)
        print(f"  Got {len(results)} articles")

    return all_results

def extract_event_date_from_content(text):
    """从文章内容中提取实际事件发生日期"""
    import re
    
    # 匹配各种日期格式
    patterns = [
        r'(\d{4})年(\d{1,2})月(\d{1,2})日',  # 2024年3月1日
        r'(\d{4})-(\d{1,2})-(\d{1,2})',       # 2024-03-01
        r'(\d{4})/(\d{1,2})/(\d{1,2})',       # 2024/03/01
        r'(\d{1,2})月(\d{1,2})日',            # 3月1日 (当年)
    ]
    
    from datetime import datetime
    dates_found = []
    
    for pattern in patterns:
        matches = re.findall(pattern, text[:500])  # 只看前500字符
        for match in matches:
            try:
                if len(match) == 3:
                    year, month, day = int(match[0]), int(match[1]), int(match[2])
                    if year < 100:
                        year += 2000
                elif len(match) == 2:
                    year = datetime.now().year
                    month, day = int(match[0]), int(match[1])
                else:
                    continue
                    
                if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                    dates_found.append(datetime(year, month, day))
            except:
                continue
    
    if dates_found:
        # 返回最早的日期（通常是事件发生日期）
        return min(dates_found).strftime('%Y-%m-%d')
    return None

def is_timely_news(news_item, max_days=14):
    """判断新闻是否有时效性（不是旧事重提）"""
    from datetime import datetime, timedelta

    now = datetime.now()

    # 检查 date 字段（标准日期格式）
    date_str = news_item.get('date', '')
    if date_str and re.match(r'\d{4}-\d{2}-\d{2}', date_str):
        try:
            dt = datetime.strptime(date_str[:10], '%Y-%m-%d')
            if now - dt > timedelta(days=max_days):
                return False
        except:
            pass

    # 如果有提取到的事件日期，检查是否在时间范围内
    event_date = news_item.get('event_date')
    if event_date:
        try:
            event_dt = datetime.strptime(event_date, '%Y-%m-%d')
            if now - event_dt > timedelta(days=max_days):
                return False
        except:
            pass

    # 检查标题/描述中的关键词，识别回顾性文章
    text = (news_item.get('title', '') + news_item.get('description', '')).lower()
    retrospective_keywords = ['回顾', '盘点', '复盘', '去年', '历史', '曾经', '此前', '早在']
    for kw in retrospective_keywords:
        if kw in text:
            return False

    return True

def search_rss_by_keywords(keywords, days=7):
    """本地搜索已抓取的 RSS 文章，按关键词过滤"""
    all_articles = fetch_all_rss_feeds()
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    # 支持逗号或空格分隔的多关键词
    if isinstance(keywords, str):
        keyword_list = [k.strip().lower() for k in re.split(r'[,，\s]+', keywords) if k.strip()]
    else:
        keyword_list = [k.lower() for k in keywords]

    matched = []
    for article in all_articles:
        text = (article.get('title', '') + ' ' + article.get('description', '')).lower()
        # 任一关键词匹配即可
        if any(kw in text for kw in keyword_list):
            # 日期过滤
            date_str = article.get('date', '')
            if date_str and re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                if date_str < cutoff_date:
                    continue
            matched.append(article)

    print(f"RSS keyword search: found {len(matched)} articles matching '{keywords}'")
    return matched

def search_wechat_via_brave(keywords, count=10):
    """通过 Brave Search API 搜索 site:mp.weixin.qq.com 的公众号文章"""
    api_key = os.environ.get('BRAVE_API_KEY', '')
    if not api_key:
        print("Brave API key not found, skipping web search")
        return []

    # 构造搜索查询，限定微信公众号
    if isinstance(keywords, list):
        keywords = ' '.join(keywords)
    query = f"site:mp.weixin.qq.com {keywords}"

    try:
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key
        }
        params = {
            "q": query,
            "count": count,
            "search_lang": "zh-hans",
            # 注意：不使用 freshness 过滤，因为 Brave 对微信文章的时间索引不准确
            # 时效性过滤改由后续日期检查完成
        }

        response = requests.get(url, headers=headers, params=params, timeout=15)
        results = []

        if response.status_code == 200:
            data = response.json()
            web_results = data.get('web', {}).get('results', [])

            for item in web_results:
                result_url = item.get('url', '')
                # 只保留微信公众号文章链接
                if 'mp.weixin.qq.com' not in result_url:
                    continue

                title = item.get('title', '')
                description = item.get('description', '')

                # 尝试提取日期
                date_str = ''
                page_age = item.get('page_age', '')
                if page_age:
                    date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', page_age)
                    if date_match:
                        date_str = date_match.group(0)

                if not date_str:
                    # 从描述中提取日期
                    date_match = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', title + description)
                    if date_match:
                        date_str = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"

                if not date_str:
                    date_str = datetime.now().strftime('%Y-%m-%d')

                results.append({
                    'title': title,
                    'description': description,
                    'url': result_url,
                    'source': '微信公众号',
                    'date': date_str,
                    'image': item.get('thumbnail', {}).get('src', '')
                })

            print(f"Brave wechat search: found {len(results)} articles for '{keywords}'")
        else:
            print(f"Brave search failed: HTTP {response.status_code}")

        return results
    except Exception as e:
        print(f"Brave wechat search error: {e}")
        return []

def search_wechat_articles(keywords, days=7):
    """组合搜索：本地RSS + Brave网页搜索，去重后走正常分类/评分流程"""
    all_results = []

    # 1. 本地 RSS 关键词搜索
    rss_results = search_rss_by_keywords(keywords, days=days)
    all_results.extend(rss_results)

    # 2. Brave 网页搜索微信公众号
    brave_results = search_wechat_via_brave(keywords, count=15)
    all_results.extend(brave_results)

    # 去重（按URL和标题前30字符）
    seen_urls = set()
    seen_titles = set()
    unique_results = []
    for item in all_results:
        url = item.get('url', '')
        title = item.get('title', '')[:30]

        if url and url in seen_urls:
            continue
        if title and title in seen_titles:
            continue

        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)

        # 走正常的评分流程（分类由AI批量处理）
        item['gaming_related'] = is_gaming_related(item.get('title', ''), item.get('description', ''))
        item['importance'] = calculate_importance(item)
        item['search_result'] = True  # 标记为搜索结果

        unique_results.append(item)

    # AI批量分类
    unique_results = ai_categorize_batch(unique_results)

    # 按重要性排序
    unique_results.sort(key=lambda x: x.get('importance', 0), reverse=True)

    print(f"Keyword search total: {len(unique_results)} unique articles for '{keywords}'")
    return unique_results

def fetch_brave_supplement(days=7):
    """用 Brave 搜索多组 AI 热点关键词，抓取微信公众号文章补充 RSS 漏掉的"""
    api_key = os.environ.get('BRAVE_API_KEY', '')
    if not api_key:
        return []

    # 覆盖各个方向的热点关键词
    search_queries = [
        'AI 大模型 发布 最新',
        'OpenAI GPT Claude Anthropic 最新',
        'AI 开源模型 发布',
        'AI 融资 收购 上市',
        'AI 游戏 应用',
        'Sora Midjourney AI视频 AI图像',
        'AI Agent 智能体',
        '大模型 评测 屠榜 排行',
    ]

    all_results = []
    for query in search_queries:
        try:
            full_query = f"site:mp.weixin.qq.com {query}"
            resp = requests.get(
                'https://api.search.brave.com/res/v1/web/search',
                headers={'Accept': 'application/json', 'X-Subscription-Token': api_key},
                params={'q': full_query, 'count': 8, 'search_lang': 'zh-hans'},
                timeout=10
            )

            if resp.status_code == 200:
                web_results = resp.json().get('web', {}).get('results', [])
                for item in web_results:
                    url = item.get('url', '')
                    if 'mp.weixin.qq.com' not in url:
                        continue

                    title = item.get('title', '')
                    description = item.get('description', '')

                    # 提取日期
                    date_str = ''
                    page_age = item.get('page_age', '')
                    if page_age:
                        date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', page_age)
                        if date_match:
                            date_str = date_match.group(0)
                    if not date_str:
                        date_match = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', title + description)
                        if date_match:
                            date_str = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
                    if not date_str:
                        date_str = datetime.now().strftime('%Y-%m-%d')

                    all_results.append({
                        'title': title,
                        'description': description,
                        'url': url,
                        'source': '微信公众号(Brave)',
                        'date': date_str,
                        'image': item.get('thumbnail', {}).get('src', '') if isinstance(item.get('thumbnail'), dict) else ''
                    })
        except Exception as e:
            print(f"  Brave search error for '{query}': {e}")

    return all_results

def get_ai_news(days=7):
    """Get AI news from RSS feeds + Brave search supplement"""
    all_news = []

    # RSS 作为唯一信息源
    print("Fetching from RSS feeds...")
    rss_news = fetch_all_rss_feeds()
    all_news.extend(rss_news)
    print(f"  Total RSS articles: {len(all_news)}")

    # If no real news, use sample
    if not all_news:
        all_news = get_sample_news()

    # Deduplicate by URL and title
    seen_urls = set()
    seen_titles = set()
    unique_news = []
    for item in all_news:
        url = item.get('url', '')
        title = item.get('title', '')[:30]

        if url and url in seen_urls:
            continue
        if title and title in seen_titles:
            continue

        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)

        item['gaming_related'] = is_gaming_related(item.get('title', ''), item.get('description', ''))
        item['importance'] = calculate_importance(item)

        # 尝试提取实际事件日期
        text = item.get('title', '') + ' ' + item.get('description', '')
        event_date = extract_event_date_from_content(text)
        if event_date:
            item['event_date'] = event_date

        # 过滤掉旧事重提的文章
        if not is_timely_news(item, max_days=days):
            continue

        unique_news.append(item)

    # 用千问AI批量分类 + 过滤垃圾内容
    print("AI categorizing articles...")
    unique_news = ai_categorize_batch(unique_news)

    # Sort by importance
    unique_news.sort(key=lambda x: x.get('importance', 0), reverse=True)

    # Deduplicate similar news (merge articles about same event)
    unique_news = deduplicate_similar_news(unique_news)

    # === Filter by date range (strict) ===
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    filtered_news = []
    for item in unique_news:
        date = item.get('date', '')
        if date and re.match(r'\d{4}-\d{2}-\d{2}', date):
            if date >= cutoff_date:
                filtered_news.append(item)
            else:
                print(f"  Filtered out (too old: {date}): {item.get('title', '')[:40]}...")
        else:
            filtered_news.append(item)

    top_news = filtered_news[:150]

    # 批量抓取文章正文（补充RSS缺失的description）
    top_news = enrich_news_with_content(top_news, max_fetch=50)

    top_news = enrich_news_with_images(top_news, max_fetch=20)

    return top_news

def fetch_wechat_content(url, timeout=8):
    """从微信公众号文章链接抓取正文摘要"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code != 200:
            return None

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')

        # 微信文章正文在 #js_content
        content = soup.select_one('#js_content')
        if content:
            text = content.get_text(strip=True)
            # 取前500字作为摘要
            return text[:500] if text else None

        # 通用fallback
        for selector in ['article', '.article-content', '.post-content', 'main']:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(strip=True)
                if len(text) > 50:
                    return text[:500]

        return None
    except:
        return None

def enrich_news_with_content(news_list, max_fetch=50):
    """批量抓取文章正文，补充缺失的description"""
    import concurrent.futures

    # 只抓没有description的文章
    items_to_fetch = []
    for i, item in enumerate(news_list[:max_fetch]):
        desc = item.get('description', '').strip()
        if not desc and item.get('url'):
            items_to_fetch.append((i, item))

    if not items_to_fetch:
        return news_list

    print(f"  Fetching content for {len(items_to_fetch)} articles...")

    def fetch_one(args):
        idx, item = args
        content = fetch_wechat_content(item['url'])
        return idx, content

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(fetch_one, items_to_fetch))

    success = 0
    for idx, content in results:
        if content:
            news_list[idx]['description'] = content
            success += 1

    print(f"  Got content for {success}/{len(items_to_fetch)} articles")
    return news_list

def format_news_for_display(news_list):
    """Format news with proper date display"""
    for item in news_list:
        if 'category' not in item:
            item['category'] = categorize_news(item.get('title', ''), item.get('description', ''))
        if 'importance' not in item:
            item['importance'] = calculate_importance(item)
        if 'gaming_related' not in item:
            item['gaming_related'] = is_gaming_related(item.get('title', ''), item.get('description', ''))
        
        # Format date - convert relative dates to actual dates
        date_str = item.get('date', '')
        dt = None
        
        if date_str:
            # Try parsing relative dates like "3 days ago", "1 hour ago"
            date_lower = date_str.lower()
            if 'ago' in date_lower or '前' in date_str:
                import re
                now = datetime.now()
                
                # English patterns
                if 'hour' in date_lower or 'minute' in date_lower:
                    dt = now  # Same day
                elif match := re.search(r'(\d+)\s*day', date_lower):
                    days = int(match.group(1))
                    dt = now - timedelta(days=days)
                elif match := re.search(r'(\d+)\s*week', date_lower):
                    weeks = int(match.group(1))
                    dt = now - timedelta(weeks=weeks)
                    
                # Chinese patterns  
                elif match := re.search(r'(\d+)\s*天前', date_str):
                    days = int(match.group(1))
                    dt = now - timedelta(days=days)
                elif match := re.search(r'(\d+)\s*小时前', date_str):
                    dt = now
                elif match := re.search(r'(\d+)\s*周前', date_str):
                    weeks = int(match.group(1))
                    dt = now - timedelta(weeks=weeks)
            
            # Try standard date formats
            if not dt:
                for fmt in ['%Y-%m-%d', '%Y年%m月%d日', '%b %d, %Y', '%B %d, %Y', '%Y/%m/%d']:
                    try:
                        dt = datetime.strptime(date_str[:10] if len(date_str) >= 10 else date_str, fmt)
                        break
                    except:
                        continue
        
        # If still no date, mark as unknown (don't fake today's date)
        if not dt:
            item['date_display'] = '日期未知'
            item['date_full'] = ''
        else:
            item['date_display'] = dt.strftime('%m月%d日')
            item['date_full'] = dt.strftime('%Y年%m月%d日')
    
    return news_list

def get_sample_news():
    """Sample news for testing - detailed descriptions matching sample PPT style (150-350 chars)"""
    return [
        {
            'title': 'OpenAI发布GPT-5，推理能力实现重大突破',
            'description': 'OpenAI正式发布GPT-5模型，在复杂推理、代码生成、多模态理解等方面取得重大突破。GPT-5采用全新的混合专家架构（MoE），参数量达到1.8万亿，支持100万token上下文窗口。在多个基准测试中，GPT-5的表现已超越人类专家水平，特别是在数学推理和科学问答领域。OpenAI表示该模型将分阶段向ChatGPT Plus用户和API开发者开放。',
            'url': 'https://openai.com/blog/gpt5',
            'source': 'openai.com',
            'date': '2024-03-20',
            'image': ''
        },
        {
            'title': 'Claude 3.5 Opus发布，支持200K上下文窗口',
            'description': 'Anthropic正式推出Claude 3.5 Opus模型，支持200K token超长上下文窗口，可处理约50万字的文档内容。新模型在代码生成和数学推理任务中表现尤为出色，MATH基准测试得分达到92.3%。Claude 3.5 Opus还引入了"工件"功能，可在对话中创建和编辑代码、文档等内容。该模型已面向Claude Pro用户开放，API价格保持不变。',
            'url': 'https://anthropic.com/claude35',
            'source': 'anthropic.com',
            'date': '2024-03-19',
            'image': ''
        },
        {
            'title': 'Google发布Gemini 2.0，原生多模态架构重新定义AI交互',
            'description': 'Google DeepMind正式发布Gemini 2.0系列模型，采用全新的原生多模态架构，可同时处理文本、图像、音频和视频输入，并生成多种格式的输出。Gemini 2.0 Ultra在MMLU基准测试中得分达到95.2%，超越GPT-4。Google同时宣布将Gemini 2.0集成到Google搜索、Google Workspace和Android系统中，为用户提供更智能的AI助手体验。',
            'url': 'https://deepmind.google/gemini2',
            'source': 'deepmind.google',
            'date': '2024-03-18',
            'image': ''
        },
        {
            'title': '育碧推出AI驱动的NPC对话系统NEO NPC',
            'description': '育碧在GDC游戏开发者大会上展示了基于大语言模型的NPC对话系统NEO NPC。该系统可实现游戏角色的自然语言交互，NPC能够根据玩家的行为和对话内容动态调整回应，并记住之前的互动历史。NEO NPC还支持动态剧情生成，可根据玩家选择创造独特的故事线。育碧表示该技术将首先应用于即将发布的《刺客信条》新作中。',
            'url': 'https://news.ubisoft.com/neo-npc',
            'source': 'ubisoft.com',
            'date': '2024-03-17',
            'image': ''
        },
        {
            'title': 'Unity推出AI Muse工具套件，文字描述即可生成3D游戏场景',
            'description': 'Unity在GDC大会上正式发布AI Muse工具套件，支持开发者通过文字描述生成完整的3D游戏场景、角色模型和动画。AI Muse基于Unity自研的3D生成模型，可在几分钟内创建高质量的游戏资产。该工具还集成了AI音效生成功能，可根据场景自动生成环境音和背景音乐。Unity表示AI Muse将作为Unity 6的核心功能向所有订阅用户开放。',
            'url': 'https://unity.com/ai-muse',
            'source': 'unity.com',
            'date': '2024-03-16',
            'image': ''
        },
        {
            'title': 'Adobe Firefly视频生成功能正式上线Creative Cloud',
            'description': 'Adobe在Creative Cloud中正式集成Firefly Video功能，支持用户通过文本描述生成高质量视频片段。Firefly Video可生成最长30秒的1080p视频，支持多种风格预设和镜头控制选项。此外，该功能还支持视频风格迁移，可将现有视频转换为不同的艺术风格。Adobe表示所有Firefly生成的内容都经过版权安全训练，可用于商业用途。',
            'url': 'https://adobe.com/firefly-video',
            'source': 'adobe.com',
            'date': '2024-03-15',
            'image': ''
        },
        {
            'title': 'Anthropic完成27.5亿美元融资，估值达到180亿美元',
            'description': 'AI安全公司Anthropic宣布完成新一轮27.5亿美元融资，由Google领投，Amazon、Spark Capital等跟投，公司估值达到180亿美元。本轮融资将用于扩大算力基础设施、加速Claude模型研发以及扩展企业销售团队。Anthropic表示将继续专注于AI安全研究，确保大语言模型的可靠性和可控性。这是Anthropic成立以来的第四轮大规模融资。',
            'url': 'https://techcrunch.com/anthropic-funding',
            'source': 'techcrunch.com',
            'date': '2024-03-14',
            'image': ''
        },
        {
            'title': 'OpenAI洽购人形机器人公司Figure AI，加速具身智能布局',
            'description': '据路透社报道，OpenAI正在洽谈收购人形机器人初创公司Figure AI，交易金额可能超过20亿美元。Figure AI成立于2022年，专注于开发通用人形机器人，其机器人Figure 01已展示了执行复杂操作任务的能力。收购完成后，OpenAI将把GPT模型与Figure的机器人硬件结合，打造具备高级认知能力的智能机器人。这标志着OpenAI正式进军具身智能领域。',
            'url': 'https://reuters.com/openai-figure',
            'source': 'reuters.com',
            'date': '2024-03-13',
            'image': ''
        },
        {
            'title': '字节跳动发布豆包大模型2.0，中文理解能力大幅提升',
            'description': '字节跳动正式发布豆包大模型2.0版本，在中文理解、创意写作和逻辑推理能力上实现重大突破。豆包2.0在C-Eval中文基准测试中得分超过90%，位列国内大模型第一梯队。字节同时宣布向开发者免费开放豆包API，每日提供100万token免费调用额度。豆包2.0已集成到抖音、飞书、剪映等字节系产品中，服务数亿用户。',
            'url': 'https://36kr.com/p/doubao-2',
            'source': '36kr.com',
            'date': '2024-03-12',
            'image': ''
        },
        {
            'title': 'NVIDIA发布Blackwell架构GPU B200，AI算力提升2.5倍',
            'description': 'NVIDIA在GTC大会上正式发布基于Blackwell架构的新一代GPU B200。相比上一代H100，B200的AI训练性能提升2.5倍，推理性能提升5倍，能效比提升25%。B200采用台积电4nm工艺，集成2080亿晶体管，支持FP4精度计算。NVIDIA CEO黄仁勋表示，Blackwell架构将推动AI从云端延伸到边缘设备，开启AI计算的新时代。',
            'url': 'https://nvidia.com/blackwell',
            'source': 'nvidia.com',
            'date': '2024-03-11',
            'image': ''
        },
        {
            'title': 'Meta开源Llama 3系列模型，400B版本多项测试超越GPT-4',
            'description': 'Meta正式开源Llama 3系列大语言模型，包含8B、70B和400B三个版本。其中400B参数版本在MMLU、HumanEval等多项基准测试中超越GPT-4，成为目前最强大的开源模型。Llama 3采用全新的训练方法，数据集规模扩大到15万亿token。Meta表示Llama 3将完全开源，包括模型权重和训练代码，允许研究人员和开发者自由使用和修改。',
            'url': 'https://ai.meta.com/llama3',
            'source': 'meta.com',
            'date': '2024-03-10',
            'image': ''
        },
        {
            'title': '腾讯混元大模型正式接入微信生态，覆盖12亿用户',
            'description': '腾讯宣布混元大模型正式接入微信生态系统，包括微信搜一搜、公众号、小程序、视频号等核心场景，覆盖超过12亿月活用户。用户可通过自然语言与微信AI助手交互，获取信息查询、内容创作、翻译等服务。腾讯表示混元模型针对微信场景进行了深度优化，在中文对话和社交场景理解方面具有独特优势。这是国内首个将大模型全面集成到超级App的案例。',
            'url': 'https://36kr.com/p/tencent-hunyuan',
            'source': '36kr.com',
            'date': '2024-03-09',
            'image': ''
        },
        {
            'title': 'Midjourney发布V7版本，首次支持AI视频生成功能',
            'description': 'AI图像生成平台Midjourney正式发布V7版本，最大亮点是首次支持文字生成视频功能。用户可通过文本描述生成最长10秒的高质量视频，支持多种风格和分辨率选项。V7在图像生成质量上也有显著提升，人物面部和手部细节更加真实，风格一致性大幅改善。Midjourney表示V7采用了全新的扩散模型架构，生成速度比V6快3倍。',
            'url': 'https://midjourney.com/v7',
            'source': 'midjourney.com',
            'date': '2024-03-08',
            'image': ''
        },
        {
            'title': 'Mistral AI完成5亿欧元B轮融资，成为欧洲最有价值AI公司',
            'description': '法国AI初创公司Mistral AI宣布完成5亿欧元B轮融资，由DST Global领投，Lightspeed、a16z等跟投，公司估值达到60亿欧元，成为欧洲最有价值的AI公司。Mistral成立仅一年，已发布多款开源大模型，其Mixtral 8x7B模型性能媲美GPT-3.5。本轮融资将用于扩大研发团队、增加算力投入，并加速企业级产品的商业化落地。',
            'url': 'https://techcrunch.com/mistral-funding',
            'source': 'techcrunch.com',
            'date': '2024-03-07',
            'image': ''
        },
        {
            'title': '网易伏羲AI全面接入《逆水寒》手游，开创国内游戏AI交互先河',
            'description': '网易宣布旗下伏羲AI实验室技术全面接入《逆水寒》手游，玩家可与游戏中上千名NPC进行自然语言对话。NPC不仅能理解玩家的问题并给出合理回应，还能根据剧情发展和玩家行为调整性格和态度。此外，伏羲AI还为游戏提供智能剧情生成和个性化任务推荐功能。这是国内首款全面应用大语言模型技术的大型网络游戏，开创了游戏AI交互的新范式。',
            'url': 'https://163.com/nsh-ai',
            'source': '163.com',
            'date': '2024-03-06',
            'image': ''
        },
        {
            'title': 'Perplexity AI新一轮融资估值达90亿美元，月活突破1亿',
            'description': '据彭博社报道，AI搜索引擎Perplexity在新一轮融资中估值达到90亿美元，较上轮融资增长3倍。Perplexity月活跃用户已突破1亿，日均搜索量超过5000万次，正在成为Google搜索的有力挑战者。Perplexity的AI搜索引擎可直接给出问题答案并标注信息来源，大幅提升了搜索效率。公司表示将利用新资金扩展企业级产品和国际市场。',
            'url': 'https://bloomberg.com/perplexity',
            'source': 'bloomberg.com',
            'date': '2024-03-05',
            'image': ''
        },
        {
            'title': 'Suno AI发布V3音乐生成模型，可创作4分钟完整歌曲',
            'description': 'AI音乐生成平台Suno正式发布V3模型，可根据文本描述生成长达4分钟的完整歌曲，包含人声、乐器和编曲。V3生成的音乐音质接近专业制作水平，支持流行、摇滚、古典等多种曲风。用户可以指定歌词内容、情感基调和音乐风格，Suno会自动生成旋律和编曲。Suno表示V3的训练数据均已获得版权授权，生成的音乐可用于商业用途。',
            'url': 'https://suno.ai/v3',
            'source': 'suno.ai',
            'date': '2024-03-04',
            'image': ''
        },
        {
            'title': 'xAI发布Grok-2模型，新增实时网络搜索和图像理解能力',
            'description': 'Elon Musk旗下AI公司xAI正式发布Grok-2模型，新增实时网络搜索和图像理解两大核心能力。Grok-2可以访问X平台的实时数据，为用户提供最新的新闻和趋势分析。图像理解功能支持用户上传图片进行分析和问答。Grok-2目前面向X Premium+订阅用户开放，xAI表示未来还将推出独立的Grok应用程序和API服务。',
            'url': 'https://x.ai/grok2',
            'source': 'x.ai',
            'date': '2024-03-03',
            'image': ''
        },
        {
            'title': '阿里云开源通义千问72B模型，中英文测试超越Llama 2 70B',
            'description': '阿里云正式开源通义千问Qwen-72B模型，在多项中英文基准测试中超越Llama 2 70B，成为国内最强开源大模型之一。Qwen-72B支持32K上下文窗口，在代码生成、数学推理和多语言理解方面表现优异。阿里云同时提供完整的商用许可，企业可免费将模型用于商业产品开发。Qwen-72B已在ModelScope和Hugging Face平台上线，支持多种部署方式。',
            'url': 'https://qwen.aliyun.com',
            'source': 'aliyun.com',
            'date': '2024-03-02',
            'image': ''
        },
        {
            'title': 'Scale AI完成10亿美元融资，估值138亿美元成AI数据龙头',
            'description': '据TechCrunch报道，AI数据标注公司Scale AI宣布完成10亿美元新一轮融资，公司估值达到138亿美元。Scale AI已成为OpenAI、Google、Meta等头部AI公司的核心数据供应商，为GPT-4、Gemini等模型提供高质量训练数据。Scale AI的数据标注平台结合了人工标注和AI辅助工具，可高效处理图像、文本、音频等多种类型的数据。',
            'url': 'https://scale.com/funding',
            'source': 'scale.com',
            'date': '2024-03-01',
            'image': ''
        },
        {
            'title': 'Runway发布Gen-3视频生成模型，支持16秒高质量视频创作',
            'description': 'AI视频生成公司Runway正式发布Gen-3模型，单次可生成长达16秒的高质量视频，分辨率最高支持4K。Gen-3新增了镜头控制功能，用户可以指定摄像机运动、景深和构图方式。模型还支持风格迁移，可将现有视频转换为动画、油画等艺术风格。Runway表示Gen-3的训练采用了自研的时序一致性技术，大幅减少了视频中的闪烁和不连贯问题。',
            'url': 'https://runway.ml/gen3',
            'source': 'runway.ml',
            'date': '2024-02-28',
            'image': ''
        },
        {
            'title': 'DeepSeek发布V2 MoE架构模型，推理成本仅为GPT-4的1/30',
            'description': '中国AI公司深度求索正式发布DeepSeek V2模型，采用创新的混合专家（MoE）架构，在保持高性能的同时将推理成本降低90%。DeepSeek V2的API定价仅为GPT-4的1/30，成为目前性价比最高的大模型之一。V2在代码生成和数学推理任务中表现优异，多项指标接近GPT-4水平。DeepSeek表示将继续开源模型权重，推动国内AI技术的发展。',
            'url': 'https://deepseek.com/v2',
            'source': 'deepseek.com',
            'date': '2024-02-27',
            'image': ''
        }
    ]
