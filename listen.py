import asyncio
import datetime
import json
import random
import re
import discord
from dotenv import load_dotenv
import os
import sys
import urllib.error
import urllib.request

load_dotenv()

USER_TOKEN = os.environ.get('DISCORD_USER_TOKEN')


def clean_bot_token(token):
  token = (token or "").strip().strip('"').strip("'")
  if token.lower().startswith("bot "):
    token = token[4:].strip()
  return token


BOT_TOKEN = clean_bot_token(os.environ.get('DISCORD_BOT_TOKEN'))

monitored_groups = {}
forwarding_targets = {}
last_message_ids = {}  # 紀錄各頻道最新處理過的訊息 ID，避免重複發送
STATE_FILE = "listener_state.json"
POLL_MIN_SECONDS = 60
POLL_MAX_SECONDS = 110


def configure_console_encoding():
  for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
      stream.reconfigure(encoding="utf-8", errors="replace")


class BotApiError(Exception):
  def __init__(self, status, message):
    super().__init__(message)
    self.status = status


class DiscordBotApiClient:

  def __init__(self):
    self.token = None

  async def validate(self, token):
    self.token = token.strip()
    response = await self.request("GET", "/users/@me")
    return response.get("username", response.get("id", "未知 Bot"))

  async def send_message(self, channel_id, content, embeds=None):
    payload = {"content": content}
    if embeds:
      payload["embeds"] = embeds
    await self.request("POST", f"/channels/{channel_id}/messages", payload)

  async def request(self, method, path, payload=None):
    if not self.token:
      raise BotApiError(401, "Bot token 尚未設定")

    def do_request():
      request_data = None
      headers = {
          "Authorization": f"Bot {self.token}",
          "User-Agent": "DiscordAnnouncementForwardingBot/1.0",
      }
      if payload is not None:
        request_data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
      request = urllib.request.Request(
          f"https://discord.com/api/v10{path}",
          data=request_data,
          headers=headers,
          method=method,
      )
      try:
        with urllib.request.urlopen(request, timeout=15) as response:
          response_body = response.read().decode("utf-8")
          return json.loads(response_body) if response_body else {}
      except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        try:
          message = json.loads(error_body).get("message", "Discord API 錯誤")
        except json.JSONDecodeError:
          message = "Discord API 錯誤"
        raise BotApiError(error.code, message) from error
      except urllib.error.URLError as error:
        raise BotApiError(0, f"網路連線失敗：{error.reason}") from error

    return await asyncio.to_thread(do_request)

  async def close(self):
    self.token = None


class InteractivePollingSelfBot(discord.Client):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.poll_task = None
    self.listen_control_task = None
    self.forward_bot = DiscordBotApiClient()
    self.forward_bot_task = None
    self.listening_enabled = False
    self.forwarding_enabled = False
    self.load_state()

  def load_state(self):
    try:
      with open(STATE_FILE, "r", encoding="utf-8") as state_file:
        state = json.load(state_file)
      if "groups" in state:
        monitored_groups.update({
            str(group_name): {int(ch_id) for ch_id in channel_ids}
            for group_name, channel_ids in state["groups"].items()
        })
      else:
        old_channels = state.get("channels", [])
        if old_channels:
          monitored_groups["未分類"] = {int(ch_id) for ch_id in old_channels}
      last_message_ids.update(
          {int(ch_id): int(msg_id) for ch_id, msg_id in state.get("last_message_ids", {}).items()}
      )
      forwarding_targets.update({
          str(group_name): int(channel_id)
          for group_name, channel_id in state.get("forwarding_targets", {}).items()
      })
    except FileNotFoundError:
      pass
    except (json.JSONDecodeError, TypeError, ValueError) as e:
      print(f"[X] 讀取監聽進度失敗，將使用空白進度：{e}")

  def save_state(self):
    state = {
      "groups": {
        group_name: sorted(channel_ids)
        for group_name, channel_ids in monitored_groups.items()
      },
        "last_message_ids": {
            str(ch_id): msg_id for ch_id, msg_id in last_message_ids.items()
        },
        "forwarding_targets": forwarding_targets,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as state_file:
      json.dump(state, state_file, ensure_ascii=False, indent=2)

  async def on_ready(self):
    print(f"[系統] 已成功登入帳號：{self.user}\n")
    await self.main_menu()

  async def main_menu(self):
    loop = asyncio.get_event_loop()
    while True:
      print("=" * 35)
      print(f" 1. 監聽：{'已啟動' if self.listening_enabled else '未啟動'}")
      print(f" 2. 轉發：{'開啟' if self.forwarding_enabled else '關閉'}")
      print(" 3. 設定")
      print(" 4. 退出程式")
      print("=" * 35)

      choice = await loop.run_in_executor(
          None, input, "請選擇操作項目 (1-4): "
      )

      if choice == "1":
        monitored_channel_count = sum(
            len(channel_ids) for channel_ids in monitored_groups.values()
        )
        if not monitored_channel_count:
          print("[X] 監聽組為空，請先選擇頻道！\n")
          continue
        print(
            f"\n[!] 輪詢監聽器已啟動，目前監聽組：{len(monitored_groups)}，"
            f"頻道數：{monitored_channel_count}"
        )
        print("[!] 每 60～110 秒將隨機檢測一次新訊息。輸入 stop 可停止監聽並回到主選單。\n")
        self.listening_enabled = True
        if self.poll_task is None or self.poll_task.done():
          self.poll_task = asyncio.create_task(self.poll_messages_loop())
        self.listen_control_task = asyncio.create_task(
            self.listen_control_loop()
        )
        break
      elif choice == "2":
        await self.toggle_forwarding()
      elif choice == "3":
        await self.configure_menu()
      elif choice == "4":
        print("[系統] 程式已終止。")
        if self.forward_bot_task and not self.forward_bot_task.done():
          await self.forward_bot.close()
        await self.close()
        return
      else:
        print("[X] 無效選項，請重新輸入。\n")

  async def listen_control_loop(self):
    loop = asyncio.get_event_loop()
    while self.listening_enabled:
      command = await loop.run_in_executor(
          None, input, "[監聽中] 輸入 stop 停止監聽："
      )
      if command.strip().lower() == "stop":
        await self.stop_listening()
        self.listen_control_task = None
        await self.main_menu()
        return

  async def stop_listening(self):
    self.listening_enabled = False
    if self.poll_task and not self.poll_task.done():
      self.poll_task.cancel()
      try:
        await self.poll_task
      except asyncio.CancelledError:
        pass
    self.poll_task = None
    print("\n[!] 監聽已停止，返回主選單。\n")

  async def toggle_forwarding(self):
    if self.forwarding_enabled:
      self.forwarding_enabled = False
      await self.forward_bot.close()
      print("[!] 轉發功能已關閉。\n")
      return

    if not BOT_TOKEN:
      print("[X] 找不到 DISCORD_BOT_TOKEN，請在 .env 設定官方 Bot Token。\n")
      return

    if await self.start_forward_bot(BOT_TOKEN):
      self.forwarding_enabled = True
      print("[!] 轉發功能已啟動。\n")

  async def start_forward_bot(self, token):
    try:
      bot_name = await self.forward_bot.validate(token)
      print(f"[轉發] 官方 Bot token 有效：{bot_name}")
      return True
    except BotApiError as error:
      if error.status == 401:
        print("[X] 官方 Bot token 無效，請確認使用的是 Bot Token（不是 Client ID 或 Secret）。")
      elif error.status == 403:
        print("[X] 官方 Bot 沒有存取 Discord API 的權限。")
      else:
        print(f"[X] 官方 Bot 登入檢查失敗：{error}")
      return False

  async def forward_message(self, message, group_name, content):
    target_id = forwarding_targets.get(group_name)
    if not target_id:
      print(f"[!] 監聽組「{group_name}」尚未設定轉發目的頻道。")
      return
    source_name = getattr(message.guild, "name", "未知伺服器")
    source_channel = getattr(message.channel, "name", str(message.channel.id))
    sender_name = getattr(
      message.author,
      "display_name",
      getattr(message.author, "name", str(message.author)),
    )
    content = await self.replace_role_mentions(message.guild, content)
    embeds = await self.serialize_embeds(message)
    message_time = message.created_at.astimezone().strftime(
      "%Y-%m-%d %H:%M:%S"
    )
    forwarded_content = (
      "====================\n"
      f"# [來自「{source_name}」的「{source_channel}」頻道]\n"
      f"## {sender_name}:\n"
      f"時間：{message_time}\n"
      f"{content}\n"
      "===================="
    )
    try:
      for start in range(0, len(forwarded_content), 2000):
        await self.forward_bot.send_message(
            target_id,
            forwarded_content[start:start + 2000],
            embeds=embeds if start == 0 else None,
        )
      print(f"[轉發] 已送出至頻道 {target_id}")
    except BotApiError as error:
      if error.status == 403:
        print(f"[X] Bot 沒有頻道 {target_id} 的發送訊息權限。")
      elif error.status == 404:
        print(f"[X] 找不到轉發目的頻道 {target_id}，或 Bot 尚未加入該伺服器。")
      else:
        print(f"[X] 轉發訊息失敗（頻道 {target_id}）：{error}")

  async def replace_role_mentions(self, guild, content):
    role_mentions = re.findall(r"<@&(\d+)>", content)
    if not role_mentions or not guild:
      return content

    roles_by_id = {
        role.id: role.name for role in getattr(guild, "roles", [])
    }
    missing_role_ids = [
        int(role_id) for role_id in role_mentions
        if int(role_id) not in roles_by_id
    ]
    if missing_role_ids and hasattr(guild, "fetch_roles"):
      try:
        fetched_roles = await guild.fetch_roles()
        roles_by_id.update({role.id: role.name for role in fetched_roles})
      except Exception:
        pass

    def replace_match(match):
      role_id = int(match.group(1))
      role_name = roles_by_id.get(role_id)
      return f"@{role_name}" if role_name else f"@未知身份組 ({role_id})"

    return re.sub(r"<@&(\d+)>", replace_match, content)

  async def serialize_embeds(self, message):
    serialized = []
    for source_embed in getattr(message, "embeds", []):
      if hasattr(source_embed, "to_dict"):
        source_data = source_embed.to_dict()
      else:
        source_data = dict(source_embed)

      embed = {}
      for key in ("title", "description", "url", "timestamp", "color"):
        if source_data.get(key) is not None:
          embed[key] = source_data[key]

      for key in ("title", "description"):
        if key in embed:
          embed[key] = await self.replace_role_mentions(
              message.guild, embed[key]
          )

      for key in ("footer", "image", "thumbnail", "author"):
        value = source_data.get(key)
        if not isinstance(value, dict):
          continue
        allowed_keys = {
            "footer": ("text", "icon_url"),
            "image": ("url",),
            "thumbnail": ("url",),
            "author": ("name", "url", "icon_url"),
        }[key]
        cleaned_value = {
            nested_key: value[nested_key]
            for nested_key in allowed_keys
            if value.get(nested_key)
        }
        if cleaned_value:
          if key == "footer" and "text" in cleaned_value:
            cleaned_value["text"] = await self.replace_role_mentions(
                message.guild, cleaned_value["text"]
            )
          if key == "author" and "name" in cleaned_value:
            cleaned_value["name"] = await self.replace_role_mentions(
                message.guild, cleaned_value["name"]
            )
          embed[key] = cleaned_value

      fields = source_data.get("fields")
      if isinstance(fields, list):
        embed["fields"] = []
        for field in fields:
          if not isinstance(field, dict) or not field.get("name") or not field.get("value"):
            continue
          embed["fields"].append({
              "name": await self.replace_role_mentions(
                  message.guild, field["name"]
              ),
              "value": await self.replace_role_mentions(
                  message.guild, field["value"]
              ),
              **({"inline": field["inline"]} if field.get("inline") is not None else {}),
          })
        if not embed["fields"]:
          embed.pop("fields")

      if embed:
        serialized.append(embed)
      if len(serialized) == 10:
        break
    return serialized

  async def configure_menu(self):
    loop = asyncio.get_event_loop()
    while True:
      print("\n--- 目前監聽組 ---")
      if monitored_groups:
        for group_name, channel_ids in monitored_groups.items():
          print(f"[{group_name}] {sorted(channel_ids)}")
      else:
        print("（空）")
      print("----------------------------")
      print(" 1. 建立監聽組")
      print(" 2. 瀏覽伺服器並選擇頻道")
      print(" 3. 設定轉發目的頻道")
      print(" 4. 刪除單一頻道")
      print(" 5. 刪除整個監聽組")
      print(" 6. 清空所有監聽組")
      print(" 7. 返回主選單")

      choice = await loop.run_in_executor(
          None, input, "請選擇操作項目 (1-7): "
      )

      if choice == "1":
        group_name = await loop.run_in_executor(
            None, input, "請輸入新的監聽組名稱: "
        )
        group_name = group_name.strip()
        if not group_name:
          print("[X] 監聽組名稱不可為空。")
        elif group_name in monitored_groups:
          print("[X] 這個監聽組已經存在。")
        else:
          monitored_groups[group_name] = set()
          self.save_state()
          print(f"[+] 已建立監聽組：{group_name}")
      elif choice == "2":
        await self.select_guild_and_channel()
      elif choice == "3":
        await self.configure_forwarding_target()
      elif choice == "4":
        await self.remove_channel()
      elif choice == "5":
        await self.remove_group()
      elif choice == "6":
        monitored_groups.clear()
        forwarding_targets.clear()
        last_message_ids.clear()
        self.save_state()
        print("[!] 已清空所有監聽組與頻道。")
      elif choice == "7":
        break

  async def configure_forwarding_target(self):
    loop = asyncio.get_event_loop()
    group_names = list(monitored_groups)
    if not group_names:
      print("[X] 尚未建立監聽組，請先建立監聽組。")
      return

    print("\n--- 監聽組與轉發目的頻道 ---")
    for idx, group_name in enumerate(group_names, start=1):
      target_id = forwarding_targets.get(group_name, "未設定")
      print(f"[{idx}] {group_name} -> {target_id}")

    group_idx = await loop.run_in_executor(
        None, input, "請選擇要設定的監聽組編號 (輸入 0 取消): "
    )
    if (
        not group_idx.isdigit()
        or int(group_idx) == 0
        or int(group_idx) > len(group_names)
    ):
      return

    group_name = group_names[int(group_idx) - 1]
    target_id = await loop.run_in_executor(
        None, input, "請輸入目的文字頻道 ID (輸入 0 清除設定): "
    )
    target_id = target_id.strip()
    if target_id == "0":
      forwarding_targets.pop(group_name, None)
      self.save_state()
      print(f"[+] 已清除「{group_name}」的轉發目的頻道。")
    elif target_id.isdigit():
      forwarding_targets[group_name] = int(target_id)
      self.save_state()
      print(f"[+] 已設定「{group_name}」轉發到頻道 {target_id}。")
    else:
      print("[X] 頻道 ID 必須是數字。")

  async def remove_channel(self):
    loop = asyncio.get_event_loop()
    channels = [
        (group_name, channel_id)
        for group_name, channel_ids in monitored_groups.items()
        for channel_id in channel_ids
    ]
    if not channels:
      print("[X] 目前沒有可刪除的頻道。")
      return

    print("\n--- 目前監聽頻道 ---")
    for idx, (group_name, channel_id) in enumerate(channels, start=1):
      channel = self.get_channel(channel_id)
      channel_name = channel.name if channel else str(channel_id)
      print(f"[{idx}] #{channel_name} ({channel_id}) - 組：{group_name}")

    choice = await loop.run_in_executor(
        None, input, "請選擇要刪除的頻道編號 (輸入 0 取消): "
    )
    if not choice.isdigit() or int(choice) == 0 or int(choice) > len(channels):
      return

    group_name, channel_id = channels[int(choice) - 1]
    monitored_groups[group_name].discard(channel_id)
    last_message_ids.pop(channel_id, None)
    if not monitored_groups[group_name]:
      del monitored_groups[group_name]
    self.save_state()
    print(f"[+] 已刪除頻道 ID：{channel_id}")

  async def remove_group(self):
    loop = asyncio.get_event_loop()
    group_names = list(monitored_groups)
    if not group_names:
      print("[X] 目前沒有可刪除的監聽組。")
      return

    print("\n--- 目前監聽組 ---")
    for idx, group_name in enumerate(group_names, start=1):
      print(f"[{idx}] {group_name} ({len(monitored_groups[group_name])} 個頻道)")

    choice = await loop.run_in_executor(
        None, input, "請選擇要刪除的組別編號 (輸入 0 取消): "
    )
    if not choice.isdigit() or int(choice) == 0 or int(choice) > len(group_names):
      return

    group_name = group_names[int(choice) - 1]
    for channel_id in monitored_groups[group_name]:
      last_message_ids.pop(channel_id, None)
    del monitored_groups[group_name]
    forwarding_targets.pop(group_name, None)
    self.save_state()
    print(f"[+] 已刪除監聽組：{group_name}")

  async def select_guild_and_channel(self):
    loop = asyncio.get_event_loop()
    guilds = list(self.guilds)

    if not guilds:
      print("[X] 未能讀取到任何已加入的伺服器。")
      return

    print("\n--- 已加入的伺服器清單 ---")
    for idx, guild in enumerate(guilds, start=1):
      print(f"[{idx}] {guild.name} (ID: {guild.id})")

    guild_idx = await loop.run_in_executor(
        None, input, "請選擇伺服器編號 (輸入 0 取消): "
    )
    if (
        not guild_idx.isdigit()
        or int(guild_idx) == 0
        or int(guild_idx) > len(guilds)
    ):
      return

    selected_guild = guilds[int(guild_idx) - 1]
    text_channels = [
        ch
        for ch in selected_guild.channels
        if isinstance(ch, discord.TextChannel)
    ]

    if not text_channels:
      print("[X] 該伺服器內無可讀取的文字頻道。")
      return
    if not monitored_groups:
      print("[X] 尚未建立監聽組，請先返回建立監聽組。")
      return

    print(f"\n--- [{selected_guild.name}] 文字頻道清單 ---")
    for idx, ch in enumerate(text_channels, start=1):
      current_group = next(
          (group_name for group_name, channel_ids in monitored_groups.items()
           if ch.id in channel_ids),
          None,
      )
      status = f" [監聽組：{current_group}]" if current_group else ""
      print(f"[{idx}] #{ch.name} (ID: {ch.id}){status}")

    ch_idx = await loop.run_in_executor(
        None, input, "請選擇要監聽的頻道編號 (輸入 0 取消): "
    )
    if (
        not ch_idx.isdigit()
        or int(ch_idx) == 0
        or int(ch_idx) > len(text_channels)
    ):
      return

    selected_channel = text_channels[int(ch_idx) - 1]

    print("\n--- 監聽組清單 ---")
    group_names = list(monitored_groups)
    for idx, group_name in enumerate(group_names, start=1):
      print(f"[{idx}] {group_name}")
    group_idx = await loop.run_in_executor(
        None, input, "請選擇此頻道要加入的組別編號 (輸入 0 取消): "
    )
    if (
        not group_idx.isdigit()
        or int(group_idx) == 0
        or int(group_idx) > len(group_names)
    ):
      return
    group_name = group_names[int(group_idx) - 1]

    for channel_ids in monitored_groups.values():
      channel_ids.discard(selected_channel.id)
    monitored_groups.setdefault(group_name, set()).add(selected_channel.id)

    if selected_channel.id not in last_message_ids:
      # 新頻道以目前最新訊息作為基準，避免印出加入前的舊歷史訊息。
      try:
        async for msg in selected_channel.history(limit=1):
          last_message_ids[selected_channel.id] = msg.id
      except Exception:
        pass
    self.save_state()

    print(
      f"[+] 成功加入頻道：#{selected_channel.name} ({selected_channel.id})"
      f"，監聽組：{group_name}"
    )

  async def poll_messages_loop(self):
    while True:
      now_str = datetime.datetime.now().strftime("%H:%M:%S")
      print(f"[{now_str}] 執行週期檢查中...")

      channel_to_group = {
          ch_id: group_name
          for group_name, channel_ids in monitored_groups.items()
          for ch_id in channel_ids
      }

      for ch_id, group_name in list(channel_to_group.items()):
        channel = self.get_channel(ch_id)
        if not channel:
          try:
            channel = await self.fetch_channel(ch_id)
          except Exception as e:
            print(f"[X] 無法存取頻道 {ch_id}: {e}")
            continue

        last_id = last_message_ids.get(ch_id)
        after_obj = discord.Object(id=last_id) if last_id else None

        try:
          new_messages = []
          # 抓取上次紀錄 ID 之後產生的新訊息
          async for msg in channel.history(
              limit=50, after=after_obj, oldest_first=True
          ):
            if msg.author != self.user:
              new_messages.append(msg)

          for msg in new_messages:
            content = msg.content
            if msg.attachments:
              content += " " + " ".join([att.url for att in msg.attachments])
            message_time = msg.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")

            print(
              f"\n[新訊息 Alert] [{group_name}]"
              f" [{msg.guild.name} -> #{msg.channel.name}]"
                f" [{message_time}] {msg.author}: {content}"
            )
            if self.forwarding_enabled:
              await self.forward_message(msg, group_name, content)

          if new_messages:
            # 更新該頻道的最新紀錄 ID
            last_message_ids[ch_id] = new_messages[-1].id
            self.save_state()

        except Exception as e:
          print(f"[X] 讀取頻道 #{channel.name} 歷史紀錄失敗: {e}")

      # 基準 60 秒，加上 0～50 秒的隨機延遲，降低固定週期特徵。
        wait_seconds = POLL_MIN_SECONDS + random.randint(
          0, max(0, POLL_MAX_SECONDS - POLL_MIN_SECONDS)
        )
      print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 下次檢查將在 {wait_seconds} 秒後執行...")
      await asyncio.sleep(wait_seconds)


async def validate_token(token):
  validation_client = discord.Client()
  try:
    await validation_client.login(token)
    print(f"[登入檢查] Token 有效，已確認帳號：{validation_client.user}")
    return True
  except discord.LoginFailure:
    print("[X] Token 無效或已失效，請重新取得 DISCORD_USER_TOKEN。")
  except discord.HTTPException as error:
    if error.status == 401:
      print("[X] Token 無效或已失效，請重新取得 DISCORD_USER_TOKEN。")
    else:
      print(f"[X] Discord 登入檢查失敗（HTTP {error.status}），請稍後再試。")
  except Exception:
    print("[X] 無法完成 Discord 登入檢查，請確認網路連線與 Token 設定。")
  finally:
    await validation_client.close()
  return False


async def start_client(token):
  if not await validate_token(token):
    return

  client = InteractivePollingSelfBot()
  try:
    await client.start(token)
  except discord.LoginFailure:
    print("[X] 啟動時 Token 已失效，程式已停止。")
  except discord.HTTPException as error:
    print(f"[X] Discord 連線失敗（HTTP {error.status}），程式已停止。")
  except Exception:
    print("[X] Discord 連線失敗，程式已停止；請確認網路與 Token。")
  finally:
    if not client.is_closed():
      await client.close()


if __name__ == "__main__":
  configure_console_encoding()
  if not USER_TOKEN:
    print("[X] 找不到 DISCORD_USER_TOKEN，請在 .env 設定使用者 Token。")
    sys.exit(1)
  asyncio.run(start_client(USER_TOKEN))