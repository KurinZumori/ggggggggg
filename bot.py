import discord
from discord import app_commands
import random
import string
import json
import os
import asyncio
import base64
import uuid
import aiohttp
from datetime import datetime, timedelta, timezone
import secrets

from fastapi import FastAPI, Form, Request, Depends, HTTPException, status, Response, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import threading

CONFIG_FILE = "config.json"
KEY_FILE = "keys.json"
ACCOUNTS_FILE = "accounts.json"

def load_json(filename, default_val):
    if not os.path.exists(filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(default_val, f, indent=4)
        return default_val
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_val

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

config = load_json(CONFIG_FILE, {
    "bot_token": "YOUR_DISCORD_BOT_TOKEN_HERE", 
    "admin_ids": ["YOUR_DISCORD_USER_ID_HERE"],
    "web_user": "admin",
    "web_pass": "123456"
})

DISCORD_BOT_TOKEN = config.get("bot_token", "").strip()
ADMIN_IDS = [str(uid) for uid in config.get("admin_ids", [])]
WEB_USER = config.get("web_user", "admin")
WEB_PASS = config.get("web_pass", "123456")
ACTIVE_SESSIONS = set()

def parse_duration(duration_str: str) -> int:
    duration_str = duration_str.strip().lower()
    if not duration_str:
        return 0
    unit = duration_str[-1]
    val_str = duration_str[:-1]
    try:
        val = int(val_str)
    except ValueError:
        return 0

    if unit == 'p': return val * 60
    elif unit == 'h': return val * 3600
    elif unit == 'd': return val * 86400
    elif unit == 'm': return val * 30 * 86400
    return 0

def get_super_properties():
    client_props = {
        "os": "Windows", "browser": "Discord Client", "release_channel": "stable",
        "client_version": "1.0.9215", "os_version": "10.0.19045", "os_arch": "x64",
        "app_arch": "x64", "system_locale": "en-US", "has_client_mods": False,
        "client_launch_id": str(uuid.uuid4()), "browser_version": "37.6.0",
        "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9215 Chrome/138.0.7204.251 Electron/37.6.0 Safari/537.36",
        "os_sdk_version": "19045", "client_build_number": 471091, "native_build_number": 72186,
        "client_event_source": None, "launch_signature": str(uuid.uuid4()),
        "client_heartbeat_session_id": str(uuid.uuid4()), "client_app_state": "focused"
    }
    return base64.b64encode(json.dumps(client_props, separators=(',', ':')).encode('utf-8')).decode('utf-8')

async def check_token_is_valid(session, token):
    headers = {
        "Authorization": token,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9215 Chrome/138.0.7204.251 Electron/37.6.0 Safari/537.36"
    }
    try:
        async with session.get("https://discord.com/api/v9/users/@me", headers=headers) as res:
            if res.status == 200:
                return True
    except Exception:
        pass
    return False

async def trigger_webhook(client, user_id_str, quest_name):
    print(f"[SUCCESS] Đã hoàn thành quest '{quest_name}' cho User ID: {user_id_str}")
    try:
        user = client.get_user(int(user_id_str)) or await client.fetch_user(int(user_id_str))
        if user:
            embed = discord.Embed(
                title="🎉 Hoàn Thành Quest Thành Công!",
                description="Hệ thống đã tự động cày xong nhiệm vụ Discord cho tài khoản của bạn.",
                color=discord.Color.purple()
            )
            embed.add_field(name="🔹 Tên Quest", value=f"`{quest_name}`", inline=False)
            embed.set_footer(text="Auto Quest System • Đa tài khoản song song")
            await user.send(embed=embed)
    except Exception:
        pass

async def process_single_quest(client, session, quest_raw, headers, user_id_str):
    quest_id = quest_raw.get("id")
    config_q = quest_raw.get("config", {})
    user_status = quest_raw.get("user_status") or {}
    quest_name = config_q.get("messages", {}).get("quest_name", "").strip() or quest_id

    if user_status.get("completed_at") and user_status.get("claimed_at"):
        return
    if user_status.get("completed_at"):
        await trigger_webhook(client, user_id_str, quest_name)
        return

    task_config_v2 = config_q.get("task_config_v2", {})
    task_config = config_q.get("task_config", {})
    tasks = task_config_v2.get("tasks") or task_config.get("tasks") or {}

    task_type = None
    for t in ["PLAY_ON_DESKTOP", "WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE", "STREAM_ON_DESKTOP", "PLAY_ACTIVITY"]:
        if t in tasks:
            task_type = t
            break

    if not task_type:
        return

    task_data = tasks[task_type]
    target = task_data.get("target", 900)
    progress_data = user_status.get("progress", {}).get(task_type) or {}
    done = progress_data.get("value", 0)

    if done >= target:
        await trigger_webhook(client, user_id_str, quest_name)
        return

    if task_type in ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE"):
        enrolled_at_str = user_status.get("enrolled_at")
        enrolled_at = datetime.fromisoformat(enrolled_at_str.replace("Z", "+00:00")).timestamp() if enrolled_at_str else datetime.now(timezone.utc).timestamp()
        
        while done < target:
            max_allowed = int(datetime.now(timezone.utc).timestamp() - enrolled_at) + 10
            diff = max_allowed - done
            next_val = done + 7
            
            if diff >= 7:
                timestamp = min(target, next_val + random.random())
                try:
                    async with session.post(f"https://discord.com/api/v9/quests/{quest_id}/video-progress", json={"timestamp": timestamp}, headers=headers) as res:
                        if res.status in (200, 202):
                            res_data = await res.json()
                            done = min(target, next_val)
                            if res_data.get("completed_at"):
                                break
                        elif res.status == 429:
                            r_data = await res.json()
                            await asyncio.sleep(r_data.get("retry_after", 5))
                            continue
                        else:
                            await asyncio.sleep(15)
                            continue
                except Exception:
                    await asyncio.sleep(15)
                    continue
            await asyncio.sleep(1)
        await trigger_webhook(client, user_id_str, quest_name)
    else:
        apps = task_data.get("applications") or []
        app_id = apps[0].get("id") if apps else config_q.get("application", {}).get("id")
        if not app_id:
            return

        last_hb = 0
        is_completed = False
        while not is_completed:
            now_ts = datetime.now(timezone.utc).timestamp()
            if now_ts - last_hb >= 60:
                try:
                    async with session.post(f"https://discord.com/api/v9/quests/{quest_id}/heartbeat", json={"application_id": app_id, "terminal": False}, headers=headers) as res:
                        if res.status in (200, 202):
                            res_data = await res.json()
                            last_hb = now_ts
                            progress_data = res_data.get("progress", {}).get(task_type) or {}
                            done = progress_data.get("value", 0)
                            if res_data.get("completed_at") or done >= target:
                                is_completed = True
                                break
                        elif res.status == 429:
                            r_data = await res.json()
                            await asyncio.sleep(r_data.get("retry_after", 5))
                            continue
                        else:
                            await asyncio.sleep(15)
                            continue
                except Exception:
                    await asyncio.sleep(15)
                    continue
            await asyncio.sleep(1)

        if is_completed:
            try:
                await session.post(f"https://discord.com/api/v9/quests/{quest_id}/heartbeat", json={"application_id": app_id, "terminal": True}, headers=headers)
            except Exception:
                pass
            await trigger_webhook(client, user_id_str, quest_name)

async def run_auto_quest_background(client, token, user_id_str, expires_at_dt):
    headers = {
        "Authorization": token,
        "accept-language": "vi,en-US;q=0.9",
        "origin": "https://discord.com",
        "referer": "https://discord.com/channels/@me",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9215 Chrome/138.0.7204.251 Electron/37.6.0 Safari/537.36",
        "x-super-properties": get_super_properties()
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        if not await check_token_is_valid(session, token):
            return

    while True:
        now = datetime.now(timezone.utc)
        if now >= expires_at_dt:
            break

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                if not await check_token_is_valid(session, token):
                    break

                async with session.get("https://discord.com/api/v9/quests/@me") as response:
                    if response.status == 200:
                        data = await response.json()
                        all_quests = (data.get("quests", []) or []) + (data.get("excluded_quests", []) or [])
                        valid_quests = []
                        for q in all_quests:
                            ust = q.get("user_status") or {}
                            if ust.get("claimed_at") is not None or ust.get("completed_at") is not None:
                                continue
                            if not ust.get("enrolled_at"):
                                q_id = q.get("id")
                                try:
                                    await asyncio.sleep(1)
                                    async with session.post(f"https://discord.com/api/v9/quests/{q_id}/enroll", json={"location": 11, "is_targeted": False, "metadata_raw": None}, headers=headers) as en_res:
                                        if en_res.status == 200:
                                            en_data = await en_res.json()
                                            q["user_status"] = en_data.get("user_status", {}) or {}
                                        else:
                                            continue
                                except Exception:
                                    continue
                            valid_quests.append(q)

                        if valid_quests:
                            tasks = [asyncio.create_task(process_single_quest(client, session, q, headers, user_id_str)) for q in valid_quests]
                            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass

        await asyncio.sleep(300)

class MultiAccountBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.running_tasks = {}

    async def setup_hook(self):
        await self.tree.sync()
        print("[✓] Đã đồng bộ xong Slash Commands.")

bot = MultiAccountBot()

# --- WEB PANEL VỚI GIAO DIỆN LOGIN RIÊNG ---
app = FastAPI(title="Auto Quest - Neon Cyber Admin")

def verify_session(session_token: str = Cookie(None)):
    if not session_token or session_token not in ACTIVE_SESSIONS:
        raise HTTPException(status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": "/login"})
    return True

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>Đăng Nhập - Cyber Admin Panel</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Rajdhani:wght@500;700&display=swap" rel="stylesheet">
    <style>
        body {{
            background-color: #05050a;
            color: #e0e0e0;
            font-family: 'Rajdhani', sans-serif;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            position: relative;
        }}
        body::before {{
            content: " ";
            display: block;
            position: absolute;
            top: 0; left: 0; bottom: 0; right: 0;
            background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.06), rgba(0, 255, 0, 0.02), rgba(0, 0, 255, 0.06));
            z-index: -1;
            background-size: 100% 4px, 6px 100%;
            pointer-events: none;
        }}
        .font-orbitron {{ font-family: 'Orbitron', sans-serif; letter-spacing: 1px; }}
        .neon-title {{ color: #00f3ff; text-shadow: 0 0 10px rgba(0, 243, 255, 0.6), 0 0 20px rgba(0, 243, 255, 0.3); }}
        .glass-card {{
            background: rgba(15, 15, 25, 0.85);
            backdrop-filter: blur(15px);
            border: 1px solid rgba(0, 243, 255, 0.3);
            border-radius: 16px;
            box-shadow: 0 0 25px rgba(0, 0, 0, 0.8), 0 0 15px rgba(0, 243, 255, 0.15);
            width: 100%;
            max-width: 420px;
            padding: 40px;
        }}
        .form-control {{
            background: rgba(10, 10, 18, 0.9);
            border: 1px solid rgba(0, 243, 255, 0.3);
            color: #fff;
            border-radius: 8px;
            padding: 12px;
            transition: all 0.3s;
        }}
        .form-control:focus {{
            background: rgba(15, 15, 25, 1);
            color: #fff;
            border-color: #00f3ff;
            box-shadow: 0 0 15px rgba(0, 243, 255, 0.4);
        }}
        .btn-neon {{
            background: transparent;
            color: #00f3ff;
            border: 1px solid #00f3ff;
            border-radius: 8px;
            font-family: 'Orbitron', sans-serif;
            font-weight: bold;
            padding: 12px;
            width: 100%;
            transition: all 0.3s ease;
            box-shadow: 0 0 10px rgba(0, 243, 255, 0.2);
        }}
        .btn-neon:hover {{
            background: #00f3ff;
            color: #05050a;
            box-shadow: 0 0 25px rgba(0, 243, 255, 0.8);
            transform: scale(1.02);
        }}
        .error-msg {{
            color: #ff0055;
            font-size: 0.9rem;
            text-align: center;
            margin-top: 15px;
            text-shadow: 0 0 8px rgba(255, 0, 85, 0.4);
        }}
    </style>
</head>
<body>
    <div class="glass-card">
        <h3 class="text-center fw-bold neon-title mb-4 font-orbitron" style="font-size: 1.4rem;">CYBER ADMIN PANEL</h3>
        <form action="/login" method="post">
            <div class="mb-3">
                <label class="form-label text-muted font-orbitron" style="font-size: 0.75rem;">TÀI KHOẢN QUẢN TRỊ</label>
                <input type="text" name="username" class="form-control" placeholder="Nhập username" required autocomplete="off">
            </div>
            <div class="mb-4">
                <label class="form-label text-muted font-orbitron" style="font-size: 0.75rem;">MẬT KHẨU BẢO MẬT</label>
                <input type="password" name="password" class="form-control" placeholder="Nhập password" required>
            </div>
            <button type="submit" class="btn btn-neon">TRUY CẬP HỆ THỐNG</button>
            {error_block}
        </form>
    </div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>Auto Quest - Neon Cyber Admin</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Rajdhani:wght@500;700&display=swap" rel="stylesheet">
    <style>
        body {{
            background-color: #05050a;
            color: #e0e0e0;
            font-family: 'Rajdhani', sans-serif;
            overflow-x: hidden;
            position: relative;
        }}
        body::before {{
            content: " ";
            display: block;
            position: absolute;
            top: 0; left: 0; bottom: 0; right: 0;
            background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.06), rgba(0, 255, 0, 0.02), rgba(0, 0, 255, 0.06));
            z-index: -1;
            background-size: 100% 4px, 6px 100%;
            pointer-events: none;
        }}
        h1, h2, h3, h4, .font-orbitron {{ font-family: 'Orbitron', sans-serif; letter-spacing: 1px; }}
        .neon-title {{ color: #00f3ff; text-shadow: 0 0 10px rgba(0, 243, 255, 0.6), 0 0 20px rgba(0, 243, 255, 0.3); }}
        .glass-card {{
            background: rgba(15, 15, 25, 0.7);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(0, 243, 255, 0.2);
            border-radius: 12px;
            box-shadow: 0 0 15px rgba(0, 0, 0, 0.5);
            transition: all 0.3s ease;
        }}
        .glass-card:hover {{
            border-color: rgba(0, 243, 255, 0.6);
            box-shadow: 0 0 25px rgba(0, 243, 255, 0.2);
            transform: translateY(-2px);
        }}
        .stat-num-blue {{ color: #00f3ff; text-shadow: 0 0 8px rgba(0, 243, 255, 0.5); }}
        .stat-num-green {{ color: #0ff0fc; text-shadow: 0 0 8px rgba(15, 240, 252, 0.5); }}
        .stat-num-pink {{ color: #ff0055; text-shadow: 0 0 8px rgba(255, 0, 85, 0.5); }}
        .form-control {{
            background: rgba(10, 10, 18, 0.8);
            border: 1px solid rgba(0, 243, 255, 0.3);
            color: #fff;
            border-radius: 8px;
            transition: all 0.3s;
        }}
        .form-control:focus {{
            background: rgba(15, 15, 25, 0.9);
            color: #fff;
            border-color: #00f3ff;
            box-shadow: 0 0 10px rgba(0, 243, 255, 0.4);
        }}
        .btn-neon {{
            background: transparent;
            color: #00f3ff;
            border: 1px solid #00f3ff;
            border-radius: 8px;
            font-family: 'Orbitron', sans-serif;
            font-weight: bold;
            transition: all 0.3s ease;
            box-shadow: 0 0 10px rgba(0, 243, 255, 0.2);
        }}
        .btn-neon:hover {{
            background: #00f3ff;
            color: #05050a;
            box-shadow: 0 0 20px rgba(0, 243, 255, 0.8);
            transform: scale(1.02);
        }}
        .btn-danger-neon {{
            background: transparent;
            color: #ff0055;
            border: 1px solid #ff0055;
            border-radius: 6px;
            transition: all 0.3s ease;
            box-shadow: 0 0 8px rgba(255, 0, 85, 0.2);
        }}
        .btn-danger-neon:hover {{
            background: #ff0055;
            color: #fff;
            box-shadow: 0 0 15px rgba(255, 0, 85, 0.8);
        }}
        .nav-tabs {{ border-bottom: 1px solid rgba(0, 243, 255, 0.2); margin-bottom: 25px; }}
        .nav-tabs .nav-link {{
            background: rgba(15, 15, 25, 0.5);
            color: #a0a0b0;
            border: 1px solid rgba(0, 243, 255, 0.1);
            border-bottom: none;
            font-family: 'Orbitron', sans-serif;
            font-size: 0.9rem;
            margin-right: 5px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            transition: all 0.3s ease;
        }}
        .nav-tabs .nav-link:hover {{ color: #00f3ff; border-color: rgba(0, 243, 255, 0.4); }}
        .nav-tabs .nav-link.active {{
            background: rgba(15, 15, 25, 0.9);
            color: #00f3ff;
            border-color: #00f3ff #00f3ff transparent #00f3ff;
            text-shadow: 0 0 8px rgba(0, 243, 255, 0.4);
        }}
        .table {{ color: #d0d0d0; background: transparent; }}
        .table > :not(caption) > * > * {{
            background-color: transparent;
            color: #e0e0e0;
            border-bottom-color: rgba(255, 255, 255, 0.05);
        }}
        .table-hover tbody tr:hover {{ background-color: rgba(0, 243, 255, 0.05); }}
        code {{ color: #ffcc00; background: rgba(255, 204, 0, 0.1); padding: 2px 6px; border-radius: 4px; }}
        .scrollable-table {{ max-height: 450px; overflow-y: auto; }}
    </style>
</head>
<body>
    <div class="container py-5">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h2 class="fw-bold neon-title mb-0">⚡ CYBER ADMIN PANEL ⚡</h2>
            <a href="/logout" class="btn btn-danger-neon px-3 py-1 font-orbitron" style="font-size: 0.8rem;">ĐĂNG XUẤT</a>
        </div>
        
        <div class="row text-center mb-4 g-4">
            <div class="col-md-4">
                <div class="glass-card p-4">
                    <p class="text-uppercase text-muted mb-1 font-orbitron" style="font-size: 0.8rem;">Tổng số Key</p>
                    <h2 class="stat-num-blue fw-bold mb-0">{total_keys}</h2>
                </div>
            </div>
            <div class="col-md-4">
                <div class="glass-card p-4">
                    <p class="text-uppercase text-muted mb-1 font-orbitron" style="font-size: 0.8rem;">Key đã sử dụng</p>
                    <h2 class="stat-num-green fw-bold mb-0">{used_keys}</h2>
                </div>
            </div>
            <div class="col-md-4">
                <div class="glass-card p-4">
                    <p class="text-uppercase text-muted mb-1 font-orbitron" style="font-size: 0.8rem;">Tài khoản đang treo</p>
                    <h2 class="stat-num-pink fw-bold mb-0">{active_accounts}</h2>
                </div>
            </div>
        </div>

        <ul class="nav nav-tabs" id="adminTab" role="tablist">
            <li class="nav-item" role="presentation">
                <button class="nav-link active" id="keys-tab" data-bs-toggle="tab" data-bs-target="#keys-content" type="button" role="tab">🔑 Quản Lý Key Bản Quyền</button>
            </li>
            <li class="nav-item" role="presentation">
                <button class="nav-link" id="accounts-tab" data-bs-toggle="tab" data-bs-target="#accounts-content" type="button" role="tab">⚡ Tài Khoản Đang Treo Ngầm</button>
            </li>
        </ul>

        <div class="tab-content" id="adminTabContent">
            <div class="tab-pane fade show active" id="keys-content" role="tabpanel">
                <div class="glass-card p-4 mb-4">
                    <h4 class="mb-3 font-orbitron text-white" style="font-size: 1.1rem;">Khởi Tạo Key Mới</h4>
                    <form action="/create-key" method="post" class="row g-3 align-items-center">
                        <div class="col-auto flex-grow-1">
                            <input type="text" name="duration" class="form-control" placeholder="Nhập thời gian (VD: 2h, 7d, 1m)" required>
                        </div>
                        <div class="col-auto">
                            <button type="submit" class="btn btn-neon px-4 py-2">TẠO KEY</button>
                        </div>
                    </form>
                </div>

                <div class="glass-card p-4">
                    <h4 class="mb-3 font-orbitron text-white" style="font-size: 1.1rem;">Danh Sách Toàn Bộ Key ({total_keys})</h4>
                    <div class="table-responsive scrollable-table">
                        <table class="table align-middle mb-0">
                            <thead>
                                <tr class="font-orbitron" style="font-size: 0.85rem; color: #00f3ff; position: sticky; top: 0; background: #0f0f19; z-index: 1;">
                                    <th>MÃ KEY</th>
                                    <th>TRẠNG THÁI</th>
                                    <th>DISCORD USER ID</th>
                                    <th>THỜI HẠN</th>
                                    <th>THAO TÁC</th>
                                </tr>
                            </thead>
                            <tbody>
                                {key_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <div class="tab-pane fade" id="accounts-content" role="tabpanel">
                <div class="glass-card p-4">
                    <h4 class="mb-3 font-orbitron text-white" style="font-size: 1.1rem;">Danh Sách Tài Khoản Đang Hoạt Động ({active_accounts})</h4>
                    <div class="table-responsive scrollable-table">
                        <table class="table align-middle mb-0">
                            <thead>
                                <tr class="font-orbitron" style="font-size: 0.85rem; color: #ff0055; position: sticky; top: 0; background: #0f0f19; z-index: 1;">
                                    <th>DISCORD USER ID</th>
                                    <th>KEY SỬ DỤNG</th>
                                    <th>THỜI GIAN HẾT HẠN</th>
                                    <th>THAO TÁC</th>
                                </tr>
                            </thead>
                            <tbody>
                                {account_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

@app.get("/login", response_class=HTMLResponse)
async def login_page(error: str = None):
    err_html = f'<div class="error-msg">⚠️ Sai tài khoản hoặc mật khẩu!</div>' if error else ''
    return LOGIN_HTML.format(error_block=err_html)

@app.post("/login")
async def login_submit(username: str = Form(...), password: str = Form(...)):
    is_user_ok = secrets.compare_digest(username.encode("utf8"), WEB_USER.encode("utf8"))
    is_pass_ok = secrets.compare_digest(password.encode("utf8"), WEB_PASS.encode("utf8"))
    
    if not (is_user_ok and is_pass_ok):
        return RedirectResponse(url="/login?error=1", status_code=303)
    
    token = secrets.token_hex(32)
    ACTIVE_SESSIONS.add(token)
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="session_token", value=token, httponly=True, max_age=86400)
    return response

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session_token")
    return response

@app.get("/", response_class=HTMLResponse)
async def admin_dashboard(auth: bool = Depends(verify_session)):
    keys_data = load_json(KEY_FILE, {})
    accounts_data = load_json(ACCOUNTS_FILE, {})
    
    total_keys = len(keys_data)
    used_keys = sum(1 for k in keys_data.values() if k.get("used"))
    active_accounts = len(accounts_data)
    
    account_rows = ""
    for token, info in accounts_data.items():
        uid = info.get("user_id", "Không rõ")
        used_key = info.get("key", "Không rõ")
        exp_str = info.get("expires_at", "Không rõ")
        
        account_rows += f"""
            <tr>
                <td><code>{uid}</code></td>
                <td><code>{used_key}</code></td>
                <td>{exp_str}</td>
                <td>
                    <form action="/stop-account" method="post" style="display:inline;">
                        <input type="hidden" name="token" value="{token}">
                        <button type="submit" class="btn btn-danger-neon btn-sm px-3">Ngắt treo</button>
                    </form>
                </td>
            </tr>
        """
    if not account_rows:
        account_rows = "<tr><td colspan='4' class='text-center text-muted py-4'>Chưa có tài khoản nào đang chạy ngầm</td></tr>"

    key_rows = ""
    for k, info in keys_data.items():
        status = "<span class='badge bg-success'>Đã dùng</span>" if info.get("used") else "<span class='badge bg-secondary'>Chưa dùng</span>"
        user_id = info.get("user_id") or "Chưa có"
        duration_sec = info.get("duration_seconds", 0)
        
        if duration_sec >= 86400:
            dur_str = f"{int(duration_sec / 86400)} Ngày"
        elif duration_sec >= 3600:
            dur_str = f"{int(duration_sec / 3600)} Giờ"
        else:
            dur_str = f"{int(duration_sec / 60)} Phút"

        key_rows += f"""
            <tr>
                <td><code>{k}</code></td>
                <td>{status}</td>
                <td>{user_id}</td>
                <td>{dur_str}</td>
                <td>
                    <form action="/delete-key" method="post" style="display:inline;">
                        <input type="hidden" name="key_code" value="{k}">
                        <button type="submit" class="btn btn-danger-neon btn-sm px-3">Xóa</button>
                    </form>
                </td>
            </tr>
        """
    if not key_rows:
        key_rows = "<tr><td colspan='5' class='text-center text-muted py-4'>Chưa có key nào được tạo trong hệ thống</td></tr>"
        
    return DASHBOARD_HTML.format(
        total_keys=total_keys,
        used_keys=used_keys,
        active_accounts=active_accounts,
        account_rows=account_rows,
        key_rows=key_rows
    )

@app.post("/create-key")
async def web_create_key(duration: str = Form(...), auth: bool = Depends(verify_session)):
    seconds = parse_duration(duration)
    if seconds > 0:
        new_key = f"DAWNGGX-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
        keys_data = load_json(KEY_FILE, {})
        keys_data[new_key] = {"used": False, "user_id": None, "duration_seconds": seconds, "expires_at": None}
        save_json(KEY_FILE, keys_data)
    return RedirectResponse(url="/", status_code=303)

@app.post("/delete-key")
async def web_delete_key(key_code: str = Form(...), auth: bool = Depends(verify_session)):
    keys_data = load_json(KEY_FILE, {})
    if key_code in keys_data:
        del keys_data[key_code]
        save_json(KEY_FILE, keys_data)
    return RedirectResponse(url="/", status_code=303)

@app.post("/stop-account")
async def web_stop_account(token: str = Form(...), auth: bool = Depends(verify_session)):
    accounts_data = load_json(ACCOUNTS_FILE, {})
    if token in accounts_data:
        del accounts_data[token]
        save_json(ACCOUNTS_FILE, accounts_data)
    
    if token in bot.running_tasks:
        bot.running_tasks[token].cancel()
        del bot.running_tasks[token]
        
    return RedirectResponse(url="/", status_code=303)

def run_web_server():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

# --- BOT EVENTS & COMMANDS ---
class ActiveModal(discord.ui.Modal, title="Kích Hoạt Auto Quest Đa Tài Khoản"):
    key_input = discord.ui.TextInput(label="Mã Key Bản Quyền", placeholder="Nhập key do Admin cung cấp", required=True, style=discord.TextStyle.short)
    token_input = discord.ui.TextInput(label="Discord User Token", placeholder="Nhập token tài khoản của bạn", required=True, style=discord.TextStyle.long)

    async def on_submit(self, interaction: discord.Interaction):
        loading_embed = discord.Embed(
            title="🔄 Đang Kết Nối Hệ Thống...",
            description="Hệ thống đang xác thực mã key và kiểm tra kết nối tài khoản Discord của bạn, vui lòng đợi trong giây lát...",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=loading_embed, ephemeral=True)

        entered_key = self.key_input.value.strip()
        user_token = self.token_input.value.strip()
        keys_data = load_json(KEY_FILE, {})

        if entered_key not in keys_data:
            err_embed = discord.Embed(title="❌ Lỗi Kích Hoạt", description="Mã key không tồn tại trong hệ thống!", color=discord.Color.red())
            await interaction.edit_original_response(embed=err_embed)
            return

        key_info = keys_data[entered_key]
        now = datetime.now(timezone.utc)

        if key_info.get("used", False) and key_info.get("user_id") != str(interaction.user.id):
            err_embed = discord.Embed(title="❌ Lỗi Kích Hoạt", description="Key này đã được dùng bởi người khác!", color=discord.Color.red())
            await interaction.edit_original_response(embed=err_embed)
            return

        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": user_token}
            async with session.get("https://discord.com/api/v9/users/@me", headers=headers) as res:
                if res.status != 200:
                    err_embed = discord.Embed(title="❌ Token Không Hợp Lệ", description="Token Discord bạn vừa nhập không thể truy cập được. Vui lòng kiểm tra lại!", color=discord.Color.red())
                    await interaction.edit_original_response(embed=err_embed)
                    return
                user_data = await res.json()
                original_discord_id = str(user_data.get("id"))

        expires_at_dt = now + timedelta(seconds=key_info.get("duration_seconds", 86400))

        key_info["used"] = True
        key_info["user_id"] = str(interaction.user.id)
        key_info["expires_at"] = expires_at_dt.isoformat()
        save_json(KEY_FILE, keys_data)

        accounts_data = load_json(ACCOUNTS_FILE, {})
        accounts_data[user_token] = {
            "user_id": str(interaction.user.id),
            "original_discord_id": original_discord_id,
            "expires_at": expires_at_dt.isoformat(),
            "key": entered_key
        }
        save_json(ACCOUNTS_FILE, accounts_data)

        success_embed = discord.Embed(
            title="🎉 Kích Hoạt Thành Công!",
            description="Hệ thống đã tiếp nhận tài khoản và bắt đầu quy trình treo ngầm tự động.",
            color=discord.Color.brand_green()
        )
        success_embed.add_field(name="📦 Mã Key Sử Dụng", value=f"`{entered_key}`", inline=True)
        success_embed.add_field(name="⏳ Thời Gian Hết Hạn", value=f"<t:{int(expires_at_dt.timestamp())}:R>", inline=True)
        success_embed.set_footer(text="Bot đang chạy ngầm 24/7 • Bạn có thể tắt ứng dụng Discord")
        
        await interaction.edit_original_response(embed=success_embed)

        if user_token in bot.running_tasks:
            bot.running_tasks[user_token].cancel()

        bot.running_tasks[user_token] = asyncio.create_task(
            run_auto_quest_background(bot, user_token, str(interaction.user.id), expires_at_dt)
        )

class UpdateTokenModal(discord.ui.Modal, title="Cập Nhật Lại Token Mới"):
    token_input = discord.ui.TextInput(
        label="Discord User Token Mới",
        placeholder="Dán token mới của bạn vào đây",
        required=True,
        style=discord.TextStyle.long
    )

    async def on_submit(self, interaction: discord.Interaction):
        loading_embed = discord.Embed(
            title="🔄 Đang Xác Thực Token...",
            description="Hệ thống đang kiểm tra chữ ký token mới và đối chiếu bảo mật tài khoản...",
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=loading_embed, ephemeral=True)

        new_token = self.token_input.value.strip()
        user_id_str = str(interaction.user.id)
        
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": new_token}
            async with session.get("https://discord.com/api/v9/users/@me", headers=headers) as res:
                if res.status != 200:
                    err_embed = discord.Embed(title="❌ Cập Nhật Thất Bại", description="Token mới không hợp lệ hoặc đã chết. Vui lòng kiểm tra lại!", color=discord.Color.red())
                    await interaction.edit_original_response(embed=err_embed)
                    return
                user_data = await res.json()
                new_discord_id = str(user_data.get("id"))

        accounts_data = load_json(ACCOUNTS_FILE, {})
        
        old_token_found = None
        acc_info = None
        for tkn, info in accounts_data.items():
            if info.get("user_id") == user_id_str:
                old_token_found = tkn
                acc_info = info
                break
        
        if not acc_info:
            err_embed = discord.Embed(title="❌ Lỗi", description="Bạn chưa từng kích hoạt gói auto quest nào trên hệ thống!", color=discord.Color.red())
            await interaction.edit_original_response(embed=err_embed)
            return

        original_discord_id = acc_info.get("original_discord_id", new_discord_id)
        if acc_info.get("original_discord_id") and new_discord_id != original_discord_id:
            err_embed = discord.Embed(title="🛡️ Cảnh Báo Bảo Mật", description="Bạn chỉ được phép cập nhật token cho **đúng tài khoản Discord** đã kích hoạt ban đầu!", color=discord.Color.red())
            await interaction.edit_original_response(embed=err_embed)
            return

        if "original_discord_id" not in acc_info:
            acc_info["original_discord_id"] = new_discord_id

        if old_token_found and old_token_found in accounts_data:
            del accounts_data[old_token_found]
            
        accounts_data[new_token] = acc_info
        save_json(ACCOUNTS_FILE, accounts_data)

        success_embed = discord.Embed(
            title="✅ Cập Nhật Token Thành Công!",
            description="Tài khoản của bạn đã được làm mới kết nối và tiếp tục chạy tiến trình cày quest.",
            color=discord.Color.brand_green()
        )
        await interaction.edit_original_response(embed=success_embed)

        if old_token_found and old_token_found in bot.running_tasks:
            bot.running_tasks[old_token_found].cancel()
            del bot.running_tasks[old_token_found]

        expires_at_dt = datetime.fromisoformat(acc_info["expires_at"])
        bot.running_tasks[new_token] = asyncio.create_task(
            run_auto_quest_background(bot, new_token, user_id_str, expires_at_dt)
        )

@bot.event
async def on_ready():
    print(f"[✓] Bot đã đăng nhập: {bot.user}")
    accounts_data = load_json(ACCOUNTS_FILE, {})
    now = datetime.now(timezone.utc)
    count = 0
    for token, acc_info in accounts_data.items():
        try:
            exp = datetime.fromisoformat(acc_info["expires_at"])
            if now < exp:
                bot.running_tasks[token] = asyncio.create_task(
                    run_auto_quest_background(bot, token, acc_info["user_id"], exp)
                )
                count += 1
        except Exception:
            continue
    print(f"[✓] Đã khôi phục thành công {count} tài khoản treo ngầm.")

@bot.tree.command(name="genkey", description="Tạo key nhanh (Ví dụ: 30p, 2h, 7d, 1m)")
@app_commands.describe(duration="Thời gian sử dụng")
async def genkey(interaction: discord.Interaction, duration: str):
    if str(interaction.user.id) not in ADMIN_IDS:
        await interaction.response.send_message("❌ Bạn không có quyền!", ephemeral=True)
        return

    seconds = parse_duration(duration)
    if seconds <= 0:
        await interaction.response.send_message("❌ Sai định dạng thời gian! (VD: 2h, 7d)", ephemeral=True)
        return

    new_key = f"DAWNGGX-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
    keys_data = load_json(KEY_FILE, {})
    keys_data[new_key] = {"used": False, "user_id": None, "duration_seconds": seconds, "expires_at": None}
    save_json(KEY_FILE, keys_data)

    embed = discord.Embed(title="🔑 Tạo Key Thành Công", color=discord.Color.blue())
    embed.add_field(name="Mã Key:", value=f"`{new_key}`", inline=False)
    embed.add_field(name="Thời hạn:", value=f"`{duration}`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="active", description="Kích hoạt Auto Quest bằng Key và Token")
async def active(interaction: discord.Interaction):
    await interaction.response.send_modal(ActiveModal())

@bot.tree.command(name="updatetoken", description="Cập nhật lại token mới khi token cũ bị lỗi/hết hạn")
async def updatetoken(interaction: discord.Interaction):
    await interaction.response.send_modal(UpdateTokenModal())

if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN or DISCORD_BOT_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("[!] LỖI: Vui lòng mở file config.json điền Token Bot của bạn vào!")
    else:
        web_thread = threading.Thread(target=run_web_server, daemon=True)
        web_thread.start()
        print("[✓] Web Admin Panel (Neon Cyber) đã khởi chạy tại: http://localhost:8000")
        
        bot.run(DISCORD_BOT_TOKEN)