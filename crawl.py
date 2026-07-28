#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TigerBox 爬虫 - 自动抓取优惠信息并推送到 GitHub Gist
=====================================================

功能：
1. 内置品牌数据库，自动计算当日优惠活动
2. 可选抓取微博/抖音最新优惠动态
3. 将结果推送为 JSON 到 GitHub Gist
4. 支持 cron / GitHub Actions 定时运行

用法：
    python crawl.py                # 执行一次抓取
    python crawl.py --daemon       # 守护进程模式（每小时运行）
    python crawl.py --test         # 仅测试，不更新 Gist

依赖：
    pip install requests
"""

import json
import os
import sys
import time
import datetime
import hashlib
from pathlib import Path

try:
    import requests
except ImportError:
    print("错误: 请先安装 requests 库")
    print("  pip install requests")
    sys.exit(1)

try:
    import certifi
    SSL_VERIFY = certifi.where()
except ImportError:
    SSL_VERIFY = True

# 某些 Windows 环境缺少 CA 证书链，降级为不验证
def _test_ssl():
    try:
        requests.get('https://api.github.com', verify=SSL_VERIFY, timeout=5)
        return SSL_VERIFY
    except Exception:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        print("⚠ SSL 证书验证不可用，降级为不验证（仅影响本地运行，GitHub Actions 不受影响）")
        return False

SSL_VERIFY = _test_ssl()

# ===================== 配置 =====================

SCRIPT_DIR = Path(__file__).parent
BRANDS_FILE = SCRIPT_DIR / "brands.json"

# 尝试加载配置
config = {}
config_file = SCRIPT_DIR / "config.py"
if config_file.exists():
    import importlib.util
    spec = importlib.util.spec_from_file_location("config", config_file)
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
else:
    print("警告: 未找到 config.py，请复制 config.example.py 为 config.py 并填写配置")
    print("       仅使用内置品牌数据库，不抓取微博/抖音，不更新 Gist")

GITHUB_TOKEN = getattr(config, 'GITHUB_TOKEN', os.environ.get('GITHUB_TOKEN', ''))
GIST_ID = getattr(config, 'GIST_ID', os.environ.get('GIST_ID', ''))
GIST_FILENAME = getattr(config, 'GIST_FILENAME', 'tigerbox-deals.json')
WEIBO_COOKIE = getattr(config, 'WEIBO_COOKIE', '')
DOUYIN_COOKIE = getattr(config, 'DOUYIN_COOKIE', '')
ENABLE_WEIBO = getattr(config, 'ENABLE_WEIBO', True)
ENABLE_DOUYIN = getattr(config, 'ENABLE_DOUYIN', False)
CRAWL_INTERVAL = getattr(config, 'CRAWL_INTERVAL', 2)

# 注意: 索引遵循 JavaScript getDay() 约定 (0=周日, 1=周一, ..., 6=周六)
# 与 brands.json 中的 weekday 值一致
WEEKDAYS_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']


# ===================== 品牌数据库 =====================

def load_brands():
    """加载品牌数据库"""
    with open(BRANDS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_today_schedule(brands_data):
    """获取今日有优惠的品牌"""
    today = datetime.date.today()
    # Python weekday(): 0=Monday ... 6=Sunday
    # JavaScript getDay(): 0=Sunday, 1=Monday ... 6=Saturday
    # brands.json 使用 JavaScript 约定，需要转换
    py_weekday = today.weekday()
    today_weekday = (py_weekday + 1) % 7  # 转为 JS 约定
    today_day = today.day
    deals = []

    for brand in brands_data.get('brands', []):
        schedule = brand.get('schedule', {})
        stype = schedule.get('type', '')

        is_today = False
        recurrence = ''

        if stype == 'weekly':
            brand_weekday = schedule.get('weekday', 0)
            if brand_weekday == today_weekday:
                is_today = True
                recurrence = f"每周{WEEKDAYS_CN[brand_weekday]}"
        elif stype == 'monthly':
            if schedule.get('day') == today_day:
                is_today = True
                recurrence = f"每月{today_day}日"

        if is_today:
            deal = {
                'title': f"{brand['name']} {schedule.get('desc', '优惠活动').split('，')[0]}",
                'notes': schedule.get('desc', ''),
                'link': '',
                'source': '品牌日历',
                'brand': brand['name'],
                'date': today.isoformat(),
                'recurrence': recurrence,
                'tags': brand.get('tags', [])
            }
            deals.append(deal)
            print(f"  ✓ {brand['name']} - {deal['title']}")

    return deals


# ===================== 微博抓取 =====================

def crawl_weibo(keyword, brands_data):
    """从微博搜索优惠信息"""
    if not ENABLE_WEIBO:
        return []

    deals = []
    base_url = brands_data.get('platforms', {}).get('weibo_search_url',
              'https://m.weibo.cn/api/container/getIndex')

    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
        'Referer': 'https://m.weibo.cn/',
    }
    if WEIBO_COOKIE:
        headers['Cookie'] = WEIBO_COOKIE

    # 搜索关键词
    search_terms = [f"{keyword} 优惠", f"{keyword} 优惠券", f"{keyword} 活动"]
    today_str = datetime.date.today().strftime('%Y-%m-%d')

    for term in search_terms[:1]:  # 只搜第一个关键词，避免过多请求
        try:
            params = {
                'containerid': f'100103type=1&q={term}',
                'page_type': 'searchall',
                'page': 1
            }
            resp = requests.get(base_url, params=params, headers=headers, timeout=10, verify=SSL_VERIFY)
            if resp.status_code == 200:
                data = resp.json()
                cards = data.get('data', {}).get('cards', [])

                for card in cards[:5]:  # 最多取5条
                    card_group = card.get('card_group', [])
                    for item in card_group:
                        mblog = item.get('mblog', {})
                        if not mblog:
                            continue

                        text = mblog.get('text', '').replace('<span>', '').replace('</span>', '')
                        # 简单提取链接
                        bid = mblog.get('bid', '')
                        if bid:
                            link = f"https://m.weibo.cn/detail/{bid}"
                        else:
                            link = ''

                        # 检查是否今天的
                        created_at = mblog.get('created_at', '')
                        if '今天' in created_at or '分钟' in created_at or '小时' in created_at:
                            deal = {
                                'title': f"{keyword} 微博优惠动态",
                                'notes': text[:100] + ('...' if len(text) > 100 else ''),
                                'link': link,
                                'source': '微博',
                                'brand': keyword,
                                'date': today_str,
                                'tags': []
                            }
                            deals.append(deal)
                            print(f"  📱 微博: {deal['title']}")
                            break

            time.sleep(CRAWL_INTERVAL)

        except Exception as e:
            print(f"  ⚠ 微博抓取失败 [{keyword}]: {e}")
            continue

    return deals


# ===================== 抖音抓取 =====================

def crawl_douyin(keyword, brands_data):
    """从抖音搜索优惠信息"""
    if not ENABLE_DOUYIN:
        return []

    deals = []
    # 注意: 抖音搜索接口需要复杂的签名，这里提供框架
    # 实际使用需要配合 playwright 或其他方式获取签名

    try:
        # 抖音搜索 API (需要有效的签名和cookie)
        # 这里只是一个框架，实际使用需要适配
        print(f"  ℹ 抖音抓取 [{keyword}]: 需要配置有效的 Cookie 和签名")
        pass
    except Exception as e:
        print(f"  ⚠ 抖音抓取失败 [{keyword}]: {e}")

    return deals


# ===================== 公众号文章抓取 =====================

def crawl_wechat_articles(brands_data):
    """抓取公众号文章中的优惠信息
    
    注意: 微信公众号文章需要通过搜狗微信搜索或已配置的 RSS 源
    """
    deals = []
    sources = brands_data.get('platforms', {}).get('wechat_article_sources', [])

    if not sources:
        return deals

    today_str = datetime.date.today().strftime('%Y-%m-%d')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    for source_url in sources:
        try:
            resp = requests.get(source_url, headers=headers, timeout=10, verify=SSL_VERIFY)
            if resp.status_code == 200:
                # 简单解析，实际需要根据具体 RSS/页面结构调整
                # 这里提供框架
                pass
            time.sleep(CRAWL_INTERVAL)
        except Exception as e:
            print(f"  ⚠ 公众号源抓取失败: {e}")
            continue

    return deals


# ===================== Gist 更新 =====================

def update_gist(deals_data):
    """更新 GitHub Gist"""
    if not GITHUB_TOKEN or not GIST_ID:
        print("\n⚠ 未配置 GitHub Token 或 Gist ID，跳过 Gist 更新")
        print("  在 config.py 或环境变量中设置 GITHUB_TOKEN 和 GIST_ID")
        return False

    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }

    content = json.dumps(deals_data, ensure_ascii=False, indent=2)

    payload = {
        'files': {
            GIST_FILENAME: {
                'content': content
            }
        }
    }

    try:
        resp = requests.patch(url, json=payload, headers=headers, timeout=15, verify=SSL_VERIFY)
        if resp.status_code == 200:
            print(f"\n✅ Gist 更新成功！共 {len(deals_data.get('deals', []))} 条优惠信息")
            gist_url = resp.json().get('html_url', '')
            print(f"   Gist URL: {gist_url}")
            return True
        else:
            print(f"\n❌ Gist 更新失败: HTTP {resp.status_code}")
            print(f"   {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"\n❌ Gist 更新异常: {e}")
        return False


# ===================== 主流程 =====================

def run_crawl(test_mode=False):
    """执行一次完整的抓取流程"""
    print("=" * 50)
    print(f"🐯 TigerBox 爬虫 - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 1. 加载品牌数据
    brands_data = load_brands()
    brands = brands_data.get('brands', [])
    print(f"\n📊 已加载 {len(brands)} 个品牌")

    all_deals = []

    # 2. 获取今日品牌日历优惠
    print("\n📅 计算今日品牌优惠日历...")
    today_deals = get_today_schedule(brands_data)
    all_deals.extend(today_deals)
    print(f"   今日品牌优惠: {len(today_deals)} 条")

    # 3. 抓取微博实时优惠
    if ENABLE_WEIBO:
        print("\n📱 抓取微博实时优惠...")
        # 只抓取今日有优惠的品牌 + 热门品牌
        today_brands = [d['brand'] for d in today_deals]
        # 额外抓取一些热门品牌
        hot_brands = ['瑞幸咖啡', '麦当劳', '肯德基', '蜜雪冰城']
        crawl_brands = list(set(today_brands + hot_brands))[:5]  # 限制数量

        for brand_name in crawl_brands:
            print(f"   搜索: {brand_name}...")
            weibo_deals = crawl_weibo(brand_name, brands_data)
            all_deals.extend(weibo_deals)

    # 4. 抓取抖音实时优惠
    if ENABLE_DOUYIN:
        print("\n🎵 抓取抖音实时优惠...")
        today_brands = [d['brand'] for d in today_deals]
        for brand_name in today_brands[:3]:
            print(f"   搜索: {brand_name}...")
            douyin_deals = crawl_douyin(brand_name, brands_data)
            all_deals.extend(douyin_deals)

    # 5. 抓取公众号文章
    print("\n💬 抓取公众号文章...")
    wechat_deals = crawl_wechat_articles(brands_data)
    all_deals.extend(wechat_deals)

    # 6. 去重
    seen = set()
    unique_deals = []
    for deal in all_deals:
        key = deal.get('title', '') + deal.get('link', '')
        if key not in seen:
            seen.add(key)
            unique_deals.append(deal)

    # 7. 组装最终数据
    result = {
        'version': '1.0',
        'updatedAt': datetime.datetime.now().isoformat(),
        'updateDate': datetime.date.today().isoformat(),
        'totalDeals': len(unique_deals),
        'deals': unique_deals
    }

    print(f"\n📊 汇总: 共 {len(unique_deals)} 条优惠信息")

    # 8. 保存本地备份
    backup_file = SCRIPT_DIR / f"deals_{datetime.date.today().isoformat()}.json"
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"💾 本地备份: {backup_file}")

    # 9. 更新 Gist
    if test_mode:
        print("\n🧪 测试模式: 跳过 Gist 更新")
        print(f"   数据预览:\n{json.dumps(result, ensure_ascii=False, indent=2)[:500]}...")
    else:
        update_gist(result)

    print("\n" + "=" * 50)
    print("✅ 完成!")
    print("=" * 50)

    return result


def daemon_mode():
    """守护进程模式，每小时运行一次"""
    print("🐯 TigerBox 爬虫守护进程已启动")
    print("   每小时自动运行一次，按 Ctrl+C 停止\n")

    while True:
        try:
            run_crawl()
        except Exception as e:
            print(f"❌ 运行异常: {e}")

        next_run = datetime.datetime.now() + datetime.timedelta(hours=1)
        print(f"\n⏰ 下次运行: {next_run.strftime('%H:%M:%S')}")
        print("-" * 50)
        time.sleep(3600)  # 1 hour


# ===================== 入口 =====================

if __name__ == '__main__':
    if '--daemon' in sys.argv:
        daemon_mode()
    elif '--test' in sys.argv:
        run_crawl(test_mode=True)
    else:
        run_crawl()
