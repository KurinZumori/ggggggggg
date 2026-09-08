import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import base64
import json
import uuid
import random
import aiohttp
import discord
from datetime import datetime, timezone
from logger.logging import print_log, Colors
from logger.connector import log_quest

def get_super_properties():
    client_props = {
        "os": "Windows",
        "browser": "Discord Client",
        "release_channel": "stable",
        "client_version": "1.0.9215",
        "os_version": "10.0.19045",
        "os_arch": "x64",
        "app_arch": "x64",
        "system_locale": "en-US",
        "has_client_mods": False,
        "client_launch_id": str(uuid.uuid4()),
        "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9215 Chrome/138.0.7204.251 Electron/37.6.0 Safari/537.36",
        "browser_version": "37.6.0",
        "os_sdk_version": "19045",
        "client_build_number": 471091,
        "native_build_number": 72186,
        "client_event_source": None,
        "launch_signature": str(uuid.uuid4()),
        "client_heartbeat_session_id": str(uuid.uuid4()),
        "client_app_state": "focused"
    }
    json_str = json.dumps(client_props, separators=(',', ':'))
    return base64.b64encode(json_str.encode('utf-8')).decode('utf-8')

def get_orbs(quest_raw):
    try:
        config = quest_raw.get("config", {})
        rewards_config = config.get("rewards_config", {})
        rewards = rewards_config.get("rewards", [])
        if isinstance(rewards, list):
            for r in rewards:
                if r.get("type") == 4:
                    return r.get("quantity", 0)
                sku_id = str(r.get("sku_id", "")).lower()
                if "orb" in sku_id:
                    return r.get("quantity", 0)
        if rewards_config.get("orb_quantity") is not None:
            return rewards_config.get("orb_quantity")
        if rewards_config.get("quantity") is not None and rewards_config.get("type") == 4:
            return rewards_config.get("quantity")
            
        def search_dict(d):
            if not isinstance(d, dict):
                return None
            if d.get("type") == 4 and "quantity" in d:
                return d.get("quantity")
            for k, v in d.items():
                if "orb_quantity" in k.lower() and isinstance(v, (int, float)):
                    return v
                if isinstance(v, dict):
                    res = search_dict(v)
                    if res is not None:
                        return res
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            res = search_dict(item)
                            if res is not None:
                                return res
            return None
        res = search_dict(quest_raw)
        if res is not None:
            return res
    except Exception:
        pass
    return 700

async def trigger_webhook(bot, quest_raw, quest_name, task_type=None):
    # Gửi DM thông báo hoàn thành Quest dạng Embed cực đẹp
    if hasattr(bot, "discord_bot_client") and hasattr(bot, "target_user_id"):
        try:
            discord_client = bot.discord_bot_client
            user_id = int(bot.target_user_id)
            user = discord_client.get_user(user_id) or await discord_client.fetch_user(user_id)
            if user:
                orbs = get_orbs(quest_raw)
                embed = discord.Embed(
                    title="🎉 Hoàn Thành Quest Thành Công!",
                    description="Hệ thống đã tự động hoàn thành nhiệm vụ Discord cho bạn.",
                    color=discord.Color.purple()
                )
                embed.add_field(name="🔹 Tên Quest", value=f"`{quest_name}`", inline=False)
                embed.add_field(name="🎁 Phần Thưởng", value=f"**{orbs}** orbs", inline=True)
                embed.set_footer(text="Auto Quest System • Hoàn thành tự động")
                await user.send(embed=embed)
        except Exception as e:
            print(f"[!] Không thể gửi DM cho người dùng: {e}")

    webhook_cfg = bot.config.get("webhook_logging", {})
    if webhook_cfg.get("enabled", False) and webhook_cfg.get("webhook_url"):
        if not task_type:
            config = quest_raw.get("config", {})
            task_config_v2 = config.get("task_config_v2", {})
            task_config = config.get("task_config", {})
            tasks = task_config_v2.get("tasks") or task_config.get("tasks") or {}
            for t in ["PLAY_ON_DESKTOP", "WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE", "STREAM_ON_DESKTOP", "PLAY_ACTIVITY", "PLAY_ON_XBOX", "PLAY_ON_PLAYSTATION"]:
                if t in tasks:
                    task_type = t
                    break
        orbs = get_orbs(quest_raw)
        asyncio.create_task(log_quest(webhook_cfg["webhook_url"], quest_name, task_type or "N/A", orbs))

async def process_single_quest(bot, session, quest_raw, quest_cfg, headers, quest_idx=None, num_quests=None):
    logging_enabled = quest_cfg.get("logging", True)
    quest_id = quest_raw.get("id")
    config = quest_raw.get("config", {})
    user_status = quest_raw.get("user_status") or {}
    quest_name = config.get("messages", {}).get("quest_name", "").strip() or quest_id

    def update_status(text, color=None):
        if not logging_enabled:
            return
        ansi_color = "\033[36m"
        if color == Colors.red_to_yellow:
            ansi_color = "\033[33m"
        elif color == Colors.green_to_cyan:
            ansi_color = "\033[36m"

        if quest_idx is not None and num_quests is not None:
            lines_up = num_quests - quest_idx
            colored_text = f"{ansi_color}{text}\033[0m"
            sys.stdout.write(f"\033[{lines_up}A\r\033[K{colored_text}\033[{lines_up}B")
            sys.stdout.flush()
        else:
            print_log(f"\r{text}\n".ljust(80), color, interval=0)

    completed_at = user_status.get("completed_at")
    claimed_at = user_status.get("claimed_at")

    if completed_at and claimed_at:
        return

    if completed_at:
        update_status(f"[✓] {quest_name} | Quest completed", Colors.green_to_cyan)
        await trigger_webhook(bot, quest_raw, quest_name)
        return

    task_config_v2 = config.get("task_config_v2", {})
    task_config = config.get("task_config", {})
    tasks = task_config_v2.get("tasks") or task_config.get("tasks") or {}

    task_type = None
    for t in ["PLAY_ON_DESKTOP", "WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE", "STREAM_ON_DESKTOP", "PLAY_ACTIVITY", "PLAY_ON_XBOX", "PLAY_ON_PLAYSTATION"]:
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
        update_status(f"[✓] {quest_name} | Quest completed", Colors.green_to_cyan)
        await trigger_webhook(bot, quest_raw, quest_name, task_type)
        return

    if task_type in ("WATCH_VIDEO", "WATCH_VIDEO_ON_MOBILE"):
        enrolled_at_str = user_status.get("enrolled_at")
        enrolled_at = datetime.fromisoformat(enrolled_at_str.replace("Z", "+00:00")).timestamp() if enrolled_at_str else datetime.now(timezone.utc).timestamp()
        
        consecutive_failures = 0
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
                            percent = int(100 * done / target)
                            bar = "█" * int(20 * done / target) + "░" * (20 - int(20 * done / target))
                            update_status(f"[</>] {quest_name} | {percent}% | {bar}", Colors.green_to_cyan)
                            consecutive_failures = 0
                            if res_data.get("completed_at"):
                                break
                        elif res.status == 429:
                            res_data = await res.json()
                            retry_after = res_data.get("retry_after", 5)
                            update_status(f"[!] {quest_name} | Rate limited. Retrying in {retry_after}s...", Colors.red_to_yellow)
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            consecutive_failures += 1
                            if consecutive_failures >= 5:
                                break
                            await asyncio.sleep(15)
                            continue
                except Exception:
                    consecutive_failures += 1
                    if consecutive_failures >= 5:
                        break
                    await asyncio.sleep(15)
                    continue
            
            if next_val >= target:
                break
            await asyncio.sleep(1)

        update_status(f"[✓] {quest_name} | Quest completed", Colors.green_to_cyan)
        await trigger_webhook(bot, quest_raw, quest_name, task_type)

    else:
        apps = task_data.get("applications") or []
        app_id = apps[0].get("id") if apps else config.get("application", {}).get("id")
        if not app_id:
            return

        last_heartbeat_time = 0
        is_completed = False
        consecutive_failures = 0
        
        while not is_completed:
            now_ts = datetime.now(timezone.utc).timestamp()
            if now_ts - last_heartbeat_time >= 60:
                try:
                    async with session.post(f"https://discord.com/api/v9/quests/{quest_id}/heartbeat", json={"application_id": app_id, "terminal": False}, headers=headers) as res:
                        if res.status in (200, 202):
                            res_data = await res.json()
                            user_status = res_data
                            last_heartbeat_time = now_ts
                            consecutive_failures = 0
                            
                            progress_data = user_status.get("progress", {}).get(task_type) or {}
                            done = progress_data.get("value", 0)
                            percent = int(100 * done / target)
                            bar = "█" * int(20 * done / target) + "░" * (20 - int(20 * done / target))
                            update_status(f"[</>] {quest_name} | {percent}% | {bar}", Colors.green_to_cyan)
                            
                            if user_status.get("completed_at") or done >= target:
                                is_completed = True
                                break
                        elif res.status == 429:
                            res_data = await res.json()
                            retry_after = res_data.get("retry_after", 5)
                            await asyncio.sleep(retry_after)
                            continue
                        else:
                            consecutive_failures += 1
                            if consecutive_failures >= 5:
                                break
                            await asyncio.sleep(15)
                            continue
                except Exception:
                    consecutive_failures += 1
                    if consecutive_failures >= 5:
                        break
                    await asyncio.sleep(15)
                    continue

            await asyncio.sleep(1)

        if is_completed:
            try:
                await session.post(f"https://discord.com/api/v9/quests/{quest_id}/heartbeat", json={"application_id": app_id, "terminal": True}, headers=headers)
            except Exception:
                pass

            update_status(f"[✓] {quest_name} | Quest completed", Colors.green_to_cyan)
            await trigger_webhook(bot, quest_raw, quest_name, task_type)

async def run_auto_quest(bot):
    quest_cfg = bot.config.get("auto_quest", {})
    if not quest_cfg.get("enabled", False):
        return

    logging_enabled = quest_cfg.get("logging", True)
    token = bot.config.get("token", "")
    if not token:
        return

    check_interval = quest_cfg.get("check_interval", 300)
    expires_at = getattr(bot, "expires_at", None)
    discord_bot_client = getattr(bot, "discord_bot_client", None)
    target_user_id = getattr(bot, "target_user_id", None)

    notified_1day = False
    notified_12h = False

    super_props = get_super_properties()
    headers = {
        "Authorization": token,
        "accept-language": "vi,en-US;q=0.9",
        "origin": "https://discord.com",
        "referer": "https://discord.com/channels/@me",
        "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-debug-options": "bugReporterEnabled",
        "x-discord-locale": "en-US",
        "x-discord-timezone": "Asia/Saigon",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9215 Chrome/138.0.7204.251 Electron/37.6.0 Safari/537.36",
        "x-super-properties": super_props
    }

    first_run = True
    while True:
        now = datetime.now(timezone.utc)

        # Kiểm tra hạn key và gửi cảnh báo dạng Embed
        if expires_at:
            if now >= expires_at:
                if discord_bot_client and target_user_id:
                    try:
                        user = discord_bot_client.get_user(int(target_user_id)) or await discord_bot_client.fetch_user(int(target_user_id))
                        if user:
                            embed_exp = discord.Embed(
                                title="⏳ Thông Báo Hết Hạn Key",
                                description="Key auto quest của bạn đã **hết hạn sử dụng**. Tiến trình auto quest đã dừng lại hoàn toàn.",
                                color=discord.Color.red()
                            )
                            embed_exp.set_footer(text="Vui lòng liên hệ Admin để gia hạn tiếp tục sử dụng!")
                            await user.send(embed=embed_exp)
                    except Exception:
                        pass
                break

            time_left = expires_at - now
            seconds_left = time_left.total_seconds()

            # Cảnh báo còn 1 ngày
            if 0 < seconds_left <= 86400 and not notified_1day:
                notified_1day = True
                if discord_bot_client and target_user_id:
                    try:
                        user = discord_bot_client.get_user(int(target_user_id)) or await discord_bot_client.fetch_user(int(target_user_id))
                        if user:
                            embed_w1 = discord.Embed(
                                title="⚠️ Cảnh Báo Gia Hạn (Còn 1 Ngày)",
                                description="Key auto quest của bạn sẽ **hết hạn sau khoảng 1 ngày nữa**.",
                                color=discord.Color.gold()
                            )
                            embed_w1.set_footer(text="Hãy nhanh chóng gia hạn để không bị gián đoạn tiến trình!")
                            await user.send(embed=embed_w1)
                    except Exception:
                        pass

            # Cảnh báo còn 12 tiếng
            if 0 < seconds_left <= 43200 and not notified_12h:
                notified_12h = True
                if discord_bot_client and target_user_id:
                    try:
                        user = discord_bot_client.get_user(int(target_user_id)) or await discord_bot_client.fetch_user(int(target_user_id))
                        if user:
                            embed_w2 = discord.Embed(
                                title="🚨 Cảnh Báo Gấp (Còn Dưới 12 Giờ)",
                                description="Key auto quest của bạn chỉ còn **dưới 12 tiếng nữa là hết hạn**.",
                                color=discord.Color.dark_orange()
                            )
                            embed_w2.set_footer(text="Vui lòng liên hệ gia hạn ngay lập tức!")
                            await user.send(embed=embed_w2)
                    except Exception:
                        pass

        if logging_enabled and first_run:
            print_log("[</>] Loading Discord Quests...\n", Colors.green_to_cyan, interval=0)

        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                try:
                    async with session.get("https://discord.com/api/v9/quests/@me") as response:
                        if response.status != 200:
                            raise Exception(f"HTTP Status {response.status}")
                        data = await response.json()
                except Exception as e:
                    raise e

                quests = data.get("quests", []) or []
                excluded_quests = data.get("excluded_quests", []) or []
                all_quests = quests + excluded_quests

                if all_quests:
                    valid_quests = []
                    for quest_raw in all_quests:
                        config = quest_raw.get("config", {})
                        user_status = quest_raw.get("user_status") or {}
                        
                        enrolled_at = user_status.get("enrolled_at")
                        claimed_at = user_status.get("claimed_at")

                        if claimed_at is not None or user_status.get("completed_at") is not None:
                            continue

                        expires_at_str = config.get("expires_at")
                        if not expires_at_str:
                            continue
                        try:
                            q_expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                            if now > q_expires_at:
                                continue
                        except Exception:
                            continue

                        if not enrolled_at:
                            quest_id = quest_raw.get("id")
                            try:
                                await asyncio.sleep(1.5)
                                async with session.post(f"https://discord.com/api/v9/quests/{quest_id}/enroll", json={"location": 11, "is_targeted": False, "metadata_raw": None}, headers=headers) as enroll_res:
                                    if enroll_res.status == 200:
                                        enroll_data = await enroll_res.json()
                                        user_status = enroll_data.get("user_status", {}) or {}
                                        quest_raw["user_status"] = user_status
                                    elif enroll_res.status == 429:
                                        break
                                    else:
                                        continue
                            except Exception:
                                continue

                        valid_quests.append(quest_raw)

                    if valid_quests:
                        tasks = []
                        for idx, quest_raw in enumerate(valid_quests):
                            tasks.append(asyncio.create_task(process_single_quest(bot, session, quest_raw, quest_cfg, headers, idx, len(valid_quests))))
                        await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass

        first_run = False
        await asyncio.sleep(check_interval)