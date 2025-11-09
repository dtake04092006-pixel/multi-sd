# TÊN FILE: multi_sofi_advanced.py
# PHIÊN BẢN: Multi-Farm Sofi Control v4.0 (Smart Button Detection)
import discord
from discord.ext import commands
import asyncio
import os
import threading
import time
import requests
import json
import random
import aiohttp
from flask import Flask, request, render_template_string, jsonify
from dotenv import load_dotenv
import re

load_dotenv()

# --- CẤU HÌNH & BIẾN TOÀN CỤC ---
SOFI_ID = 853629533855809596

# Tải danh sách tài khoản từ biến môi trường
TOKEN_MAIN = os.getenv("TOKEN_MAIN", "")  # Token chính - có khả năng đọc và phân tích
TOKENS_STR = os.getenv("TOKENS", "")
ACC_NAMES_STR = os.getenv("ACC_NAMES", "")

# Xử lý danh sách tài khoản
GLOBAL_ACCOUNTS = []
main_account = None

if TOKEN_MAIN:
    main_account = {"id": "acc_main", "name": "Main Account", "token": TOKEN_MAIN}
    GLOBAL_ACCOUNTS.append(main_account)

tokens_list = [token.strip() for token in TOKENS_STR.split(',') if token.strip()]
acc_names_list = [name.strip() for name in ACC_NAMES_STR.split(',') if name.strip()]

for i, token in enumerate(tokens_list):
    name = acc_names_list[i] if i < len(acc_names_list) else f"Account {i + 1}"
    GLOBAL_ACCOUNTS.append({"id": f"acc_{i}", "name": name, "token": token})

# Biến trạng thái
panels = []
main_panel_config = {
    "min_value": 0,  # Giá trị tối thiểu để nhặt
    "priority_emojis": []  # Danh sách emoji ưu tiên
}
current_drop_slot = 0
is_auto_drop_enabled = True
bot_ready = False
listener_bot = None
last_drop_cycle_time = 0

# Bộ nhớ lưu thông tin button từ Main Account
detected_buttons_cache = {}

# --- CÁC HÀM TIỆN ÍCH & API DISCORD (AIOHTTP + SPOOFING) ---

SPOOFED_HEADERS = {
    "Origin": "https://discord.com",
    "Referer": "https://discord.com/channels/@me",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "X-Super-Properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIiwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzExOC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTE4LjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjk5OTk5LCJjbGllbnRfZXZlbnRfc291cmNlIjpudWxsfQ=="
}

async def send_message_http_async(session, token, channel_id, content):
    """Gửi tin nhắn bằng AIOHTTP + Spoofed Headers (non-blocking)."""
    if not token or not channel_id: return
    
    headers = SPOOFED_HEADERS.copy()
    headers["Authorization"] = token
    
    payload = {"content": content}
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    try:
        async with session.post(url, headers=headers, json=payload, timeout=10) as res:
            if res.status != 200:
                print(f"[HTTP SEND ERROR] Lỗi khi gửi tin nhắn tới kênh {channel_id}: {res.status}")
    except Exception as e:
        print(f"[HTTP SEND EXCEPTION] Lỗi ngoại lệ khi gửi tin nhắn: {e}")

# --- LƯU & TẢI CẤU HÌNH PANEL ---

def save_panels():
    """Lưu cấu hình các panel lên JSONBin.io"""
    api_key = os.getenv("JSONBIN_API_KEY")
    bin_id = os.getenv("JSONBIN_BIN_ID")
    if not api_key or not bin_id:
        print("[Settings] Thiếu API Key hoặc Bin ID của JSONBin. Bỏ qua việc lưu.")
        return

    headers = {'Content-Type': 'application/json', 'X-Master-Key': api_key}
    url = f"https://api.jsonbin.io/v3/b/{bin_id}"
    
    data_to_save = {
        "panels": panels,
        "main_panel_config": main_panel_config
    }
    
    try:
        def do_save():
            req = requests.put(url, json=data_to_save, headers=headers, timeout=15)
            if req.status_code == 200:
                print("[Settings] Đã lưu cấu hình panels lên JSONBin.io thành công.")
            else:
                print(f"[Settings] Lỗi khi lưu cài đặt: {req.status_code} - {req.text}")
        threading.Thread(target=do_save, daemon=True).start()
    except Exception as e:
        print(f"[Settings] Exception khi lưu cài đặt: {e}")

def load_panels():
    """Tải cấu hình các panel từ JSONBin.io"""
    global panels, main_panel_config
    api_key = os.getenv("JSONBIN_API_KEY")
    bin_id = os.getenv("JSONBIN_BIN_ID")
    if not api_key or not bin_id:
        print("[Settings] Thiếu API Key hoặc Bin ID của JSONBin. Bắt đầu với cấu hình rỗng.")
        return

    headers = {'X-Master-Key': api_key, 'X-Bin-Meta': 'false'}
    url = f"https://api.jsonbin.io/v3/b/{bin_id}/latest"
    try:
        req = requests.get(url, headers=headers, timeout=15)
        if req.status_code == 200:
            data = req.json()
            if isinstance(data, dict):
                panels = data.get("panels", [])
                main_panel_config = data.get("main_panel_config", {"min_value": 0, "priority_emojis": []})
                print(f"[Settings] Đã tải {len(panels)} panel từ JSONBin.io.")
            elif isinstance(data, list):
                panels = data
                save_panels()
        else:
            print(f"[Settings] Lỗi khi tải cài đặt: {req.status_code} - {req.text}")
    except Exception as e:
        print(f"[Settings] Exception khi tải cài đặt: {e}")

def get_server_name_from_channel(channel_id):
    """Lấy tên server từ Channel ID thông qua Discord API."""
    if not channel_id or not channel_id.isdigit():
        return "ID kênh không hợp lệ"
    if not GLOBAL_ACCOUNTS:
        return "Không có token để xác thực"

    token = GLOBAL_ACCOUNTS[0]["token"]
    headers = SPOOFED_HEADERS.copy()
    headers["Authorization"] = token

    try:
        channel_res = requests.get(f"https://discord.com/api/v9/channels/{channel_id}", headers=headers, timeout=10)
        if channel_res.status_code != 200:
            return "Không tìm thấy kênh"

        channel_data = channel_res.json()
        guild_id = channel_data.get("guild_id")

        if not guild_id:
            return "Đây là kênh DM/Group"

        guild_res = requests.get(f"https://discord.com/api/v9/guilds/{guild_id}", headers=headers, timeout=10)
        if guild_res.status_code == 200:
            return guild_res.json().get("name", "Không thể lấy tên server")
        else:
            return "Không thể truy cập server"

    except requests.RequestException:
        return "Lỗi mạng"

# --- LOGIC PHÂN TÍCH BUTTON THÔNG MINH (CHO MAIN ACCOUNT) ---

def extract_number_from_text(text):
    """Trích xuất số từ text (VD: '★5 Character' -> 5)"""
    if not text:
        return None
    # Tìm tất cả các số trong text
    numbers = re.findall(r'\d+', text)
    if numbers:
        return int(numbers[0])
    return None

def analyze_button_priority(button, config):
    """
    Phân tích độ ưu tiên của button dựa trên:
    1. Emoji ưu tiên
    2. Giá trị số (nếu có)
    Trả về: (priority_score, value)
    """
    emoji_str = str(button.emoji) if button.emoji else ""
    label = button.label or ""
    
    # Kiểm tra emoji ưu tiên
    emoji_priority = -1
    for idx, priority_emoji in enumerate(config.get("priority_emojis", [])):
        if priority_emoji in emoji_str or priority_emoji in label:
            emoji_priority = idx
            break
    
    # Trích xuất giá trị số
    value = extract_number_from_text(label)
    
    # Tính điểm ưu tiên
    # Emoji match = ưu tiên cao nhất (điểm càng thấp càng ưu tiên)
    # Không match emoji = dựa vào giá trị số
    if emoji_priority >= 0:
        priority_score = emoji_priority * 1000  # Emoji ưu tiên luôn cao hơn
    else:
        priority_score = 10000  # Không có emoji ưu tiên
    
    # Thêm giá trị số (số càng cao, priority_score càng thấp)
    if value is not None:
        priority_score -= value
    
    return (priority_score, value if value else 0)

async def smart_button_click_main(message, bot, config):
    """
    Main Account: Phân tích và click button thông minh
    - Ưu tiên emoji theo danh sách
    - Chọn button có giá trị cao nhất
    - Kiểm tra giá trị tối thiểu
    """
    await asyncio.sleep(6)  # Delay 6 giây như yêu cầu
    
    try:
        print(f"[MAIN] 🧠 Đang phân tích button...")
        
        fetched_message = None
        found_buttons = []
        
        for attempt in range(5):
            try:
                fetched_message = await message.channel.fetch_message(message.id)
                
                found_buttons = []
                for action_row in fetched_message.components:
                    for component in action_row.children:
                        if isinstance(component, discord.Button):
                            found_buttons.append(component)
                
                if len(found_buttons) >= 3:
                    break
            except:
                pass
            await asyncio.sleep(1)
        
        if not found_buttons:
            print(f"[MAIN] ❌ Không tìm thấy button nào")
            return None
        
        # Phân tích từng button
        button_analysis = []
        for idx, btn in enumerate(found_buttons):
            priority, value = analyze_button_priority(btn, config)
            button_analysis.append({
                "index": idx,
                "button": btn,
                "priority": priority,
                "value": value,
                "label": btn.label or "No label",
                "emoji": str(btn.emoji) if btn.emoji else ""
            })
            print(f"[MAIN] 📊 Button {idx+1}: {btn.label} | Emoji: {btn.emoji} | Value: {value} | Priority: {priority}")
        
        # Sắp xếp theo độ ưu tiên (priority thấp = ưu tiên cao)
        button_analysis.sort(key=lambda x: x["priority"])
        
        # Chọn button tốt nhất thỏa mãn điều kiện min_value
        min_value = config.get("min_value", 0)
        best_button = None
        
        for btn_info in button_analysis:
            if btn_info["value"] >= min_value:
                best_button = btn_info
                break
        
        if best_button:
            print(f"[MAIN] ✅ Chọn button: {best_button['label']} (Value: {best_button['value']})")
            await best_button["button"].click()
            print(f"[MAIN] 🖱️ ĐÃ CLICK!")
            
            # Lưu thông tin để các account khác sử dụng
            detected_buttons_cache[str(message.channel.id)] = {
                "message_id": message.id,
                "best_index": best_button["index"],
                "timestamp": time.time()
            }
            
            return best_button["index"]
        else:
            print(f"[MAIN] ⚠️ Không có button nào thỏa mãn điều kiện (min_value: {min_value})")
            return None
            
    except Exception as e:
        print(f"[MAIN] ❌ Lỗi khi phân tích button: {e}")
        return None

async def handle_button_click_follower(message, bot, account_info, grab_index, delay):
    """
    Các account theo sau: Click button theo chỉ định của panel
    """
    await asyncio.sleep(delay)
    
    try:
        print(f"[{account_info['name']}] 🎯 Đang tìm button vị trí {grab_index+1}...")
        
        fetched_message = None
        found_buttons = []
        
        for attempt in range(5):
            try:
                fetched_message = await message.channel.fetch_message(message.id)
                
                found_buttons = []
                for action_row in fetched_message.components:
                    for component in action_row.children:
                        if isinstance(component, discord.Button):
                            found_buttons.append(component)
                
                if len(found_buttons) >= 3:
                    break
            except:
                pass
            await asyncio.sleep(1)
        
        if len(found_buttons) > grab_index:
            target_button = found_buttons[grab_index]
            await target_button.click()
            print(f"[{account_info['name']}] 🖱️ ĐÃ CLICK button vị trí {grab_index+1}!")
        else:
            print(f"[{account_info['name']}] ❌ Không tìm thấy button vị trí {grab_index+1}")
            
    except Exception as e:
        print(f"[{account_info['name']}] ⚠️ Lỗi click: {e}")

async def handle_drop_detection(message, panel):
    """
    Xử lý khi phát hiện drop trong panel
    - Main account: Phân tích thông minh và click
    - Các account khác: Click theo slot đã cấu hình
    """
    accounts_in_panel = panel.get("accounts", {})
    if not accounts_in_panel:
        return
    
    tasks = []
    grab_indices = [0, 1, 2]
    grab_delays = [6.0, 6.2, 6.4]
    
    # Kiểm tra xem có phải channel của Main không
    is_main_channel = False
    if main_account and str(message.channel.id) == panel.get("channel_id"):
        # Kiểm tra xem main account có được assign vào panel này không
        for slot_key, token in accounts_in_panel.items():
            if token == main_account["token"]:
                is_main_channel = True
                break
    
    # Nếu là channel có Main Account, Main sẽ phân tích và click trước
    if is_main_channel and main_account:
        # Main account click thông minh
        async def main_click_task():
            main_bot = None
            for bot in [listener_bot]:  # Tìm bot của main account
                if bot and bot.user:
                    break
            if main_bot:
                await smart_button_click_main(message, main_bot, main_panel_config)
        
        tasks.append(main_click_task())
    
    # Các account khác click theo cấu hình
    for i in range(3):
        slot_key = f"slot_{i + 1}"
        token = accounts_in_panel.get(slot_key)
        
        if token and token != (main_account["token"] if main_account else None):
            # Tìm account info
            acc_info = next((acc for acc in GLOBAL_ACCOUNTS if acc["token"] == token), None)
            if acc_info:
                grab_index = grab_indices[i]
                delay = grab_delays[i]
                
                async def click_task(acc, msg, idx, d):
                    # Tìm bot tương ứng với token này
                    # (Trong thực tế, bạn cần track bot instances cho từng account)
                    await handle_button_click_follower(msg, None, acc, idx, d)
                
                tasks.append(click_task(acc_info, message, grab_index, delay))
    
    if tasks:
        await asyncio.gather(*tasks)
        print(f"✅ Hoàn thành xử lý drop cho panel '{panel.get('name')}'")

async def run_listener_bot(session):
    """Chạy bot chính để lắng nghe sự kiện drop"""
    global bot_ready, listener_bot
    
    if not GLOBAL_ACCOUNTS:
        print("Không có token nào trong biến môi trường. Bot không thể khởi động.")
        bot_ready = True
        return
    
    listener_token = GLOBAL_ACCOUNTS[0]["token"]
    
    # ✅ Không cần intents cho self-bot với discord.py-self
    listener_bot = commands.Bot(
        command_prefix="!слушать",
        self_bot=True
    )
    
    # ✅ Tắt tất cả cache không cần thiết
    listener_bot.chunk_guilds_at_startup = False

    @listener_bot.event
    async def on_ready():
        global bot_ready
        print("-" * 60)
        print(f"🤖 BOT LẮNG NGHE ĐÃ SẴN SÀNG!")
        print(f"👤 Đăng nhập với tài khoản: {listener_bot.user} (ID: {listener_bot.user.id})")
        if main_account and listener_token == main_account["token"]:
            print(f"⭐ Đây là MAIN ACCOUNT - Có khả năng phân tích thông minh")
        print("🎯 Kiến trúc: Smart Button Detection + Multi-Panel Control")
        print("-" * 60)
        bot_ready = True

    @listener_bot.event
    async def on_message(message):
        if message.author.id != SOFI_ID:
            return
        
        content = message.content.lower()
        
        # Phát hiện drop
        if "dropping" in content or "thả" in content or "drop" in content:
            found_panel = None
            for p in panels:
                if p.get("channel_id") == str(message.channel.id):
                    found_panel = p
                    break
            
            if found_panel:
                print(f"\n{'='*60}")
                print(f"🎁 PHÁT HIỆN DROP trong '{found_panel.get('name')}'")
                print(f"📝 Nội dung: {message.content[:100]}")
                print(f"{'='*60}")
                asyncio.create_task(handle_drop_detection(message, found_panel))

    try:
        await listener_bot.start(listener_token)
    except discord.errors.LoginFailure:
        print(f"❌ LỖI ĐĂNG NHẬP NGHIÊM TRỌNG với token của bot lắng nghe.")
        print("💡 Kiểm tra lại TOKEN_MAIN hoặc TOKENS trong file .env")
        bot_ready = True
    except Exception as e:
        print(f"❌ Lỗi không xác định với bot lắng nghe: {e}")
        import traceback
        traceback.print_exc()
        bot_ready = True

# --- GIAO DIỆN WEB & API FLASK ---

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Multi-Sofi Smart Control</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --primary-bg: #111; --secondary-bg: #1d1d1d; --panel-bg: #2a2a2a; --border-color: #444; --text-primary: #f0f0f0; --text-secondary: #aaa; --accent-color: #00aaff; --danger-color: #ff4444; --success-color: #44ff44; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: var(--primary-bg); color: var(--text-primary); margin: 0; padding: 20px; }
        .container { max-width: 1800px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { color: var(--accent-color); font-weight: 600; margin-bottom: 10px; }
        .header .subtitle { color: var(--text-secondary); font-size: 0.9em; }
        
        .status-bar { display: flex; justify-content: space-around; background-color: var(--secondary-bg); padding: 15px; border-radius: 8px; margin-bottom: 20px; flex-wrap: wrap; gap: 15px; }
        .status-item { text-align: center; }
        .status-item span { display: block; font-size: 0.9em; color: var(--text-secondary); }
        .status-item strong { font-size: 1.2em; color: var(--accent-color); }
        
        .main-config { background-color: var(--secondary-bg); border: 2px solid var(--success-color); border-radius: 8px; padding: 20px; margin-bottom: 20px; }
        .main-config h2 { color: var(--success-color); margin-top: 0; font-size: 1.3em; }
        .main-config-grid { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; align-items: start; }
        
        .controls { display: flex; justify-content: center; gap: 15px; margin-bottom: 30px; flex-wrap: wrap; }
        .btn { background-color: var(--accent-color); color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 1em; transition: all 0.3s; }
        .btn:hover { background-color: #0088cc; transform: translateY(-2px); }
        .btn-danger { background-color: var(--danger-color); }
        .btn-danger:hover { background-color: #cc3333; }
        .btn-success { background-color: var(--success-color); color: #111; }
        .btn-success:hover { background-color: #33dd33; }
        
        .farm-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 20px; }
        .panel { background-color: var(--secondary-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 20px; position: relative; transition: transform 0.2s; }
        .panel:hover { transform: translateY(-3px); border-color: var(--accent-color); }
        .panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid var(--border-color); padding-bottom: 10px; }
        .panel-header h3 { margin: 0; font-size: 1.2em; color: var(--accent-color); }
        
        .input-group { margin-bottom: 15px; }
        .input-group label { display: block; color: var(--text-secondary); margin-bottom: 5px; font-size: 0.9em; }
        .input-group input, .input-group select, .input-group textarea { width: 100%; background-color: var(--primary-bg); border: 1px solid var(--border-color); color: var(--text-primary); padding: 8px; border-radius: 5px; box-sizing: border-box; font-family: inherit; }
        .input-group textarea { min-height: 80px; resize: vertical; }
        .input-group input:focus, .input-group select:focus, .input-group textarea:focus { outline: none; border-color: var(--accent-color); }
        
        .emoji-input { display: flex; gap: 10px; align-items: flex-start; }
        .emoji-input textarea { flex: 1; }
        .emoji-help { font-size: 0.8em; color: var(--text-secondary); margin-top: 5px; font-style: italic; }
        
        .server-name-display { font-size: 0.8em; color: var(--text-secondary); margin-top: 5px; display: block; height: 1.2em; }
        
        .account-slots { display: grid; grid-template-columns: 1fr; gap: 15px; }
        
        .info-badge { display: inline-block; background-color: var(--success-color); color: #111; padding: 3px 8px; border-radius: 3px; font-size: 0.8em; font-weight: bold; margin-left: 10px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-brain"></i> Multi-Sofi Smart Control v4.0</h1>
            <p class="subtitle">🧠 Hệ thống phân tích button thông minh với Main Account AI</p>
        </div>

        <div class="status-bar">
            <div class="status-item"><span>Trạng thái Bot</span><strong id="bot-status">Đang khởi động...</strong></div>
            <div class="status-item"><span>Tổng số Panel</span><strong id="total-panels">0</strong></div>
            <div class="status-item"><span>Lượt Drop Kế Tiếp</span><strong id="next-slot">Slot 1</strong></div>
            <div class="status-item"><span>Thời gian chờ</span><strong id="countdown">--:--:--</strong></div>
        </div>

        <div class="main-config">
            <h2><i class="fas fa-crown"></i> Cấu Hình Main Account <span class="info-badge">SMART AI</span></h2>
            <div class="main-config-grid">
                <div class="input-group">
                    <label><i class="fas fa-sort-numeric-up"></i> Giá trị tối thiểu (Min Value)</label>
                    <input type="number" id="main-min-value" min="0" placeholder="VD: 3">
                    <div class="emoji-help">Main chỉ nhặt button có giá trị ≥ con số này</div>
                </div>
                <div class="input-group">
                    <label><i class="fas fa-star"></i> Emoji ưu tiên (Priority Emojis)</label>
                    <div class="emoji-input">
                        <textarea id="main-priority-emojis" placeholder="VD: ⭐,🌟,✨&#10;(Mỗi emoji một dòng hoặc cách nhau bởi dấu phẩy)"></textarea>
                    </div>
                    <div class="emoji-help">Độ ưu tiên từ trên xuống dưới. Emoji đầu tiên = ưu tiên cao nhất.</div>
                </div>
            </div>
            <button id="save-main-config-btn" class="btn btn-success"><i class="fas fa-save"></i> Lưu Cấu Hình Main</button>
        </div>

        <div class="controls">
            <button id="add-panel-btn" class="btn"><i class="fas fa-plus"></i> Thêm Panel Mới</button>
            <button id="toggle-drop-btn" class="btn"></button>
        </div>    

        <div id="farm-grid" class="farm-grid"></div>
    </div>

<script>
document.addEventListener('DOMContentLoaded', function () {
    const API_ENDPOINT = '/api/panels';
    const MAIN_CONFIG_ENDPOINT = '/api/main_config';

    async function apiCall(method, url, data = null) {
        try {
            const options = {
                method: method,
                headers: { 'Content-Type': 'application/json' },
            };
            if (data) options.body = JSON.stringify(data);
            const response = await fetch(url, options);
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('API call failed:', error);
            alert('Thao tác thất bại. Vui lòng kiểm tra console log.');
            return null;
        }
    }
    
    async function loadMainConfig() {
        const config = await apiCall('GET', MAIN_CONFIG_ENDPOINT);
        if (config) {
            document.getElementById('main-min-value').value = config.min_value || 0;
            document.getElementById('main-priority-emojis').value = (config.priority_emojis || []).join('\n');
        }
    }
    
    document.getElementById('save-main-config-btn').addEventListener('click', async () => {
        const minValue = parseInt(document.getElementById('main-min-value').value) || 0;
        const emojisText = document.getElementById('main-priority-emojis').value;
        const emojis = emojisText.split(/[\n,]/).map(e => e.trim()).filter(e => e);
        
        const result = await apiCall('PUT', MAIN_CONFIG_ENDPOINT, {
            min_value: minValue,
            priority_emojis: emojis
        });
        
        if (result) {
            alert('✅ Đã lưu cấu hình Main Account!');
        }
    });
    
    function renderPanels(panels) {
        const grid = document.getElementById('farm-grid');
        grid.innerHTML = '';
        if (!panels) return;
    
        const usedTokens = new Set();
        panels.forEach(p => {
            Object.values(p.accounts).forEach(token => {
                if (token) usedTokens.add(token);
            });
        });
    
        panels.forEach(panel => {
            const panelEl = document.createElement('div');
            panelEl.className = 'panel';
            panelEl.dataset.id = panel.id;
    
            let accountSlotsHTML = '';
            
            for (let i = 1; i <= 3; i++) {
                const slotKey = `slot_${i}`;
                const currentTokenForSlot = panel.accounts[slotKey] || '';
                
                let uniqueAccountOptions = '<option value="">-- Chọn tài khoản --</option>';
                
                {{ GLOBAL_ACCOUNTS_JSON | safe }}.forEach(acc => {
                    if (!usedTokens.has(acc.token) || acc.token === currentTokenForSlot) {
                        const mainBadge = acc.id === 'acc_main' ? ' 👑' : '';
                        uniqueAccountOptions += `<option value="${acc.token}">${acc.name}${mainBadge}</option>`;
                    }
                });
    
                accountSlotsHTML += `
                    <div class="input-group">
                        <label>Slot ${i}</label>
                        <select class="account-selector" data-slot="${slotKey}">
                            ${uniqueAccountOptions}
                        </select>
                    </div>
                `;
            }
    
            panelEl.innerHTML = `
                <div class="panel-header">
                    <h3 contenteditable="true" class="panel-name">${panel.name}</h3>
                    <button class="btn btn-danger btn-sm delete-panel-btn"><i class="fas fa-trash"></i></button>
                </div>
                <div class="input-group">
                    <label>Channel ID</label>
                    <input type="text" class="channel-id-input" value="${panel.channel_id || ''}">
                    <small class="server-name-display">${panel.server_name || '(Tên server sẽ hiện ở đây)'}</small>
                </div>
                <div class="account-slots">${accountSlotsHTML}</div>
            `;
            grid.appendChild(panelEl);
            
            for (let i = 1; i <= 3; i++) {
                const slotKey = `slot_${i}`;
                const selectedToken = panel.accounts[slotKey] || '';
                panelEl.querySelector(`select[data-slot="${slotKey}"]`).value = selectedToken;
            }
        });
    }
    
    async function updateStatus() {
        try {
            const response = await fetch('/status');
            const data = await response.json();
            
            document.getElementById('bot-status').textContent = data.bot_ready ? 'Đang hoạt động' : 'Đang kết nối...';
            document.getElementById('total-panels').textContent = data.panels.length;
            document.getElementById('next-slot').textContent = `Slot ${data.current_drop_slot + 1}`;
            
            let countdown = data.countdown;
            let timeString = new Date(countdown * 1000).toISOString().substr(11, 8);
            document.getElementById('countdown').textContent = timeString;

            const toggleBtn = document.getElementById('toggle-drop-btn');
            if (toggleBtn) {
                if (data.is_auto_drop_enabled) {
                    toggleBtn.innerHTML = '<i class="fas fa-pause"></i> TẮT Auto Drop';
                    toggleBtn.classList.remove('btn-danger');
                    document.getElementById('next-slot').style.color = 'var(--accent-color)';
                } else {
                    toggleBtn.innerHTML = '<i class="fas fa-play"></i> BẬT Auto Drop';
                    toggleBtn.classList.add('btn-danger');
                    document.getElementById('next-slot').style.color = 'var(--danger-color)';
                }
            }
        } catch (e) {
            console.error("Error updating status:", e);
        }
    }

    async function fetchAndRenderPanels() {
        const response = await fetch('/status');
        const data = await response.json();
        renderPanels(data.panels);
    }
    
    document.getElementById('add-panel-btn').addEventListener('click', async () => {
        const name = prompt('Nhập tên cho panel mới:', 'Farm Server Mới');
        if (name) {
            await apiCall('POST', API_ENDPOINT, { name });
            fetchAndRenderPanels();
        }
    });

    document.getElementById('farm-grid').addEventListener('click', async (e) => {
        if (e.target.closest('.delete-panel-btn')) {
            const panelEl = e.target.closest('.panel');
            const panelId = panelEl.dataset.id;
            if (confirm(`Bạn có chắc muốn xóa panel "${panelEl.querySelector('.panel-name').textContent}"?`)) {
                await apiCall('DELETE', API_ENDPOINT, { id: panelId });
                fetchAndRenderPanels();
            }
        }
    });
    
    document.getElementById('farm-grid').addEventListener('change', async (e) => {
        const panelEl = e.target.closest('.panel');
        if (!panelEl) return;
        const panelId = panelEl.dataset.id;
    
        const payload = { id: panelId, update: {} };
    
        if (e.target.classList.contains('channel-id-input')) {
            payload.update.channel_id = e.target.value.trim();
            const updatedPanel = await apiCall('PUT', API_ENDPOINT, payload);
            if (updatedPanel) {
                const serverNameEl = panelEl.querySelector('.server-name-display');
                if (serverNameEl) {
                    serverNameEl.textContent = updatedPanel.server_name || '(Không tìm thấy server)';
                }
            }
        } else if (e.target.classList.contains('account-selector')) {
            const slot = e.target.dataset.slot;
            const token = e.target.value;
            payload.update.accounts = { [slot]: token };
            await apiCall('PUT', API_ENDPOINT, payload);
            fetchAndRenderPanels();
        }
    });
    
    document.getElementById('farm-grid').addEventListener('blur', async (e) => {
        if (e.target.classList.contains('panel-name')) {
             const panelEl = e.target.closest('.panel');
             const panelId = panelEl.dataset.id;
             const newName = e.target.textContent.trim();
             await apiCall('PUT', API_ENDPOINT, { id: panelId, update: { name: newName } });
        }
    }, true);

    const toggleBtn = document.getElementById('toggle-drop-btn');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', async () => {
            await fetch('/api/toggle_drop', { method: 'POST' });
            updateStatus();
        });
    }

    setInterval(updateStatus, 1000);
    loadMainConfig();
    fetchAndRenderPanels();
});
</script>
</body>
</html>
"""

@app.route("/")
def index():
    global_accounts_json = json.dumps([{"id": acc["id"], "name": acc["name"], "token": acc["token"]} for acc in GLOBAL_ACCOUNTS])
    return render_template_string(HTML_TEMPLATE, GLOBAL_ACCOUNTS_JSON=global_accounts_json)

@app.route("/api/panels", methods=['GET', 'POST', 'PUT', 'DELETE'])
def handle_panels():
    global panels  # ✅ QUAN TRỌNG: Thêm global ở đầu hàm
    
    if request.method == 'GET':
        return jsonify(panels)

    elif request.method == 'POST':
        data = request.get_json()
        name = data.get('name')
        if not name: 
            return jsonify({"error": "Tên là bắt buộc"}), 400
        
        new_panel = {
            "id": f"panel_{int(time.time())}_{random.randint(1000, 9999)}",  # ✅ Thêm random để tránh trùng
            "name": name,
            "channel_id": "",
            "server_name": "",
            "accounts": {f"slot_{i}": "" for i in range(1, 4)}
        }
        panels.append(new_panel)
        save_panels()
        print(f"[API] Đã tạo panel mới: {name}")  # ✅ Log để debug
        return jsonify(new_panel), 201

    elif request.method == 'PUT':
        data = request.get_json()
        panel_id = data.get('id')
        update_data = data.get('update')
        
        panel_to_update = next((p for p in panels if p.get('id') == panel_id), None)
        if not panel_to_update: 
            return jsonify({"error": "Không tìm thấy panel"}), 404

        if 'name' in update_data: 
            panel_to_update['name'] = update_data['name']

        if 'channel_id' in update_data:
            new_channel_id = update_data['channel_id'].strip()
            panel_to_update['channel_id'] = new_channel_id
            server_name = get_server_name_from_channel(new_channel_id)
            panel_to_update['server_name'] = server_name

        if 'accounts' in update_data:
            for slot, token in update_data['accounts'].items():
                panel_to_update['accounts'][slot] = token

        save_panels()
        print(f"[API] Đã cập nhật panel: {panel_id}")  # ✅ Log để debug
        return jsonify(panel_to_update)

    elif request.method == 'DELETE':
        data = request.get_json()
        panel_id = data.get('id')
        
        # ✅ FIX: Phải dùng global và không gán trực tiếp
        panels[:] = [p for p in panels if p.get('id') != panel_id]
        
        save_panels()
        print(f"[API] Đã xóa panel: {panel_id}")  # ✅ Log để debug
        return jsonify({"message": "Đã xóa panel"}), 200

@app.route("/api/main_config", methods=['GET', 'PUT'])
def handle_main_config():
    global main_panel_config
    
    if request.method == 'GET':
        return jsonify(main_panel_config)
    
    elif request.method == 'PUT':
        data = request.get_json()
        main_panel_config['min_value'] = data.get('min_value', 0)
        main_panel_config['priority_emojis'] = data.get('priority_emojis', [])
        save_panels()
        return jsonify(main_panel_config)

@app.route("/status")
def status():
    return jsonify({
        "bot_ready": bot_ready,
        "panels": panels,
        "current_drop_slot": current_drop_slot,
        "countdown": 605,
        "is_auto_drop_enabled": is_auto_drop_enabled
    })
    
@app.route("/api/toggle_drop", methods=['POST'])
def toggle_drop():
    global is_auto_drop_enabled
    is_auto_drop_enabled = not is_auto_drop_enabled
    state = "BẬT" if is_auto_drop_enabled else "TẮT"
    print(f"[CONTROL] Auto drop đã được {state}.")
    return jsonify({"message": f"Auto drop đã được {state}.", "is_enabled": is_auto_drop_enabled})

# --- HÀM KHỞI CHẠY CHÍNH ---

async def main():
    global last_drop_cycle_time
    
    if not TOKENS_STR and not TOKEN_MAIN:
        print("❌ Lỗi: Không có token nào được cấu hình. Vui lòng thêm TOKEN_MAIN hoặc TOKENS vào file .env.")
        return

    print("\n" + "="*60)
    print("🚀 KHỞI ĐỘNG MULTI-SOFI SMART CONTROL v4.0")
    print("="*60)
    
    if main_account:
        print(f"👑 Main Account: {main_account['name']}")
        print(f"   - Có khả năng phân tích button thông minh")
        print(f"   - Tự động chọn button tốt nhất theo cấu hình")
    
    print(f"📊 Tổng số tài khoản: {len(GLOBAL_ACCOUNTS)}")
    print(f"🎯 Bot Sofi ID: {SOFI_ID}")
    print("="*60 + "\n")

    load_panels()
    last_drop_cycle_time = time.time()

    def run_flask():
        try:
            from waitress import serve
            port = int(os.environ.get("PORT", 10000))
            print(f"🌐 Khởi động Web Server tại http://0.0.0.0:{port}")
            serve(app, host="0.0.0.0", port=port)
        except Exception as e:
            print(f"[FLASK ERROR] Không thể khởi động server: {e}")
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    async def updated_drop_sender_loop(session):
        global current_drop_slot, last_drop_cycle_time
        print("⏳ Vòng lặp gửi 'sd' đang chờ BOT LẮNG NGHE sẵn sàng...")
        while not bot_ready:
            await asyncio.sleep(1)
        print("✅ Bot lắng nghe đã sẵn sàng. Bắt đầu vòng lặp gửi 'sd'.\n")
    
        while True:
            if not is_auto_drop_enabled:
                await asyncio.sleep(5)
                last_drop_cycle_time = time.time()
                continue
            
            try:
                slot_key = f"slot_{current_drop_slot + 1}"
                print(f"\n{'='*60}")
                print(f"🎲 ĐANG TRONG LƯỢT CỦA SLOT {current_drop_slot + 1}")
                print(f"{'='*60}")
    
                tasks = []
                active_sends = 0
                for panel in panels:
                    channel_id = panel.get("channel_id")
                    token_to_use = panel.get("accounts", {}).get(slot_key)
    
                    if token_to_use and channel_id:
                        task = send_message_http_async(session, token_to_use, channel_id, "sd")
                        tasks.append(task)
                        active_sends += 1
                
                if tasks:
                    print(f"📤 Bắt đầu gửi {active_sends} lệnh 'sd' cho {slot_key}...")
                    for task in tasks:
                        try:
                            await task
                            await asyncio.sleep(0.5)  # Giãn cách để tránh spam
                        except Exception as e:
                            print(f"[SEND TASK ERROR] Lỗi khi gửi 1 task 'sd': {e}")
                            
                    print(f"✅ Đã gửi xong {active_sends} lệnh cho {slot_key}.")
                else:
                    print(f"⚠️ Không có tài khoản nào được cấu hình cho {slot_key}.")
    
                current_drop_slot = (current_drop_slot + 1) % 3
    
                print(f"⏰ Đã xong lượt. Chờ 240 giây (4 phút) cho lượt kế tiếp (Slot {current_drop_slot + 1})...")
                print(f"{'='*60}\n")
                
                last_drop_cycle_time = time.time()
                await asyncio.sleep(240)  # 4 phút = 240 giây
    
            except Exception as e:
                print(f"[DROP SENDER ERROR] Lỗi nghiêm trọng trong vòng lặp gửi 'sd': {e}")
                await asyncio.sleep(60)

    @app.route("/status")
    def updated_status():
        remaining_time = 0
        if is_auto_drop_enabled:
            elapsed = time.time() - last_drop_cycle_time
            remaining_time = max(0, 240 - elapsed)  # 240 giây = 4 phút
        else:
            remaining_time = 240

        return jsonify({
            "bot_ready": bot_ready,
            "panels": panels,
            "current_drop_slot": current_drop_slot,
            "countdown": remaining_time,
            "is_auto_drop_enabled": is_auto_drop_enabled
        })
    
    app.view_functions['status'] = updated_status

    async with aiohttp.ClientSession() as session:
        sender_task = asyncio.create_task(updated_drop_sender_loop(session), name='drop_sender_loop')
        listener_task = asyncio.create_task(run_listener_bot(session), name='listener_bot')
        await asyncio.gather(sender_task, listener_task)


if __name__ == "__main__":
    try:
        import waitress
    except ImportError:
        print("⏳ Đang cài đặt waitress...")
        os.system('pip install waitress')
    try:
        import aiohttp
    except ImportError:
        print("⏳ Đang cài đặt aiohttp...")
        os.system('pip install aiohttp')
        
    asyncio.run(main())
