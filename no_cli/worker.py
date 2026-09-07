"""Non-interactive worker.

Tokens come from environment variables. Monitoring and forwarding assignments
come from no_cli/config.json.
"""

import asyncio
import json
import os
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import listen


CONFIG_FILE = SCRIPT_DIR / "config.json"


def load_config():
  try:
    with CONFIG_FILE.open("r", encoding="utf-8") as config_file:
      config = json.load(config_file)
  except FileNotFoundError as error:
    raise RuntimeError(f"找不到設定檔：{CONFIG_FILE}") from error
  except json.JSONDecodeError as error:
    raise RuntimeError(f"設定檔 JSON 格式錯誤：{error}") from error

  groups = config.get("groups", {})
  targets = config.get("forwarding_targets", {})
  if not isinstance(groups, dict) or not isinstance(targets, dict):
    raise RuntimeError("config.json 的 groups 與 forwarding_targets 必須是物件。")

  configured_groups = {}
  for group_name, channel_ids in groups.items():
    if not isinstance(group_name, str) or not group_name.strip():
      raise RuntimeError("監聽組名稱不可為空。")
    if not isinstance(channel_ids, list) or not all(
        str(channel_id).isdigit() for channel_id in channel_ids
    ):
      raise RuntimeError(f"監聽組「{group_name}」的頻道 ID 必須是數字陣列。")
    configured_groups[group_name] = {int(channel_id) for channel_id in channel_ids}

  configured_targets = {}
  for group_name, channel_id in targets.items():
    if group_name not in configured_groups:
      raise RuntimeError(f"轉發目標「{group_name}」沒有對應的監聽組。")
    if not str(channel_id).isdigit():
      raise RuntimeError(f"監聽組「{group_name}」的轉發頻道 ID 必須是數字。")
    configured_targets[group_name] = int(channel_id)

  missing_targets = set(configured_groups) - set(configured_targets)
  if missing_targets:
    missing_names = "、".join(sorted(missing_targets))
    raise RuntimeError(f"監聽組尚未設定轉發目的頻道：{missing_names}")

  poll_min = int(config.get("poll_min_seconds", 60))
  poll_max = int(config.get("poll_max_seconds", 110))
  if poll_min < 1 or poll_max < poll_min:
    raise RuntimeError("poll_min_seconds 必須大於 0，且不可大於 poll_max_seconds。")

  return configured_groups, configured_targets, poll_min, poll_max


class NonInteractiveClient(listen.InteractivePollingSelfBot):

  async def on_ready(self):
    if self.listening_enabled:
      return
    print(f"[無 CLI] 已登入來源帳號：{self.user}")
    if not listen.BOT_TOKEN:
      raise RuntimeError("找不到 DISCORD_BOT_TOKEN。")
    if not await self.start_forward_bot(listen.BOT_TOKEN):
      raise RuntimeError("官方 Bot token 驗證失敗。")
    self.forwarding_enabled = True
    self.listening_enabled = True
    self.poll_task = asyncio.create_task(self.poll_messages_loop())
    print("[無 CLI] 非互動監聽與轉發已啟動。")


async def run_worker():
  groups, targets, poll_min, poll_max = load_config()
  listen.STATE_FILE = str(SCRIPT_DIR / "listener_state.json")
  listen.POLL_MIN_SECONDS = poll_min
  listen.POLL_MAX_SECONDS = poll_max
  listen.monitored_groups.clear()
  listen.monitored_groups.update(groups)
  listen.forwarding_targets.clear()
  listen.forwarding_targets.update(targets)

  if not listen.USER_TOKEN:
    raise RuntimeError("找不到 DISCORD_USER_TOKEN。")
  if not listen.BOT_TOKEN:
    raise RuntimeError("找不到 DISCORD_BOT_TOKEN。")
  if not any(groups.values()):
    raise RuntimeError("config.json 至少要設定一個來源頻道。")

  if not await listen.validate_token(listen.USER_TOKEN):
    return

  client = NonInteractiveClient()
  try:
    await client.start(listen.USER_TOKEN)
  finally:
    if not client.is_closed():
      await client.close()


if __name__ == "__main__":
  listen.configure_console_encoding()
  try:
    asyncio.run(run_worker())
  except (RuntimeError, ValueError) as error:
    print(f"[無 CLI][X] {error}", file=sys.stderr)
    sys.exit(1)
