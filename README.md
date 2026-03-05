# AI Weekly Report Generator

自动生成AI行业周报PPT的工具。

## 功能特性

- 自动抓取量子位（qbitai）AI新闻
- 使用阿里通义千问API润色改写内容
- 自动搜索并下载相关公司Logo
- 基于模板生成17页PPT周报

## 安装依赖

```bash
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

创建 `.env` 文件，添加API密钥：

```env
BRAVE_API_KEY=your_brave_search_api_key
QWEN_API_KEY=your_qwen_api_key
```

## 使用方法

```bash
python app.py
```

生成的PPT将保存在 `output/` 目录。

## 文件说明

- `app.py` - 主程序入口
- `news_fetcher.py` - 新闻抓取和处理逻辑
- `AI_template.pptx` - PPT模板文件
- `AI_sample.pptx` - 样例输出参考
- `templates/` - HTML模板文件

## 要求

- Python 3.8+
- Brave Search API密钥
- 通义千问API密钥

## License

MIT
