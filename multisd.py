# TÊN FILE: multi_sofi_advanced.py
# PHIÊN BẢN: Multi-Farm Sofi Control v4.0 (Smart Button Detection) - FIXED
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
TOKEN_MAIN = os.getenv("TOKEN_MAIN", "")
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
    "min_value": 0,
    "priority_emojis": []
}
current_drop_slot = 0
is_auto_drop_enabled = True
bot_ready = False
listener_bot = None
last_drop_cycle_time = 0

detected_buttons_cache = {}

# --- CÁC HÀM TIỆN ÍCH & API DISCORD ---

SPOOFED_HEADERS = {
    "Origin": "https://discord.com",
    "Referer": "https://discord.com/channels/@me",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "X-Super-Properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIiwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzExOC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTE4LjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjk5OTk5LCJjbGllbnRfZXZlbnRfc291cmNlIjpudWxsfQ=="
}

async def send_message_http_async(session, token, channel_id, content):
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
async def click_button_http_async(session, token, channel_id, message_id, guild_id, custom_id):
    if not token: return
    
    headers = SPOOFED_HEADERS.copy()
    headers["Authorization"] = token
    
    payload = {
        "type": 3, # Loại tương tác: bấm component
        "application_id": str(SOFI_ID),
        "guild_id": str(guild_id) if guild_id else None,
        "channel_id": str(channel_id),
        "message_id": str(message_id),
        "session_id": "0", # Self-bot có thể dùng session_id đơn giản
        "data": {
            "component_type": 2, # Loại component: button
            "custom_id": custom_id
        }
    }
    
    url = "https://discord.com/api/v9/interactions"
    try:
        async with session.post(url, headers=headers, json=payload, timeout=10) as res:
            if res.status == 204: # 204 No Content là thành công
                print(f"[HTTP CLICK] ✅ Token {token[:5]}... đã click thành công (HTTP 204)")
            else:
                print(f"[HTTP CLICK ERROR] ❌ Token {token[:5]}... Lỗi khi click: {res.status} - {await res.text()}")
    except Exception as e:
        print(f"[HTTP CLICK EXCEPTION] ❌ Token {token[:5]}... Lỗi ngoại lệ khi click: {e}")
        
def save_panels():
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

# --- LOGIC PHÂN TÍCH BUTTON THÔNG MINH ---

def extract_number_from_text(text):
    if not text:
        return None
    numbers = re.findall(r'\d+', text)
    if numbers:
        return int(numbers[0])
    return None

def analyze_button_priority(button, config):
    emoji_str = str(button.emoji) if button.emoji else ""
    label = button.label or ""
    
    emoji_priority = -1
    for idx, priority_emoji in enumerate(config.get("priority_emojis", [])):
        if priority_emoji in emoji_str or priority_emoji in label:
            emoji_priority = idx
            break
    
    value = extract_number_from_text(label)
    
    if emoji_priority >= 0:
        priority_score = emoji_priority * 1000
    else:
        priority_score = 10000
    
    if value is not None:
        priority_score -= value
    
    return (priority_score, value if value else 0)

async def smart_button_click_main(message, bot, config):
    # 1. Đặt thời gian chờ ban đầu
    await asyncio.sleep(3.0) 
    
    try:
        print(f"[MAIN] 🧠 Bắt đầu phân tích button cho tin nhắn {message.id}")
        
        fetched_message = None
        found_buttons = []
        
        # 2. Vẫn "hỏi" 5 lần, mỗi lần cách 1 giây
        for attempt in range(5):
            try:
                fetched_message = await message.channel.fetch_message(message.id)
                
                found_buttons = []
                for action_row in fetched_message.components:
                    for component in action_row.children:
                        if isinstance(component, discord.Button):
                            found_buttons.append(component)
                
                if len(found_buttons) >= 3:
                    print(f"[MAIN] ✅ Đã tìm thấy {len(found_buttons)} buttons (Lần thử {attempt+1}/5).")
                    break 
            except:
                pass 
            await asyncio.sleep(1)
        
        if not found_buttons:
            print(f"[MAIN] ❌ Không tìm thấy button nào sau 5 lần thử.")
            return None
        
        button_analysis = []
        print("[MAIN] --- BẮT ĐẦU PHÂN TÍCH NỘI DUNG BUTTON ---")
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
            print(f"[MAIN] 📊 Button {idx+1}: Label='{btn.label}' | Emoji='{btn.emoji}' | Value={value} | Priority={priority}")
        print("[MAIN] --- KẾT THÚC PHÂN TÍCH ---")
        
        button_analysis.sort(key=lambda x: x["priority"])
        
        min_value = config.get("min_value", 0)
        
        # --- BẮT ĐẦU SỬA ĐỔI KỸ THUẬT CLICK ---
        
        best_button_info = None

        for btn_info in button_analysis:
            if "Join Sofi Cafe" in btn_info["label"]:
                print(f"[MAIN] ⚠️ Bỏ qua button 'Join Sofi Cafe'")
                continue 

            if btn_info["priority"] < 10000:
                print(f"[MAIN] ✅ ƯU TIÊN EMOJI! Chọn: {btn_info['label']} (Bỏ qua min_value)")
                best_button_info = btn_info
                break

            if btn_info["value"] >= min_value:
                print(f"[MAIN] ✅ Chọn button theo giá trị: {btn_info['label']} (Value: {btn_info['value']})")
                best_button_info = btn_info
                break

        # Nếu tìm thấy nút tốt nhất, tiến hành click bằng HTTP
        if best_button_info:
            main_token = bot.token
            channel_id = message.channel.id
            message_id = message.id
            guild_id = message.guild.id if message.guild else None
            custom_id = best_button_info["button"].custom_id # Lấy custom_id
            
            print(f"[MAIN] 🖱️ ĐANG GỬI LỆNH CLICK (HTTP) CHO NÚT: {best_button_info['label']}")
            
            async with aiohttp.ClientSession() as session:
                await click_button_http_async(session, main_token, channel_id, message_id, guild_id, custom_id)

            # Bỏ lệnh click cũ (Không ổn định)
            # await best_button_info["button"].click()
            
            print(f"[MAIN] 🖱️ ĐÃ GỬI XONG LỆNH CLICK (HTTP)!")
            
            detected_buttons_cache[str(message.channel.id)] = {
                "message_id": message.id,
                "best_index": best_button_info["index"],
                "timestamp": time.time()
            }
            return best_button_info["index"]
        # --- KẾT THÚC SỬA ĐỔI ---

        print(f"[MAIN] ⚠️ Không có button nào thỏa mãn điều kiện (min_value: {min_value} và đã lọc 'Join Sofi Cafe')")
        return None
            
    except Exception as e:
        print(f"[MAIN] ❌ Lỗi khi phân tích hoặc click button: {e}")
        return None

async def handle_button_click_follower(message, bot, account_info, grab_index, delay):
    # 1. Thời gian chờ ban đầu (lấy từ grab_delays)
    await asyncio.sleep(delay) 
    
    try:
        print(f"[{account_info['name']}] 🎯 Đang tìm button vị trí {grab_index+1} cho tin nhắn {message.id}...")
        
        fetched_message = None
        found_buttons = []
        
        # 2. Vẫn "hỏi" 5 lần, mỗi lần cách 1 giây
        #    Việc này vẫn do Acc Main làm, vì chỉ nó mới "thấy" message object
        for attempt in range(5):
            try:
                fetched_message = await message.channel.fetch_message(message.id)
                
                found_buttons = []
                for action_row in fetched_message.components:
                    for component in action_row.children:
                        if isinstance(component, discord.Button):
                            found_buttons.append(component)
                
                if len(found_buttons) >= 3:
                    print(f"[{account_info['name']}] ✅ (Main) Đã tìm thấy {len(found_buttons)} buttons (Lần thử {attempt+1}/5).")
                    break # Thoát vòng lặp khi tìm thấy
            except:
                pass # Bỏ qua lỗi và thử lại
            await asyncio.sleep(1) # Chờ 1 giây trước khi thử lại
        
        if len(found_buttons) > grab_index:
            target_button = found_buttons[grab_index]
            
            button_label = target_button.label or ""
            if "Join Sofi Cafe" in button_label:
                print(f"[{account_info['name']}] ⚠️ Bỏ qua button 'Join Sofi Cafe' (vị trí {grab_index+1})")
                return

            print(f"[{account_info['name']}] ℹ️ (Main) Button mục tiêu: Label='{target_button.label}', Emoji='{target_button.emoji}'")
            
            # --- BẮT ĐẦU SỬA ĐỔI QUAN TRỌNG ---
            # Lấy thông tin cần thiết cho Acc Phụ
            follower_token = account_info['token']
            channel_id = message.channel.id
            message_id = message.id
            guild_id = message.guild.id if message.guild else None
            custom_id = target_button.custom_id # Đây là chìa khóa
            
            print(f"[{account_info['name']}] 🖱️ ĐANG CHUYỂN GIAO LỆNH CLICK CHO ACC PHỤ (Token: {follower_token[:5]}...)")
            
            # Acc Phụ tự click qua HTTP
            async with aiohttp.ClientSession() as session:
                await click_button_http_async(session, follower_token, channel_id, message_id, guild_id, custom_id)
            
            # Bỏ lệnh click của Acc Main (NGUYÊN NHÂN GÂY LỖI)
            # await target_button.click() 
            # --- KẾT THÚC SỬA ĐỔI ---

            print(f"[{account_info['name']}] 🖱️ ĐÃ GỬI XONG LỆNH CLICK TỪ ACC PHỤ!")
        else:
            print(f"[{account_info['name']}] ❌ (Main) Không tìm thấy button vị trí {grab_index+1} (Tìm thấy {len(found_buttons)} buttons sau 5 lần thử).")
            
    except Exception as e:
        print(f"[{account_info['name']}] ⚠️ Lỗi trong hàm follower (Lỗi của Main): {e}")
        
async def handle_drop_detection(message, panel):
    accounts_in_panel = panel.get("accounts", {})
    
    tasks = []
    grab_indices = [0, 1, 2]
    grab_delays = [6.0, 6.2, 6.4]
    
    # --- ĐÃ SỬA ĐỔI ---
    # Logic kiểm tra "is_main_channel" đã bị xóa.
    # Giờ đây, nếu main_account tồn tại, nó sẽ LUÔN LUÔN thử smart click.
    if main_account:
        async def main_click_task():
            main_bot = None
            
            # SỬA LỖI: Gán 'bot' cho 'main_bot' khi tìm thấy
            for bot in [listener_bot]:
                if bot and bot.user:
                    main_bot = bot # <--- DÒNG NÀY ĐÃ ĐƯỢC THÊM VÀO
                    break
                    
            if main_bot:
                # smart_button_click_main sẽ được gọi cho BẤT KỲ panel nào
                await smart_button_click_main(message, main_bot, main_panel_config)
            else:
                print(f"[MAIN] ⚠️ Không tìm thấy đối tượng bot lắng nghe để click.")
        
        tasks.append(main_click_task())
    # --- KẾT THÚC SỬA ĐỔI ---

    # Logic cho các tài khoản phụ (follower) vẫn như cũ
    for i in range(3):
        slot_key = f"slot_{i + 1}"
        token = accounts_in_panel.get(slot_key)
        
        # Điều kiện này vẫn quan trọng để ngăn Main Account click 2 lần
        if token and token != (main_account["token"] if main_account else None):
            acc_info = next((acc for acc in GLOBAL_ACCOUNTS if acc["token"] == token), None)
            if acc_info:
                grab_index = grab_indices[i]
                delay = grab_delays[i]
                
                async def click_task(acc, msg, idx, d):
                    await handle_button_click_follower(msg, None, acc, idx, d)
                
                tasks.append(click_task(acc_info, message, grab_index, delay))
    
    if tasks:
        await asyncio.gather(*tasks)
        print(f"✅ Hoàn thành xử lý drop cho panel '{panel.get('name')}' (Main đã tự động tham gia)")
        
async def run_listener_bot(session):
    global bot_ready, listener_bot
    
    if not GLOBAL_ACCOUNTS:
        print("Không có token nào trong biến môi trường. Bot không thể khởi động.")
        bot_ready = True
        return
    
    listener_token = GLOBAL_ACCOUNTS[0]["token"]
    
    listener_bot = commands.Bot(
        command_prefix="!слушать",
        self_bot=True,
        chunk_guilds_at_startup=False,
        member_cache_flags=discord.MemberCacheFlags.none()
    )

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
        
        if "dropping" in content or "thả" in content or "drop" in content:
            # --- LOG MỚI ---
            print(f"[DEBUG] -> Phát hiện từ khóa drop trong kênh {message.channel.id}: {content[:50]}")
            # --- KẾT THÚC LOG MỚI ---
            
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
            # --- LOG MỚI ---
            else:
                print(f"[DEBUG] -> Đã thấy drop, nhưng kênh {message.channel.id} không nằm trong panel nào.")
            # --- KẾT THÚC LOG MỚI ---

    try:
        await listener_bot.start(listener_token)
    except discord.errors.LoginFailure:
        print(f"❌ LỖI ĐĂNG NHẬP NGHIÊM TRỌNG với token của bot lắng nghe.")
        bot_ready = True
    except Exception as e:
        print(f"❌ Lỗi không xác định với bot lắng nghe: {e}")
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
            document.getElementById('main-priority-emojis').value = (config.priority_emojis || []).join('\\n');
        }
    }
    
    document.getElementById('save-main-config-btn').addEventListener('click', async () => {
        const minValue = parseInt(document.getElementById('main-min-value').value) || 0;
        const emojisText = document.getElementById('main-priority-emojis').value;
        const emojis = emojisText.split(/[\\n,]/).map(e => e.trim()).filter(e => e);
        
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
    global panels
    if request.method == 'GET':
        return jsonify(panels)

    elif request.method == 'POST':
        data = request.get_json()
        name = data.get('name')
        if not name: return jsonify({"error": "Tên là bắt buộc"}), 400
        new_panel = {
            "id": f"panel_{int(time.time())}",
            "name": name,
            "channel_id": "",
            "server_name": "",
            "accounts": {f"slot_{i}": "" for i in range(1, 4)}
        }
        panels.append(new_panel)
        save_panels()
        return jsonify(new_panel), 201

    elif request.method == 'PUT':
        data = request.get_json()
        panel_id = data.get('id')
        update_data = data.get('update')
        panel_to_update = next((p for p in panels if p.get('id') == panel_id), None)
        if not panel_to_update: return jsonify({"error": "Không tìm thấy panel"}), 404

        if 'name' in update_data: panel_to_update['name'] = update_data['name']

        if 'channel_id' in update_data:
            new_channel_id = update_data['channel_id'].strip()
            panel_to_update['channel_id'] = new_channel_id
            server_name = get_server_name_from_channel(new_channel_id)
            panel_to_update['server_name'] = server_name

        if 'accounts' in update_data:
            for slot, token in update_data['accounts'].items():
                panel_to_update['accounts'][slot] = token

        save_panels()
        return jsonify(panel_to_update)

    elif request.method == 'DELETE':
        data = request.get_json()
        panel_id = data.get('id')
        panels[:] = [p for p in panels if p.get('id') != panel_id]
        save_panels()
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
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            print(f"[SEND TASK ERROR] Lỗi khi gửi 1 task 'sd': {e}")
                            
                    print(f"✅ Đã gửi xong {active_sends} lệnh cho {slot_key}.")
                else:
                    print(f"⚠️ Không có tài khoản nào được cấu hình cho {slot_key}.")
    
                current_drop_slot = (current_drop_slot + 1) % 3
    
                print(f"⏰ Đã xong lượt. Chờ 240 giây (4 phút) cho lượt kế tiếp (Slot {current_drop_slot + 1})...")
                print(f"{'='*60}\n")
                
                last_drop_cycle_time = time.time()
                await asyncio.sleep(245)
    
            except Exception as e:
                print(f"[DROP SENDER ERROR] Lỗi nghiêm trọng trong vòng lặp gửi 'sd': {e}")
                await asyncio.sleep(60)

    @app.route("/status")
    def updated_status():
        remaining_time = 0
        if is_auto_drop_enabled:
            elapsed = time.time() - last_drop_cycle_time
            remaining_time = max(0, 240 - elapsed)
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
