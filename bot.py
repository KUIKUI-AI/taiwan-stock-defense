import datetime
import pytz
import feedparser
import requests
import os
import sys
import json

CHIMPFEEDR_URL = os.environ.get("CHIMPFEEDR_URL")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# 定義快取檔案名稱（用於防重複推播）
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
    # 只保留最近 100 筆，避免快取檔案無限膨脹
    list_to_save = list(sent_links)[-100:]
    with open(CACHE_FILE, "w") as f:
        json.dump(list_to_save, f)

def main():
    if not CHIMPFEEDR_URL or not DISCORD_WEBHOOK_URL:
        print("【配置錯誤】未設定環境變數 CHIMPFEEDR_URL 或 DISCORD_WEBHOOK_URL")
        sys.exit(1)

    tw_tz = pytz.timezone('Asia/Taipei')
    now_tw = datetime.datetime.now(tw_tz)
    weekday = now_tw.weekday() 
    hour = now_tw.hour
    minute = now_tw.minute
    current_time_val = hour * 100 + minute

    # 1. 判斷台股開盤期間 (週一至週五 08:45 - 13:45)
    is_market_open = (0 <= weekday <= 4) and (845 <= current_time_val <= 1345)

    # 2. 變速邏輯攔截（加入 10 分鐘的容差區間，防 GitHub Actions 延遲啟動）
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

    # 4. 執行掃描
    feed = feedparser.parse(CHIMPFEEDR_URL)
    
    CRITICAL_KEYWORDS = ["breaking", "war", "attack", "missile", "iran", "military", "explosion", "crisis", "strike"]
    new_alerts_sent = False

    # 依時間由舊到新排序（有些 RSS 預設最新在最上面，反向處理可以讓最新消息最後被推播）
    entries = reversed(feed.entries) if hasattr(feed, 'entries') else []

    for entry in entries:
        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        
        # 檢查是否已推播過
        if link in sent_links:
            continue

        content_to_check = f"{title} {summary}".lower()
        
        # 關鍵字過濾
        if any(kw in content_to_check for kw in CRITICAL_KEYWORDS):
            payload = {
                "username": "全球戰事速報 (防禦特化版)",
                "embeds": [{
                    "title": f"⚠️ 突發要聞：{title}",
                    "url": link,
                    "description": summary[:200] if summary else "無新聞摘要。",
                    "color": 16711680,
                    "footer": {
                        "text": f"偵測時間 (Taipei): {now_tw.strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                }]
            }
            
            try:
                res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
                if res.status_code in [200, 204]:
                    print(f"✅ 已成功推播: {title}")
                    sent_links.add(link)
                    new_alerts_sent = True
                else:
                    print(f"❌ Discord 推播失敗，狀態碼: {res.status_code}")
            except Exception as e:
                print(f"❌ 發送請求至 Discord 時發生異常: {e}")

    # 5. 如果有新推播，更新快取檔案
    if new_alerts_sent:
        save_sent_links(sent_links)
    else:
        print("【掃描結束】未發現符合關鍵字的新消息。")

if __name__ == "__main__":
    main()
