# TigerBox 配置文件 - 复制此文件为 config.py 并填入你的信息
# ============================================================

# GitHub Personal Access Token (需要 gist 权限)
# 创建地址: https://github.com/settings/tokens (勾选 gist)
GITHUB_TOKEN = "ghp_your_token_here"

# GitHub Gist ID (从 Gist URL 中获取)
# 例如 https://gist.github.com/username/abc123def456 中的 abc123def456
GIST_ID = "your_gist_id_here"

# Gist 中的文件名 (需与 App 端一致)
GIST_FILENAME = "tigerbox-deals.json"

# 微博 Cookie (可选，用于抓取微博搜索结果)
# 获取方式: 浏览器登录微博后，开发者工具中复制 Cookie
WEIBO_COOKIE = ""

# 抖音 Cookie (可选，用于抓取抖音搜索结果)
DOUYIN_COOKIE = ""

# 是否启用微博抓取
ENABLE_WEIBO = True

# 是否启用抖音抓取
ENABLE_DOUYIN = False

# 抓取间隔(秒)，避免频率过高
CRAWL_INTERVAL = 2
