import asyncio
import datetime
import json
import random
import discord
from dotenv import load_dotenv
import os

load_dotenv()

USER_TOKEN = os.environ.get('DISCORD_USER_TOKEN')

monitored_groups = {}
last_message_ids = {}  # 紀錄各頻道最新處理過的訊息 ID，避免重複發送
STATE_FILE = "listener_state.json"


class InteractivePollingSelfBot(discord.Client):

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.poll_task = None
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
      print(" 1. 啟動監聽 (每 60～110 秒隨機輪詢)")
      print(" 2. 調整監聽組")
      print(" 3. 退出程式")
      print("=" * 35)

      choice = await loop.run_in_executor(
          None, input, "請選擇操作項目 (1-3): "
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
        print("[!] 每 60～110 秒將隨機檢測一次新訊息... (暫停請按 Ctrl+C)\n")
        if self.poll_task is None or self.poll_task.done():
          self.poll_task = asyncio.create_task(self.poll_messages_loop())
        break
      elif choice == "2":
        await self.configure_menu()
      elif choice == "3":
        print("[系統] 程式已終止。")
        await self.close()
        return
      else:
        print("[X] 無效選項，請重新輸入。\n")

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
      print(" 3. 刪除單一頻道")
      print(" 4. 刪除整個監聽組")
      print(" 5. 清空所有監聽組")
      print(" 6. 返回主選單")

      choice = await loop.run_in_executor(
          None, input, "請選擇操作項目 (1-3): "
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
        await self.remove_channel()
      elif choice == "4":
        await self.remove_group()
      elif choice == "5":
        monitored_groups.clear()
        last_message_ids.clear()
        self.save_state()
        print("[!] 已清空所有監聽組與頻道。")
      elif choice == "6":
        break

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

          if new_messages:
            # 更新該頻道的最新紀錄 ID
            last_message_ids[ch_id] = new_messages[-1].id
            self.save_state()

        except Exception as e:
          print(f"[X] 讀取頻道 #{channel.name} 歷史紀錄失敗: {e}")

      # 基準 60 秒，加上 0～50 秒的隨機延遲，降低固定週期特徵。
      wait_seconds = 60 + random.randint(0, 50)
      print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 下次檢查將在 {wait_seconds} 秒後執行...")
      await asyncio.sleep(wait_seconds)


client = InteractivePollingSelfBot()
client.run(USER_TOKEN)