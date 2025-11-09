# TÊN FILE: multi_kd_v2.py
# PHIÊN BẢN: Multi-Farm Deep Control v4.0 (SOFI + Smart Grab)
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
SOFI_ID = 853629533855809596  # ID của bot Sofi

# Tải danh sách tài khoản từ biến môi trường
TOKENS_STR = os.getenv("TOKENS", "")
ACC_NAMES_STR = os.getenv("ACC_NAMES", "")

# Xử lý danh sách tài khoản
GLOBAL_ACCOUNTS = []
tokens_list = [token.strip() for token in TOKENS_STR.split(',') if token.strip()]
acc_names_list = [name.strip() for name in ACC_NAMES_STR.split(',') if name.strip()]

for i, token in enumerate(tokens_list):
    name = acc_names_list[i] if i < len(acc_names_list) else f"Account {i + 1}"
    GLOBAL_ACCOUNTS.append({"id": f"acc_{i}", "name": name, "token": token})

# Biến trạng thái
panels = []
current_drop_slot = 0
is_sd_loop_enabled = True
bot_ready = False
listener_bot = None
last_sd_cycle_time = 0

# Cấu hình cho Account 1 (Main account)
main_account_config = {
    "enabled": False,
    "min_value": 1,
    "priority_emojis": []
}

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
        async with session.post(url, headers=headers, json=payload, timeout=15) as res:
            if res.status != 200:
                print(f"[HTTP SEND ERROR] Lỗi khi gửi tin nhắn tới kênh {channel_id}: {res.status}")
    except Exception as e:
        print(f"[HTTP SEND EXCEPTION] Lỗi ngoại lệ khi gửi tin nhắn: {e}")

def extract_number_from_label(label):
    """Trích xuất số từ label của button."""
    if not label:
        return 0
    # Tìm tất cả các số trong label
    numbers = re.findall(r'\d+', label)
    if numbers:
        return int(numbers[0])
    return 0

def get_emoji_string(emoji_obj):
    """Chuyển đổi emoji object thành string để so sánh."""
    if emoji_obj is None:
        return ""
    return str(emoji_obj)

async def smart_click_button(message, bot_user, config):
    """
    Click button thông minh cho main account:
    - Ưu tiên button có emoji trong danh sách
    - Nếu không có emoji ưu tiên, chọn button có số cao nhất
    - Chỉ click nếu số >= min_value
    """
    await asyncio.sleep(6)  # Delay 6 giây
    
    try:
        print(f"[SMART GRAB] {bot_user.name} đang phân tích buttons...")
        
        fetched_message = None
        found_buttons = []
        
        # Tìm buttons (thử 5 lần)
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
            print(f"[SMART GRAB] {bot_user.name} - Không tìm thấy button nào")
            return
        
        # Phân tích buttons
        button_info = []
        for idx, btn in enumerate(found_buttons):
            number = extract_number_from_label(btn.label)
            emoji = get_emoji_string(btn.emoji)
            button_info.append({
                "index": idx,
                "button": btn,
                "number": number,
                "emoji": emoji,
                "label": btn.label or "No label"
            })
            print(f"  Button {idx+1}: {btn.label} | Số: {number} | Emoji: {emoji}")
        
        # Tìm button tốt nhất
        best_button = None
        
        # Bước 1: Ưu tiên theo emoji
        if config["priority_emojis"]:
            for priority_emoji in config["priority_emojis"]:
                for btn_info in button_info:
                    if priority_emoji in btn_info["emoji"] and btn_info["number"] >= config["min_value"]:
                        best_button = btn_info
                        print(f"[SMART GRAB] Tìm thấy button với emoji ưu tiên: {priority_emoji}")
                        break
                if best_button:
                    break
        
        # Bước 2: Nếu không có emoji ưu tiên, chọn số cao nhất
        if not best_button:
            valid_buttons = [b for b in button_info if b["number"] >= config["min_value"]]
            if valid_buttons:
                best_button = max(valid_buttons, key=lambda x: x["number"])
                print(f"[SMART GRAB] Chọn button có số cao nhất: {best_button['number']}")
        
        # Click button
        if best_button:
            await best_button["button"].click()
            print(f"[SMART GRAB] ✅ {bot_user.name} đã click button '{best_button['label']}'")
        else:
            print(f"[SMART GRAB] ❌ Không có button nào đáp ứng điều kiện (min: {config['min_value']})")
            
    except Exception as e:
        print(f"[SMART GRAB ERROR] {bot_user.name}: {e}")

async def normal_click_button(message, grab_index, delay, bot_user):
    """Click button bình thường cho các account còn lại."""
    await asyncio.sleep(delay)
    
    try:
        print(f"[NORMAL GRAB] {bot_user.name} đang tìm button vị trí {grab_index+1}...")
        
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
            print(f"[NORMAL GRAB] ✅ {bot_user.name} đã click button vị trí {grab_index+1}")
        else:
            print(f"[NORMAL GRAB] ❌ {bot_user.name} - Không tìm thấy button (Tìm thấy {len(found_buttons)} button)")
            
    except Exception as e:
        print(f"[NORMAL GRAB ERROR] {bot_user.name}: {e}")

async def handle_buttons(panel, message, all_panels=None):
    """Xử lý việc click button."""
    accounts_in_panel = panel.get("accounts", {})
    if not accounts_in_panel:
        return
    
    grab_times = [6.0, 6.3, 6.6]  # Tăng thời gian lên 6s
    
    tasks = []
    
    # Xử lý từng slot
    for i in range(3):
        slot_key = f"slot_{i + 1}"
        token = accounts_in_panel.get(slot_key)
        
        if not token:
            continue
        
        # Tìm bot tương ứng với token
        bot_instance = None
        for bot_data in running_bots:
            if bot_data["token"] == token:
                bot_instance = bot_data["bot"]
                break
        
        if not bot_instance:
            continue
        
        # Kiểm tra xem có phải main account không
        is_main_account = (token == GLOBAL_ACCOUNTS[0]["token"]) if GLOBAL_ACCOUNTS else False
        
        if is_main_account and main_account_config["enabled"]:
            # Main account dùng smart grab
            tasks.append(smart_click_button(message, bot_instance.user, main_account_config))
        else:
            # Account thường dùng normal grab
            delay = grab_times[i]
            tasks.append(normal_click_button(message, i, delay, bot_instance.user))
    
    if tasks:
        await asyncio.gather(*tasks)
        print(f"Đã hoàn thành các tác vụ click button cho drop trong kênh {message.channel.id}")

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
        "main_account_config": main_account_config
    }
    
    try:
        def do_save():
            req = requests.put(url, json=data_to_save, headers=headers, timeout=15)
            if req.status_code == 200:
                print("[Settings] Đã lưu cấu hình lên JSONBin.io thành công.")
            else:
                print(f"[Settings] Lỗi khi lưu cài đặt: {req.status_code} - {req.text}")
        threading.Thread(target=do_save, daemon=True).start()
    except Exception as e:
        print(f"[Settings] Exception khi lưu cài đặt: {e}")

def load_panels():
    """Tải cấu hình các panel từ JSONBin.io"""
    global panels, main_account_config
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
                main_account_config.update(data.get("main_account_config", main_account_config))
                print(f"[Settings] Đã tải {len(panels)} panel từ JSONBin.io.")
            elif isinstance(data, list):
                panels = data
                print(f"[Settings] Đã tải {len(panels)} panel (format cũ).")
        else:
            print(f"[Settings] Lỗi khi tải cài đặt: {req.status_code}")
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

# --- LOGIC BOT CHÍNH ---

running_bots = []

async def run_listener_bot(token, account_info):
    """Chạy một bot để lắng nghe drop."""
    global running_bots
    
    bot = commands.Bot(
        command_prefix="!слушать",
        self_bot=True,
        chunk_guilds_at_startup=False,
        member_cache_flags=discord.MemberCacheFlags.none()
    )
    
    @bot.event
    async def on_ready():
        print(f"[BOT] Đã đăng nhập: {bot.user.name} (ID: {bot.user.id})")
        running_bots.append({"bot": bot, "token": token, "account": account_info})
    
    @bot.event
    async def on_message(message):
        if message.author.id != SOFI_ID:
            return
        
        content = message.content.lower()
        if "dropping" not in content and "thả" not in content:
            return
        
        # Tìm panel tương ứng với kênh này
        found_panel = None
        for p in panels:
            if p.get("channel_id") == str(message.channel.id):
                found_panel = p
                break
        
        if found_panel:
            print(f"Phát hiện drop trong kênh {message.channel.id} (Panel: '{found_panel.get('name')}')")
            asyncio.create_task(handle_buttons(found_panel, message, panels))
    
    try:
        await bot.start(token)
    except Exception as e:
        print(f"[BOT ERROR] Lỗi với bot {account_info['name']}: {e}")

async def start_all_listener_bots():
    """Khởi động tất cả các bot listener."""
    global bot_ready
    
    if not GLOBAL_ACCOUNTS:
        print("Không có token nào trong biến môi trường.")
        bot_ready = True
        return
    
    tasks = []
    for acc in GLOBAL_ACCOUNTS:
        tasks.append(run_listener_bot(acc["token"], acc))
    
    # Đợi tất cả bot đăng nhập
    await asyncio.gather(*tasks, return_exceptions=True)
    bot_ready = True

# --- GIAO DIỆN WEB & API FLASK ---

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Multi-Farm Deep Control v4.0</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --primary-bg: #111; --secondary-bg: #1d1d1d; --panel-bg: #2a2a2a; --border-color: #444; --text-primary: #f0f0f0; --text-secondary: #aaa; --accent-color: #00aaff; --danger-color: #ff4444; --success-color: #44ff44; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: var(--primary-bg); color: var(--text-primary); margin: 0; padding: 20px; }
        .container { max-width: 1800px; margin: 0 auto; }
        .header { text-align: center; margin-bottom: 30px; }
        .header h1 { color: var(--accent-color); font-weight: 600; }
        .status-bar { display: flex; justify-content: space-around; background-color: var(--secondary-bg); padding: 15px; border-radius: 8px; margin-bottom: 20px; flex-wrap: wrap; gap: 15px; }
        .status-item { text-align: center; }
        .status-item span { display: block; font-size: 0.9em; color: var(--text-secondary); }
        .status-item strong { font-size: 1.2em; color: var(--accent-color); }
        .controls { display: flex; justify-content: center; gap: 15px; margin-bottom: 30px; flex-wrap: wrap; }
        .btn { background-color: var(--accent-color); color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 1em; transition: background-color 0.3s; }
        .btn:hover { background-color: #0088cc; }
        .btn-danger { background-color: var(--danger-color); }
        .btn-danger:hover { background-color: #cc3333; }
        .btn-success { background-color: var(--success-color); color: #000; }
        .btn-success:hover { background-color: #33cc33; }
        .farm-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 20px; }
        .panel { background-color: var(--secondary-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 20px; position: relative; }
        .panel.main-panel { border: 2px solid var(--success-color); }
        .panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid var(--border-color); padding-bottom: 10px; }
        .panel-header h3 { margin: 0; font-size: 1.2em; }
        .input-group { margin-bottom: 15px; }
        .input-group label { display: block; color: var(--text-secondary); margin-bottom: 5px; font-size: 0.9em; }
        .input-group input, .input-group select, .input-group textarea { width: 100%; background-color: var(--primary-bg); border: 1px solid var(--border-color); color: var(--text-primary); padding: 8px; border-radius: 5px; box-sizing: border-box; }
        .input-group textarea { min-height: 60px; resize: vertical; font-family: inherit; }
        .account-slots { display: grid; grid-template-columns: 1fr; gap: 15px; }
        .server-name-display { font-size: 0.8em; color: var(--text-secondary); margin-top: 5px; display: block; height: 1.2em; }
        .main-config-section { background-color: var(--panel-bg); padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 2px solid var(--success-color); }
        .checkbox-group { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
        .checkbox-group input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; }
        .emoji-input { font-size: 1.2em; }
        .help-text { font-size: 0.85em; color: var(--text-secondary); font-style: italic; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Multi-Farm Deep Control v4.0</h1>
            <p>Hệ thống quản lý farm thông minh với Sofi Bot</p>
        </div>

        <div class="status-bar">
            <div class="status-item"><span>Trạng thái Bot</span><strong id="bot-status">Đang khởi động...</strong></div>
            <div class="status-item"><span>Tổng số Panel</span><strong id="total-panels">0</strong></div>
            <div class="status-item"><span>Lượt Drop Kế Tiếp</span><strong id="next-slot">Slot 1</strong></div>
            <div class="status-item"><span>Thời gian chờ</span><strong id="countdown">--:--:--</strong></div>
        </div>

        <!-- Main Account Config -->
        <div class="main-config-section">
            <h3>⚙️ Cấu hình Account Main (Token đầu tiên)</h3>
            <div class="checkbox-group">
                <input type="checkbox" id="main-enabled">
                <label for="main-enabled"><strong>Bật chế độ Smart Grab cho Account Main</strong></label>
            </div>
            <div class="input-group">
                <label>Giá trị tối thiểu</label>
                <input type="number" id="main-min-value" min="1" value="1">
                <div class="help-text">Account main chỉ nhặt button có số >= giá trị này</div>
            </div>
            <div class="input-group">
                <label>Danh sách Emoji ưu tiên (mỗi dòng 1 emoji)</label>
                <textarea id="main-emojis" class="emoji-input" placeholder="🔥
⭐
💎"></textarea>
                <div class="help-text">Emoji ở trên được ưu tiên hơn. Nếu không có emoji ưu tiên, sẽ chọn số cao nhất.</div>
            </div>
            <button id="save-main-config" class="btn btn-success">💾 Lưu cấu hình Main</button>
        </div>

        <div class="controls">
            <button id="add-panel-btn" class="btn"><i class="fas fa-plus"></i> Thêm Panel Mới</button>
            <button id="toggle-sd-btn" class="btn"></button>
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
            if (!response.ok) throw new Error(\`HTTP error! status: \${response.status}\`);
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
            document.getElementById('main-enabled').checked = config.enabled;
            document.getElementById('main-min-value').value = config.min_value;
            document.getElementById('main-emojis').value = config.priority_emojis.join('\\n');
        }
    }
    
    document.getElementById('save-main-config').addEventListener('click', async () => {
        const enabled = document.getElementById('main-enabled').checked;
        const min_value = parseInt(document.getElementById('main-min-value').value) || 1;
        const emojis_text = document.getElementById('main-emojis').value;
        const priority_emojis = emojis_text.split('\\n').map(e => e.trim()).filter(e => e);
        
        const result = await apiCall('POST', MAIN_CONFIG_ENDPOINT, {
            enabled: enabled,
            min_value: min_value,
            priority_emojis: priority_emojis
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
                const slotKey = \`slot_\${i}\`;
                const currentTokenForSlot = panel.accounts[slotKey] || '';
                
                let uniqueAccountOptions = '<option value="">-- Chọn tài khoản --</option>';
                
                {{ GLOBAL_ACCOUNTS_JSON | safe }}.forEach(acc => {
                    if (!usedTokens.has(acc.token) || acc.token === currentTokenForSlot) {
                        uniqueAccountOptions += \`<option value="\${acc.token}">\${acc.name}</option>\`;
                    }
                });
    
                accountSlotsHTML += \`
                    <div class="input-group">
                        <label>Slot \${i}</label>
                        <select class="account-selector" data-slot="\${slotKey}">
                            \${uniqueAccountOptions}
                        </select>
                    </div>
                \`;
            }
    
            panelEl.innerHTML = \`
                <div class="panel-header">
                    <h3 contenteditable="true" class="panel-name">\${panel.name}</h3>
                    <button class="btn btn-danger btn-sm delete-panel-btn"><i class="fas fa-trash"></i></button>
                </div>
                <div class="input-group">
                    <label>Channel ID</label>
                    <input type
="text" class="channel-id-input" value="${panel.channel_id || ''}">
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

            const toggleBtn = document.getElementById('toggle-sd-btn');
            if (toggleBtn) {
                if (data.is_sd_loop_enabled) {
                    toggleBtn.textContent = 'TẮT VÒNG LẶP SD';
                    toggleBtn.classList.remove('btn-danger');
                    document.getElementById('next-slot').style.color = 'var(--accent-color)';
                } else {
                    toggleBtn.textContent = 'BẬT VÒNG LẶP SD';
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

    const toggleBtn = document.getElementById('toggle-sd-btn');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', async () => {
            await fetch('/api/toggle_sd', { method: 'POST' });
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
    global_accounts_json = json.dumps([{"name": acc["name"], "token": acc["token"]} for acc in GLOBAL_ACCOUNTS])
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
            "id": f"panel_{int(time.time())}_{random.randint(1000,9999)}",
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
        panels = [p for p in panels if p.get('id') != panel_id]
        save_panels()
        return jsonify({"message": "Đã xóa panel"}), 200

@app.route("/api/main_config", methods=['GET', 'POST'])
def handle_main_config():
    global main_account_config
    
    if request.method == 'GET':
        return jsonify(main_account_config)
    
    elif request.method == 'POST':
        data = request.get_json()
        main_account_config['enabled'] = data.get('enabled', False)
        main_account_config['min_value'] = data.get('min_value', 1)
        main_account_config['priority_emojis'] = data.get('priority_emojis', [])
        save_panels()
        return jsonify(main_account_config)

@app.route("/status")
def status():
    remaining_time = 0
    if is_sd_loop_enabled:
        elapsed = time.time() - last_sd_cycle_time
        remaining_time = max(0, 240 - elapsed)  # 4 phút = 240 giây
    else:
        remaining_time = 240

    return jsonify({
        "bot_ready": bot_ready,
        "panels": panels,
        "current_drop_slot": current_drop_slot,
        "countdown": remaining_time,
        "is_sd_loop_enabled": is_sd_loop_enabled
    })
    
@app.route("/api/toggle_sd", methods=['POST'])
def toggle_sd():
    global is_sd_loop_enabled
    is_sd_loop_enabled = not is_sd_loop_enabled
    state = "BẬT" if is_sd_loop_enabled else "TẮT"
    print(f"[CONTROL] Vòng lặp gửi 'sd' đã được {state}.")
    return jsonify({"message": f"Vòng lặp gửi 'sd' đã được {state}.", "is_enabled": is_sd_loop_enabled})

# --- HÀM KHỞI CHẠY CHÍNH ---

async def main():
    global last_sd_cycle_time
    
    if not TOKENS_STR:
        print("Lỗi: Biến môi trường TOKENS chưa được thiết lập.")
        return

    load_panels()
    last_sd_cycle_time = time.time()

    def run_flask():
        try:
            from waitress import serve
            port = int(os.environ.get("PORT", 10000))
            print(f"Khởi động Web Server tại http://0.0.0.0:{port}")
            serve(app, host="0.0.0.0", port=port)
        except Exception as e:
            print(f"[FLASK ERROR] Không thể khởi động server: {e}")
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    async def sd_sender_loop(session):
        global current_drop_slot, last_sd_cycle_time, bot_ready
        print("Vòng lặp gửi 'sd' đang chờ các bot sẵn sàng...")
        
        # Đợi tất cả bot đăng nhập
        max_wait = 60  # Đợi tối đa 60 giây
        waited = 0
        while len(running_bots) < len(GLOBAL_ACCOUNTS) and waited < max_wait:
            await asyncio.sleep(1)
            waited += 1
        
        if len(running_bots) == 0:
            print("⚠️ Không có bot nào đăng nhập thành công!")
            bot_ready = True
            return
        
        bot_ready = True
        print(f"✅ Đã có {len(running_bots)}/{len(GLOBAL_ACCOUNTS)} bot sẵn sàng. Bắt đầu vòng lặp gửi 'sd'.")
    
        while True:
            if not is_sd_loop_enabled:
                await asyncio.sleep(5)
                last_sd_cycle_time = time.time()
                continue
            
            try:
                slot_key = f"slot_{current_drop_slot + 1}"
                print(f"\n--- Đang trong lượt của Slot {current_drop_slot + 1} ---")
    
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
                    print(f"Bắt đầu gửi {active_sends} lệnh 'sd' cho {slot_key}...")
                    for task in tasks:
                        try:
                            await task
                            await asyncio.sleep(0.5)  # Tăng delay để tránh spam
                        except Exception as e:
                            print(f"[SEND TASK ERROR] Lỗi khi gửi 1 task 'sd': {e}")
                            
                    print(f"Đã gửi xong {active_sends} lệnh cho {slot_key}.")
                else:
                    print(f"Không có tài khoản nào được cấu hình cho {slot_key}.")
    
                current_drop_slot = (current_drop_slot + 1) % 3
    
                print(f"Đã xong lượt. Chờ 240 giây (4 phút) cho lượt kế tiếp (Slot {current_drop_slot + 1})...")
                last_sd_cycle_time = time.time()
                await asyncio.sleep(240)  # 4 phút
    
            except Exception as e:
                print(f"[SD SENDER ERROR] Lỗi nghiêm trọng trong vòng lặp gửi 'sd': {e}")
                await asyncio.sleep(60)

    # Khởi tạo AIOHTTP ClientSession
    async with aiohttp.ClientSession() as session:
        # Tạo task cho vòng lặp gửi 'sd'
        sender_task = asyncio.create_task(sd_sender_loop(session), name='sd_sender_loop')
        
        # Tạo task để chạy tất cả listener bots
        listener_task = asyncio.create_task(start_all_listener_bots(), name='all_listener_bots')

        # Chạy đồng thời 2 task chính
        await asyncio.gather(sender_task, listener_task, return_exceptions=True)


if __name__ == "__main__":
    # Kiểm tra và cài đặt dependencies
    try:
        import waitress
    except ImportError:
        print("Đang cài đặt waitress...")
        os.system('pip install waitress')
    
    try:
        import aiohttp
    except ImportError:
        print("Đang cài đặt aiohttp...")
        os.system('pip install aiohttp')
    
    try:
        import discord
    except ImportError:
        print("Đang cài đặt discord.py-self...")
        os.system('pip install discord.py-self')
        
    print("=" * 60)
    print("🚀 MULTI-FARM DEEP CONTROL V4.0 - SOFI EDITION")
    print("=" * 60)
    print("📋 Tính năng:")
    print("  ✅ Tự động gửi 'sd' mỗi 4 phút")
    print("  ✅ Click button với delay 6 giây")
    print("  ✅ Smart Grab cho Account Main:")
    print("     - Ưu tiên button có emoji được chỉ định")
    print("     - Chọn button có số cao nhất nếu không có emoji")
    print("     - Chỉ nhặt button >= giá trị tối thiểu")
    print("  ✅ Account Main có thể tham gia tất cả các panel")
    print("  ✅ Quản lý đa panel qua giao diện web")
    print("=" * 60)
    
    asyncio.run(main())
