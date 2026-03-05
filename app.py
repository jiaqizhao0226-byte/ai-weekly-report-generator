#!/usr/bin/env python3
"""
AI News PPT Generator - Fixed version without complex slide duplication
"""

from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from datetime import datetime
import os
import sys

# Load .env file
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

sys.path.insert(0, os.path.dirname(__file__))

from pptx import Presentation
from pptx.util import Pt, Inches
from pptx.dml.color import RGBColor
from news_fetcher import format_news_for_display, get_ai_news, expand_news_batch, rewrite_news_batch

app = Flask(__name__)
CORS(app)

def generate_news_text_parts(news_item):
    """Split news into title (bold) and content (normal) parts"""
    # Use AI-rewritten text if available
    rewritten = news_item.get('rewritten', '')
    if rewritten:
        # Rewritten format is "标题：内容" - split on first colon
        if '：' in rewritten:
            parts = rewritten.split('：', 1)
            title_part = parts[0] + '：'
            content_part = parts[1] if len(parts) > 1 else ''
        else:
            title_part = ''
            content_part = rewritten
        return title_part, content_part
    
    # Fallback to original text
    title = news_item.get('title', '')
    description = news_item.get('description', '')
    date = news_item.get('date_full', news_item.get('date', ''))
    
    if date and '-' in date and '年' not in date:
        try:
            dt = datetime.strptime(date[:10], '%Y-%m-%d')
            date = dt.strftime('%Y年%m月%d日')
        except:
            pass
    
    title_part = title + "："
    content_part = f"{date}，{description}" if date else description
    
    # Limit to 220 chars
    max_total = 220
    if len(title_part) + len(content_part) > max_total:
        content_part = content_part[:max_total - len(title_part) - 3] + '...'
    
    return title_part, content_part

def fill_text_shape(shape, news_item):
    """Fill shape with formatted news text - matching sample format"""
    title_part, content_part = generate_news_text_parts(news_item)
    
    tf = shape.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    
    # Title (bold, black, 华文楷体)
    run1 = p.add_run()
    run1.text = title_part
    run1.font.size = Pt(14)
    run1.font.bold = True
    run1.font.name = '华文楷体'
    run1.font.color.rgb = RGBColor(0, 0, 0)
    
    # Content (normal, black, 华文楷体)
    run2 = p.add_run()
    run2.text = content_part
    run2.font.size = Pt(14)
    run2.font.bold = False
    run2.font.name = '华文楷体'
    run2.font.color.rgb = RGBColor(0, 0, 0)

def download_image(url, timeout=10):
    """Download image from URL and return as BytesIO"""
    try:
        import requests
        from io import BytesIO
        from urllib.parse import urlparse
        
        # Extract domain for Referer header (bypass anti-hotlinking)
        parsed = urlparse(url)
        referer = f"{parsed.scheme}://{parsed.netloc}/"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': referer,
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code == 200 and len(response.content) > 1000:
            return BytesIO(response.content)
    except:
        pass
    return None

def search_logo_image(news_item, timeout=10):
    """Search for company/model logo when article has no image"""
    import requests
    from io import BytesIO
    
    # Extract company/model name from title for search
    title = news_item.get('title', '')
    
    # Common AI companies and models to search for
    logo_keywords = [
        'OpenAI', 'Anthropic', 'Google', 'Microsoft', 'Meta', 'Apple', 'Amazon', 'Nvidia',
        '百度', '阿里', '腾讯', '字节跳动', '华为', '小米', '商汤', '科大讯飞',
        'ChatGPT', 'GPT', 'Claude', 'Gemini', 'Llama', 'Mistral', 'Qwen', '千问', 
        'DeepSeek', 'Kimi', '文心', '混元', '豆包', 'Sora', 'Midjourney', 'Stable Diffusion'
    ]
    
    search_term = None
    for kw in logo_keywords:
        if kw.lower() in title.lower():
            search_term = f"{kw} logo"
            break
    
    if not search_term:
        # Try to extract first meaningful noun from title
        search_term = title.split('：')[0] if '：' in title else title[:20]
        search_term = f"{search_term} logo AI"
    
    # Use Brave Image Search
    brave_api_key = os.environ.get('BRAVE_API_KEY', '')
    if not brave_api_key:
        return None
    
    try:
        url = "https://api.search.brave.com/res/v1/images/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": brave_api_key
        }
        params = {
            "q": search_term,
            "count": 5,
            "safesearch": "strict"
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            results = data.get('results', [])
            
            # Try to download first valid image
            for result in results:
                img_url = result.get('properties', {}).get('url') or result.get('thumbnail', {}).get('src')
                if img_url:
                    img_stream = download_image(img_url, timeout=5)
                    if img_stream:
                        print(f"  Found logo for '{search_term}': {img_url[:60]}...")
                        return img_stream
    except Exception as e:
        print(f"  Logo search error: {e}")
    
    return None

def replace_shape_with_image(slide, shape, image_stream):
    """Replace a text shape with an image at the same position, preserving aspect ratio"""
    try:
        from PIL import Image
        from io import BytesIO
        
        # Get shape position and size
        left = shape.left
        top = shape.top
        placeholder_width = shape.width
        placeholder_height = shape.height
        
        # Get original image dimensions and convert if needed
        image_stream.seek(0)
        img = Image.open(image_stream)
        img_width, img_height = img.size
        
        # Convert WebP/unsupported formats to PNG
        if img.format not in ['BMP', 'GIF', 'JPEG', 'PNG', 'TIFF', 'WMF']:
            print(f"  Converting {img.format} to PNG...")
            png_stream = BytesIO()
            # Convert to RGB if necessary (for RGBA/P mode images)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGBA')
                img.save(png_stream, format='PNG')
            else:
                img = img.convert('RGB')
                img.save(png_stream, format='PNG')
            png_stream.seek(0)
            image_stream = png_stream
        else:
            image_stream.seek(0)  # Reset stream for pptx
        
        # Calculate aspect-ratio-preserving dimensions
        img_ratio = img_width / img_height
        placeholder_ratio = placeholder_width / placeholder_height
        
        if img_ratio > placeholder_ratio:
            # Image is wider - fit to width
            new_width = placeholder_width
            new_height = int(placeholder_width / img_ratio)
        else:
            # Image is taller - fit to height
            new_height = placeholder_height
            new_width = int(placeholder_height * img_ratio)
        
        # Center image within placeholder area
        new_left = left + (placeholder_width - new_width) // 2
        new_top = top + (placeholder_height - new_height) // 2
        
        # Remove the old shape
        sp = shape._element
        sp.getparent().remove(sp)
        
        # Add image with preserved aspect ratio
        slide.shapes.add_picture(image_stream, new_left, new_top, new_width, new_height)
        return True
    except Exception as e:
        print(f"  Image insert error: {e}")
        return False

def delete_slide(prs, index):
    """Delete slide at index"""
    rId = prs.slides._sldIdLst[index].rId
    prs.part.drop_rel(rId)
    del prs.slides._sldIdLst[index]

def fill_slide(slide, news_list):
    """Fill a single slide with up to 2 news items"""
    news_shapes = []
    image_shapes = []
    
    for shape in slide.shapes:
        if shape.has_text_frame:
            text = shape.text_frame.text
            if '新闻标题' in text or '新闻内容' in text:
                news_shapes.append(shape)
            elif '对应图片' in text:
                image_shapes.append(shape)
    
    news_shapes.sort(key=lambda s: s.top)
    image_shapes.sort(key=lambda s: s.top)
    
    for i in range(len(news_shapes)):
        if i < len(news_list):
            fill_text_shape(news_shapes[i], news_list[i])
            if i < len(image_shapes):
                news_item = news_list[i]
                image_url = news_item.get('image', '')
                img_stream = None
                
                if image_url:
                    # Try to download article image
                    img_stream = download_image(image_url)
                
                if not img_stream:
                    # No image or download failed - search for company/model logo
                    print(f"  No image for: {news_item.get('title', '')[:30]}... searching logo...")
                    img_stream = search_logo_image(news_item)
                
                if img_stream:
                    # Insert image with aspect ratio preserved
                    replace_shape_with_image(slide, image_shapes[i], img_stream)
                else:
                    # Still no image found, show placeholder
                    image_shapes[i].text_frame.clear()
                    p = image_shapes[i].text_frame.paragraphs[0]
                    run = p.add_run()
                    run.text = "[暂无图片]"
                    run.font.size = Pt(10)
                    run.font.name = '微软雅黑'
                    run.font.color.rgb = RGBColor(128, 128, 128)
        else:
            news_shapes[i].text_frame.clear()
            if i < len(image_shapes):
                image_shapes[i].text_frame.clear()

def generate_ppt(selected_news, output_path, date_range):
    """Generate PPT with multi-page template (17 slides)"""
    template_path = os.path.join(os.path.dirname(__file__), 'AI_template_new.pptx')
    prs = Presentation(template_path)
    
    # Update cover date (slide 0)
    for shape in prs.slides[0].shapes:
        if shape.has_text_frame:
            text = shape.text_frame.text
            if '202X年X月' in text:
                shape.text_frame.clear()
                p = shape.text_frame.paragraphs[0]
                run = p.add_run()
                run.text = date_range + '  |  光子策略分析'
                run.font.size = Pt(14)
                run.font.name = '华文楷体'
                run.font.color.rgb = RGBColor(255, 255, 255)
    
    # Group by category
    news_by_cat = {'model': [], 'application': [], 'investment': []}
    for news in selected_news:
        cat = news.get('category', 'application')
        if cat in news_by_cat:
            news_by_cat[cat].append(news)
    
    # Category slide structure:
    # - Slides 1-4: double-item (2 news each), Slide 5: single-item (1 news)
    # - Slides 6-9: double-item, Slide 10: single-item
    # - Slides 11-14: double-item, Slide 15: single-item
    # For odd news count, last item goes on single-item slide
    cat_config = {
        'model': {'double_start': 1, 'double_count': 4, 'single_idx': 5},
        'application': {'double_start': 6, 'double_count': 4, 'single_idx': 10},
        'investment': {'double_start': 11, 'double_count': 4, 'single_idx': 15}
    }
    
    # Track slides to delete (will delete in reverse order later)
    slides_to_delete = []
    
    # Process each category
    for category in ['model', 'application', 'investment']:
        cat_news = news_by_cat[category]
        config = cat_config[category]
        double_start = config['double_start']
        double_count = config['double_count']
        single_idx = config['single_idx']
        
        n = len(cat_news)
        pairs_needed = n // 2  # Number of double-item slides needed
        has_single = n % 2 == 1  # Whether we need single-item slide
        
        if n == 0:
            # No news - show placeholder on first double slide, delete rest
            slide = prs.slides[double_start]
            for shape in slide.shapes:
                if shape.has_text_frame:
                    text = shape.text_frame.text
                    if '新闻标题' in text:
                        shape.text_frame.clear()
                        p = shape.text_frame.paragraphs[0]
                        run = p.add_run()
                        run.text = "本周暂无相关重点新闻"
                        run.font.size = Pt(14)
                        run.font.name = '华文楷体'
                        run.font.color.rgb = RGBColor(128, 128, 128)
                    elif '对应图片' in text:
                        shape.text_frame.clear()
            # Delete slides 2-4 and single slide
            for i in range(1, double_count):
                slides_to_delete.append(double_start + i)
            slides_to_delete.append(single_idx)
        else:
            # Fill double-item slides
            for i in range(pairs_needed):
                slide_idx = double_start + i
                news_start = i * 2
                slide_news = cat_news[news_start:news_start + 2]
                fill_slide(prs.slides[slide_idx], slide_news)
            
            # Delete unused double-item slides
            for i in range(pairs_needed, double_count):
                slides_to_delete.append(double_start + i)
            
            # Handle single-item slide
            if has_single:
                # Fill single-item slide with last news
                last_news = cat_news[-1]
                fill_slide(prs.slides[single_idx], [last_news])
            else:
                # Delete single-item slide
                slides_to_delete.append(single_idx)
    
    # Delete unused slides in reverse order (to maintain indices)
    for idx in sorted(slides_to_delete, reverse=True):
        delete_slide(prs, idx)
    
    prs.save(output_path)
    return output_path

# Flask routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    days = data.get('days', 7)
    news = get_ai_news(days)
    news = format_news_for_display(news)
    news.sort(key=lambda x: x.get('importance', 0), reverse=True)
    return jsonify({'news': news, 'count': len(news)})

@app.route('/api/fetch-url', methods=['POST'])
def api_fetch_url():
    """Fetch article from URL for manual addition"""
    import requests
    from bs4 import BeautifulSoup
    import re
    
    data = request.json
    url = data.get('url', '')
    category = data.get('category', 'application')
    
    if not url:
        return jsonify({'success': False, 'error': '请提供链接'})
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract title
        title = ''
        for selector in ['h1', 'title', '.article-title', '.post-title']:
            elem = soup.select_one(selector)
            if elem:
                title = elem.get_text().strip()
                if len(title) > 10:
                    break
        
        # Extract description
        description = ''
        # Try meta description
        meta_desc = soup.select_one('meta[name="description"]')
        if meta_desc:
            description = meta_desc.get('content', '')
        
        # Try article content
        if not description or len(description) < 50:
            for selector in ['article p', '.article-content p', '.post-content p', 'main p']:
                paragraphs = soup.select(selector)
                if paragraphs:
                    texts = [p.get_text().strip() for p in paragraphs[:3] if len(p.get_text().strip()) > 30]
                    if texts:
                        description = ' '.join(texts)[:500]
                        break
        
        # Extract date
        date_str = ''
        for selector in ['.date', '.publish-time', '.post-date', 'time[datetime]', '.article-time']:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get('datetime', '') or elem.text.strip()
                date_match = re.search(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})', text)
                if date_match:
                    date_str = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"
                    break
        
        # Extract image
        image = ''
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get('content'):
            image = og_img.get('content')
        
        # Extract source domain
        from urllib.parse import urlparse
        source = urlparse(url).netloc
        
        # Format date display
        if date_str:
            try:
                dt = datetime.strptime(date_str, '%Y-%m-%d')
                date_display = dt.strftime('%m月%d日')
                date_full = dt.strftime('%Y年%m月%d日')
            except:
                date_display = '近期'
                date_full = ''
        else:
            now = datetime.now()
            date_display = now.strftime('%m月%d日')
            date_full = now.strftime('%Y年%m月%d日')
            date_str = now.strftime('%Y-%m-%d')
        
        news_item = {
            'title': title or '未知标题',
            'description': description,
            'url': url,
            'source': source,
            'date': date_str,
            'date_display': date_display,
            'date_full': date_full,
            'image': image,
            'category': category,
            'importance': 75,
            'custom': True
        }
        
        return jsonify({'success': True, 'news': news_item})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json
    selected_news = data.get('news', [])
    date_range = data.get('date_range', datetime.now().strftime('%Y年%m月第%W周'))
    
    # AI rewrite news in professional tone (max 220 chars each)
    selected_news = rewrite_news_batch(selected_news, max_chars=220)
    
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = os.path.join(output_dir, f'AI_Weekly_Report_{timestamp}.pptx')
    
    try:
        generate_ppt(selected_news, output_path, date_range)
        return jsonify({'success': True, 'filename': os.path.basename(output_path)})
    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e), 'trace': traceback.format_exc()}), 500

@app.route('/api/download')
def api_download():
    filename = request.args.get('file', '')
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    
    if filename:
        file_path = os.path.join(output_dir, filename)
    else:
        files = sorted([f for f in os.listdir(output_dir) if f.endswith('.pptx')], reverse=True)
        file_path = os.path.join(output_dir, files[0]) if files else None
    
    if file_path and os.path.exists(file_path):
        return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))
    return jsonify({'error': 'File not found'}), 404

if __name__ == '__main__':
    os.makedirs(os.path.join(os.path.dirname(__file__), 'templates'), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), 'output'), exist_ok=True)
    print("Starting AI News PPT Generator on http://localhost:5050")
    app.run(host='0.0.0.0', port=5050, debug=True)
