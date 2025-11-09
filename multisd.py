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

# --- SPOOFED HEADERS ---
SPOOFED_HEADERS = {
    "Origin": "https://discord.com",
    "Referer": "https://discord.com/channels/@me",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "X-Super-Properties": "eyJvcyI6IldpbmRvd3MiLCJicm93c2VyIjoiQ2hyb21lIiwiZGV2aWNlIjoiIiwic3lzdGVtX2xvY2FsZSI6ImVuLVVTIiwiYnJvd3Nlcl91c2VyX2FnZW50IjoiTW96aWxsYS81LjAgKFdpbmRvd3MgTlQgMTAuMDsgV2luNjQ7IHg2NCkgQXBwbGVXZWJLaXQvNTM3LjM2IChLSFRNTCwgbGlrZSBHZWNrbykgQ2hyb21lLzExOC4wLjAuMCBTYWZhcmkvNTM3LjM2IiwiYnJvd3Nlcl92ZXJzaW9uIjoiMTE4LjAuMC4wIiwib3NfdmVyc2lvbiI6IjEwIiwicmVmZXJyZXIiOiIiLCJyZWZlcnJpbmdfZG9tYWluIjoiIiwicmVmZXJyZXJfY3VycmVudCI6IiIsInJlZmVycmluZ19kb21haW5fY3VycmVudCI6IiIsInJlbGVhc2VfY2hhbm5lbCI6InN0YWJsZSIsImNsaWVudF9idWlsZF9udW1iZXIiOjk5OTk5LCJjbGllbnRfZXZlbnRfc291cmNlIjpudWxsfQ=="
}

# --- CÁC HÀM TIỆN ÍCH ---
async def send_message_http_async(session, token, channel_id, content):
    """Gửi tin nhắn bằng AIOHTTP + Spoofed Headers."""
    if not token or not channel_id: 
        return
    
    headers = SPOOFED_HEADERS.copy()
    headers["Authorization"] = token
    
    payload = {"content": content}
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    try:
        async with session.post(url, headers=headers, json=payload, timeout=10) as res:
            if res.status != 200:
                print(f"[HTTP SEND ERROR] Lỗi {res.status} khi gửi tin nhắn tới kênh {channel_id}")
    except Exception as e:
        print(f"[HTTP SEND EXCEPTION] {e}")

def save_panels():
    """Lưu cấu hình panels lên JSONBin.io"""
    api_key = os.getenv("JSONBIN_API_KEY")
    bin_id = os.getenv("JSONBIN_BIN_ID")
    if not api_key or not bin_id:
        print("[Settings] Thiếu API Key hoặc Bin ID của JSONBin.")
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
                print("[Settings] Đã lưu cấu hình thành công.")
            else:
                print(f"[Settings] Lỗi {req.status_code}: {req.text}")
        threading.Thread(target=do_save, daemon=True).start()
    except Exception as e:
        print(f"[Settings] Exception: {e}")

def load_panels():
    """Tải cấu hình panels từ JSONBin.io"""
    global panels, main_panel_config
    api_key = os.getenv("JSONBIN_API_KEY")
    bin_id = os.getenv("JSONBIN_BIN_ID")
    if not api_key or not bin_id:
        print("[Settings] Thiếu API Key hoặc Bin ID. Bắt đầu với cấu hình rỗng.")
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
            print(f"[Settings] Lỗi {req.status_code}: {req.text}")
    except Exception as e:
        print(f"[Settings] Exception: {e}")

def get_server_name_from_channel(channel_id):
    """Lấy tên server từ Channel ID."""
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

# --- LOGIC PHÂN TÍCH BUTTON ---
def extract_number_from_text(text):
    """Trích xuất số từ text"""
    if not text:
        return None
    numbers = re.findall(r'\d+', text)
    if numbers:
        return int(numbers[0])
    return None

def analyze_button_priority(button, config):
    """Phân tích độ ưu tiên của button"""
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
    """Main Account: Phân tích và click button thông minh"""
    await asyncio.sleep(6)
    
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
            print(f"[MAIN] ❌ Không tìm thấy button")
            return None
        
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
            print(f"[MAIN] 📊 Button {idx+1}: {btn.label} | Value: {value} | Priority: {priority}")
        
        button_analysis.sort(key=lambda x: x["priority"])
        
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
            
            detected_buttons_cache[str(message.channel.id)] = {
                "message_id": message.id,
                "best_index": best_button["index"],
                "timestamp": time.time()
            }
            
            return best_button["index"]
        else:
            print(f"[MAIN] ⚠️ Không có button nào thỏa mãn (min_value: {min_value})")
            return None
            
    except Exception as e:
        print(f"[MAIN] ❌ Lỗi: {e}")
        return None

async def handle_button_click_follower(message, bot, account_info, grab_index, delay):
    """Các account theo sau: Click button theo chỉ định"""
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
            print(f"[{account_info['name']}] ❌ Không tìm thấy button")
            
    except Exception as e:
        print(f"[{account_info['name']}] ⚠️ Lỗi: {e}")

async def handle_drop_detection(message, panel):
    """Xử lý khi phát hiện drop"""
    accounts_in_panel = panel.get("accounts", {})
    if not accounts_in_panel:
        return
    
    tasks = []
    grab_indices = [0, 1, 2]
    grab_delays = [6.0, 6.2, 6.4]
    
    is_main_channel = False
    if main_account and str(message.channel.id) == panel.get("channel_id"):
        for slot_key, token in accounts_in_panel.items():
            if token == main_account["token"]:
                is_main_channel = True
                break
    
    if is_main_channel and main_account:
        async def main_click_task():
            if listener_bot:
                await smart_button_click_main(message, listener_bot, main_panel_config)
        
        tasks.append(main_click_task())
    
    for i in range(3):
        slot_key = f"slot_{i + 1}"
        token = accounts_in_panel.get(slot_key)
        
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
        print(f"✅ Hoàn thành xử lý drop cho panel '{panel.get('name')}'")

async def run_listener_bot(session):
    """Chạy bot chính để lắng nghe sự kiện drop"""
    global bot_ready, listener_bot
    
    if not GLOBAL_ACCOUNTS:
        print("❌ Không có token nào. Bot không thể khởi động.")
        bot_ready = True
        return
    
    listener_token = GLOBAL_ACCOUNTS[0]["token"]
    
    # ✅ Không cần intents cho self-bot
    listener_bot = commands.Bot(
        command_prefix="!слушать",
        self_bot=True
    )

    @listener_bot.event
    async def on_ready():
        global bot_ready
        print("-" * 60)
        print(f"🤖 BOT LẮNG NGHE ĐÃ SẴN SÀNG!")
        print(f"👤 Đăng nhập: {listener_bot.user} (ID: {listener_bot.user.id})")
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
        print(f"❌ LỖI ĐĂNG NHẬP với token của bot lắng nghe.")
        print("💡 Kiểm tra lại TOKEN_MAIN hoặc TOKENS trong file .env")
        bot_ready = True
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        import traceback
        traceback.print_exc()
        bot_ready = True

# --- FLASK WEB ---
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
        .status-bar { display: flex; justify-content: space-around; background-color: var(--secondary-bg); padding: 15px; border-radius: 8px; margin-bottom: 20px; flex-wrap: wrap; gap: 15px; }
        .status-item { text-align: center; }
        .status-item span { display: block; font-size: 0.9em; color: var(--text-secondary); }
        .status-item strong { font-size: 1.2em; color: var(--accent-color); }
        .main-config { background-color: var(--secondary-bg); border: 2px solid var(--success-color); border-radius: 8px; padding: 20px; margin-bottom: 20px; }
        .main-config h2 { color: var(--success-color); margin-top: 0; }
        .main-config-grid { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; }
        .controls { display: flex; justify-content: center; gap: 15px; margin-bottom: 30px; }
        .btn { background-color: var(--accent-color); color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-size: 1em; transition: all 0.3s; }
        .btn:hover { background-color: #0088cc; }
        .btn-danger { background-color: var(--danger-color); }
        .btn-success { background-color: var(--success-color); color: #111; }
        .farm-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 20px; }
        .panel { background-color: var(--secondary-bg); border: 1px solid var(--border-color); border-radius: 8px; padding: 20px; }
        .panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 1px solid var(--border-color); padding-bottom: 10px; }
        .input-group { margin-bottom: 15px; }
        .input-group label { display: block; color: var(--text-secondary); margin-bottom: 5px; }
        .input-group input, .input-group select, .input-group textarea { width: 100%; background-color: var(--primary-bg); border: 1px solid var(--border-color); color: var(--text-primary); padding: 8px; border-radius: 5px; box-sizing: border-box; }
        .server-name-display { font-size: 0.8em; color: var(--text-secondary); margin-top: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><i class="fas fa-brain"></i> Multi-Sofi Smart Control v4.0</h1>
        </div>

        <div class="status-bar">
            <div class="status-item"><span>Trạng thái Bot</span><strong id="bot-status">Đang khởi động...</strong></div>
            <div class="status-item"><span>Tổng số Panel</span><strong id="total-panels">0</strong></div>
            <div class="status-item"><span>Lượt Drop Kế Tiếp</span><strong id="next-slot">Slot 1</strong></div>
        </div>

        <div class="main-config">
            <h2><i class="fas fa-crown"></i> Cấu Hình Main Account</h2>
            <div class="main-config-grid">
                <div class="input-group">
                    <label>Giá trị tối thiểu (Min Value)</label>
                    <input type="number" id="main-min-value" min="0" placeholder="VD: 3">
                </div>
                <div class="input-group">
                    <label>Emoji ưu tiên (Priority Emojis)</label>
                    <textarea id="main-priority-emojis" placeholder="VD: ⭐,🌟,✨"></textarea>
                </div>
            </div>
            <button id="save-main-config-btn" class="btn btn-success"><i class="fas fa-save"></i> Lưu Cấu Hình Main</button>
        </div>

        <div class="controls">
            <button id="add-panel-btn" class="btn"><i class="fas fa-plus"></i> Thêm Panel Mới</button>
        </div>

        <div id="farm-grid" class="farm-grid"></div>
    </div>

<script>
document.addEventListener('DOMContentLoaded', function () {
    const API_ENDPOINT = '/api/panels';
    const MAIN_CONFIG_ENDPOINT = '/api/main_config';

    async function apiCall(method, url, data = null) {
        try {
            const options = { method, headers: { 'Content-Type': 'application/json' } };
            if (data) options.body = JSON.stringify(data);
            const response = await fetch(url, options);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('API Error:', error);
            alert('Thao tác thất bại!');
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
        
        if (result) alert('✅ Đã lưu cấu hình Main Account!');
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
                const slotKey = `slot_\${i}`;
                const currentTokenForSlot = panel.accounts[slotKey] || '';
                
                let uniqueAccountOptions = '<option value="">-- Chọn tài khoản --</option>';
                
                {{ GLOBAL_ACCOUNTS_JSON | safe }}.forEach(acc => {
                    if (!usedTokens.has(acc.token) || acc.token === currentTokenForSlot) {
                        const mainBadge = acc.id === 'acc_main' ? ' 👑' : '';
                        uniqueAccountOptions += `<option value="\${acc.token}">\${acc.name}\${mainBadge}</option>`;
                    }
                });
    
                accountSlotsHTML += `
                    <div class="input-group">
                        <label>Slot \${i}</label>
                        <select class="account-selector" data-slot="\${slotKey}">
                            \${uniqueAccountOptions}
                        </select>
                    </div>
                `;
            }
    
            panelEl.innerHTML = `
                <div class="panel-header">
                    <h3 contenteditable="true" class="panel-name">\${panel.name}</h3>
                    <button class="btn btn-danger delete-panel-btn"><i class="fas fa-trash"></i></button>
                </div>
                <div class="input-group">
                    <label>Channel ID</label>
                    <input type="text" class="channel-id-input" value="\${panel.channel_id || ''}">
                    <small class="server-name-display">\${panel.server_name || '(Tên server sẽ hiện ở đây)'}</small>
                </div>
                <div class="account-slots">\${accountSlotsHTML}</div>
