import datetime
import pytz
import feedparser
import requests
import os
import sys
import json
import urllib.parse

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

NEWS_FEEDS = [
    "https://search.cnbc.com/rs/search/combined/?partnerId=2&query=breaking%20news&output=rss", # CNBC Breaking
    "https://www.reutersagency.com/feed/?best-sectors=news", # Reuters World
    "http://feeds.bbci.co.uk/news/world/rss.xml" # BBC World
]

CACHE_FILE = "sent_links_cache.json"

def load_sent_links():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_sent_links(sent_links):
    list_to_save = list(sent_links)[-100:]
    with open(CACHE_FILE, "w") as f:
        json.dump(list_to_save, f)

def translate_to_zh_tw(text):
    """
    使用免費免 API Key 的 Google 翻譯接口，將英文翻譯為繁體中文。
    """
    if not text:
        return ""
    try:
        # 進行網址編碼以防特殊字元出錯
        encoded_text = urllib.parse.quote(text)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-TW&dt=t&q={encoded_text}"
        
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            result = response.json()
            # 解析 Google 翻譯返回的嵌套 List
            translated_sentences = [sentence[0] for sentence in result[0] if sentence[0]]
            return "".join(translated_sentences)
    except Exception as e:
        print(f"⚠️ 翻譯失敗: {e}")
    return "[翻譯失敗]"

def main():
    if not DISCORD_WEBHOOK_URL:
        print("【配置錯誤】未設定環境變數 DISCORD_WEBHOOK_URL")
        sys.exit(1)

    tw_tz = pytz.timezone('Asia/Taipei')
    now_tw = datetime.datetime.now(tw_tz)
    weekday = now_tw.weekday() 
    hour = now_tw.hour
    minute = now_tw.minute
    current_time_val = hour * 100 + minute

    # 1. 判斷台股開盤期間 (週一至週五 08:45 - 13:45)
    is_market_open = (0 <= weekday <= 4) and (845 <= current_time_val <= 1345)

    # 2. 變速邏輯攔截
    if not is_market_open:
        is_sentinel_window = (0 <= minute <= 9) or (30 <= minute <= 39)
        if not is_sentinel_window:
            print(f"【哨兵模式】目前時間 {now_tw.strftime('%H:%M')}，非交易時段且不在半整點區間內，自主終止。")
            sys.exit(0)
        else:
            print(f"【哨兵模式】符合半整點觀測窗口（目前：{now_tw.strftime('%H:%M')}），執行雷達掃描...")
    else:
        print(f"【極速模式】台股開盤中（目前：{now_tw.strftime('%H:%M')}），執行雷達掃描...")

    # 3. 載入歷史推播紀錄
    sent_links = load_sent_links()

    # 4. 收集所有來源的新聞
    all_entries = []
    for url in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            if hasattr(feed, 'entries'):
                all_entries.extend(feed.entries)
        except Exception as e:
            print(f"⚠️ 抓取 RSS 來源失敗 ({url}): {e}")

    CRITICAL_KEYWORDS = ["breaking", "war", "attack", "missile", "iran", "military", "explosion", "crisis", "strike"]
    new_alerts_sent = False

    # 5. 執行掃描、過濾與翻譯
    for entry in all_entries:
        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        
        if link in sent_links:
            continue

        content_to_check = f"{title} {summary}".lower()
        
        if any(kw in content_to_check for kw in CRITICAL_KEYWORDS):
            # 觸發黑天鵝，進行即時翻譯！
            print(f"🚨 偵測到重大新聞，正在翻譯標題...")
            translated_title = translate_to_zh_tw(title)

            payload = {
                "username": "全球戰事速報",
                "embeds": [{
                    # 標題：顯示流暢的繁體中文
                    "title": f"⚠️ 突發：{translated_title}",
                    "url": link,
                    # 描述：僅保留乾淨的中英對照，移除容易夾帶網頁廣告/推薦影片雜訊的 summary
                    "description": f"**🌐 英文原標題 (Original):**\n*{title}*",
                    "color": 16711680,
                    "footer": {
                        "text": f"偵測時間 (Taipei): {now_tw.strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                }]
            }
            
            try:
                res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
                if res.status_code in [200, 204]:
                    print(f"✅ 已成功推播雙語新聞: {title}")
                    sent_links.add(link)
                    new_alerts_sent = True
                else:
                    print(f"❌ Discord 推播失敗，狀態碼: {res.status_code}")
            except Exception as e:
                print(f"❌ 發送請求至 Discord 時發生異常: {e}")

    # 6. 如果有新推播，更新快取檔案
    if new_alerts_sent:
        save_sent_links(sent_links)
    else:
        print("【掃描結束】未發現符合關鍵字的新消息。")

if __name__ == "__main__":
    main()
