#!/usr/bin/env python3
"""Telegram channel reader for Claude Code.

Usage:
    python tg.py auth                              # interactive login
    python tg.py channels                          # list joined channels/groups
    python tg.py read <channel> [--limit N]        # read recent posts
    python tg.py search <query> [--channels ...]   # search across channels
    python tg.py post <channel> <msg_id>           # get specific post
    python tg.py media <channel> <msg_id> <path>   # download media to path
    python tg.py folders                           # list Telegram folders with channels
"""

import argparse
import asyncio
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    Channel,
    Chat,
    Document,
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaWebPage,
    Photo,
)
from telethon.tl.functions.messages import GetDialogFiltersRequest

ENV_FILE = Path.home() / "code-environment" / "telegram.env"
SESSION_FILE = Path.home() / "code-environment" / ".telegram-session"


def load_credentials():
    creds = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip()
    return int(creds["TG_API_ID"]), creds["TG_API_HASH"]


def get_client():
    api_id, api_hash = load_credentials()
    return TelegramClient(str(SESSION_FILE), api_id, api_hash)


def serialize_message(msg: Message) -> dict:
    """Convert a Telegram message to a JSON-serializable dict."""
    result = {
        "id": msg.id,
        "date": msg.date.isoformat() if msg.date else None,
        "text": msg.text or "",
        "has_media": msg.media is not None,
        "media_type": None,
        "views": getattr(msg, "views", None),
        "forwards": getattr(msg, "forwards", None),
    }

    if isinstance(msg.media, MessageMediaPhoto):
        result["media_type"] = "photo"
    elif isinstance(msg.media, MessageMediaDocument):
        doc = msg.media.document
        if doc and hasattr(doc, "mime_type"):
            result["media_type"] = doc.mime_type
        else:
            result["media_type"] = "document"
    elif isinstance(msg.media, MessageMediaWebPage):
        result["media_type"] = "webpage"

    # Grouped media (album)
    if msg.grouped_id:
        result["grouped_id"] = str(msg.grouped_id)

    return result


# --- Commands ---


async def cmd_auth(client):
    """Interactive authentication — run manually once."""
    await client.start()
    me = await client.get_me()
    # Lock down session file
    SESSION_PATH = Path(str(SESSION_FILE) + ".session")
    if SESSION_PATH.exists():
        os.chmod(SESSION_PATH, 0o600)
    print(json.dumps({
        "status": "authenticated",
        "user": me.first_name,
        "username": me.username,
        "phone": me.phone,
    }))


async def cmd_channels(client):
    """List joined channels and groups."""
    await client.connect()
    if not await client.is_user_authorized():
        print(json.dumps({"error": "Not authenticated. Run: python tg.py auth"}))
        return

    result = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, (Channel, Chat)):
            entry = {
                "id": entity.id,
                "title": dialog.title,
                "username": getattr(entity, "username", None),
                "type": "channel" if isinstance(entity, Channel) and entity.broadcast else "group",
                "unread": dialog.unread_count,
            }
            if hasattr(entity, "participants_count") and entity.participants_count:
                entry["members"] = entity.participants_count
            result.append(entry)

    print(json.dumps(result, ensure_ascii=False))


async def cmd_folders(client):
    """List Telegram folders with their channels."""
    await client.connect()
    if not await client.is_user_authorized():
        print(json.dumps({"error": "Not authenticated. Run: python tg.py auth"}))
        return

    filters_result = await client(GetDialogFiltersRequest())
    # Build entity cache for resolving peer IDs
    dialogs = await client.get_dialogs()
    entity_map = {}
    for d in dialogs:
        entity_map[d.entity.id] = {
            "title": d.title,
            "username": getattr(d.entity, "username", None),
        }

    folders = []
    for f in filters_result.filters:
        # Skip the default "All" filter
        if not hasattr(f, "title") or not f.title:
            continue

        # Extract title — can be a string or TextWithEntities
        title = f.title if isinstance(f.title, str) else getattr(f.title, "text", str(f.title))

        included = []
        if hasattr(f, "include_peers") and f.include_peers:
            for peer in f.include_peers:
                peer_id = getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None) or getattr(peer, "user_id", None)
                if peer_id and peer_id in entity_map:
                    included.append(entity_map[peer_id])
                elif peer_id:
                    included.append({"id": peer_id})

        folders.append({
            "id": f.id,
            "title": title,
            "channels": included,
            "count": len(included),
        })

    print(json.dumps(folders, ensure_ascii=False))


async def cmd_read(client, channel: str, limit: int):
    """Read recent posts from a channel."""
    await client.connect()
    if not await client.is_user_authorized():
        print(json.dumps({"error": "Not authenticated. Run: python tg.py auth"}))
        return

    entity = await client.get_entity(channel)
    messages = []
    async for msg in client.iter_messages(entity, limit=limit):
        messages.append(serialize_message(msg))

    meta = {
        "channel": channel,
        "title": getattr(entity, "title", channel),
        "count": len(messages),
    }
    print(json.dumps({"meta": meta, "messages": messages}, ensure_ascii=False))


async def cmd_search(client, query: str, channels: list[str] | None, limit: int):
    """Search across channels."""
    await client.connect()
    if not await client.is_user_authorized():
        print(json.dumps({"error": "Not authenticated. Run: python tg.py auth"}))
        return

    targets = []
    if channels:
        for ch in channels:
            targets.append(await client.get_entity(ch))
    else:
        # Search all channels/groups
        async for dialog in client.iter_dialogs():
            if isinstance(dialog.entity, (Channel, Chat)):
                targets.append(dialog.entity)

    results = []
    for entity in targets:
        try:
            async for msg in client.iter_messages(entity, search=query, limit=limit):
                entry = serialize_message(msg)
                entry["channel"] = getattr(entity, "username", None) or str(entity.id)
                entry["channel_title"] = getattr(entity, "title", "")
                results.append(entry)
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
            try:
                async for msg in client.iter_messages(entity, search=query, limit=limit):
                    entry = serialize_message(msg)
                    entry["channel"] = getattr(entity, "username", None) or str(entity.id)
                    entry["channel_title"] = getattr(entity, "title", "")
                    results.append(entry)
            except Exception:
                pass
        except Exception as e:
            # Some channels may restrict search
            pass
        await asyncio.sleep(1.0)

    print(json.dumps({
        "query": query,
        "count": len(results),
        "results": results,
    }, ensure_ascii=False))


async def cmd_post(client, channel: str, msg_id: int):
    """Get a specific post with full details."""
    await client.connect()
    if not await client.is_user_authorized():
        print(json.dumps({"error": "Not authenticated. Run: python tg.py auth"}))
        return

    entity = await client.get_entity(channel)
    msg = await client.get_messages(entity, ids=msg_id)

    if not msg:
        print(json.dumps({"error": f"Message {msg_id} not found in {channel}"}))
        return

    result = serialize_message(msg)
    result["channel"] = channel
    result["channel_title"] = getattr(entity, "title", channel)

    # If part of an album, fetch all grouped messages
    if msg.grouped_id:
        album = []
        async for m in client.iter_messages(entity, limit=20, offset_id=msg_id + 10):
            if m.grouped_id == msg.grouped_id:
                album.append(serialize_message(m))
            elif m.id < msg_id - 10:
                break
        if len(album) > 1:
            result["album"] = album

    print(json.dumps(result, ensure_ascii=False))


async def cmd_media(client, channel: str, msg_id: int, dest_path: str):
    """Download media from a message to dest_path."""
    await client.connect()
    if not await client.is_user_authorized():
        print(json.dumps({"error": "Not authenticated. Run: python tg.py auth"}))
        return

    entity = await client.get_entity(channel)
    msg = await client.get_messages(entity, ids=msg_id)

    if not msg:
        print(json.dumps({"error": f"Message {msg_id} not found in {channel}"}))
        return

    if not msg.media:
        print(json.dumps({"error": f"Message {msg_id} has no media"}))
        return

    dest = Path(dest_path)
    dest.mkdir(parents=True, exist_ok=True)

    # Build filename: tg-channel-msgid[-n].ext
    ch_name = channel.lstrip("@").replace("/", "-")

    downloaded = []

    # Handle albums: download all grouped messages
    messages_to_download = [msg]
    if msg.grouped_id:
        async for m in client.iter_messages(entity, limit=20, offset_id=msg_id + 10):
            if m.grouped_id == msg.grouped_id and m.id != msg_id and m.media:
                messages_to_download.append(m)
            elif m.id < msg_id - 10:
                break
        messages_to_download.sort(key=lambda m: m.id)

    for idx, m in enumerate(messages_to_download):
        # Determine extension
        ext = ".jpg"  # default for photos
        if isinstance(m.media, MessageMediaDocument):
            doc = m.media.document
            if hasattr(doc, "mime_type"):
                mime_map = {
                    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                    "image/webp": ".webp", "video/mp4": ".mp4", "audio/ogg": ".ogg",
                    "application/pdf": ".pdf",
                }
                ext = mime_map.get(doc.mime_type, ".bin")

        suffix = f"-{idx + 1}" if len(messages_to_download) > 1 else ""
        filename = f"tg-{ch_name}-{m.id}{suffix}{ext}"
        filepath = dest / filename

        await client.download_media(m, file=str(filepath))
        downloaded.append({"file": str(filepath), "message_id": m.id})

    print(json.dumps({"downloaded": downloaded}, ensure_ascii=False))


async def main():
    parser = argparse.ArgumentParser(description="Telegram channel reader")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("auth", help="Interactive authentication")
    sub.add_parser("channels", help="List channels/groups")
    sub.add_parser("folders", help="List Telegram folders")

    read_p = sub.add_parser("read", help="Read recent posts")
    read_p.add_argument("channel", help="Channel username or ID")
    read_p.add_argument("--limit", type=int, default=20)

    search_p = sub.add_parser("search", help="Search across channels")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--channels", nargs="*", help="Limit to specific channels")
    search_p.add_argument("--limit", type=int, default=5, help="Results per channel")

    post_p = sub.add_parser("post", help="Get specific post")
    post_p.add_argument("channel")
    post_p.add_argument("msg_id", type=int)

    media_p = sub.add_parser("media", help="Download media")
    media_p.add_argument("channel")
    media_p.add_argument("msg_id", type=int)
    media_p.add_argument("path", help="Destination directory")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    lock_file = open("/tmp/tg_api.lock", "w")
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    client = get_client()
    try:
        if args.command == "auth":
            await cmd_auth(client)
        elif args.command == "channels":
            await cmd_channels(client)
        elif args.command == "folders":
            await cmd_folders(client)
        elif args.command == "read":
            await cmd_read(client, args.channel, args.limit)
        elif args.command == "search":
            await cmd_search(client, args.query, args.channels, args.limit)
        elif args.command == "post":
            await cmd_post(client, args.channel, args.msg_id)
        elif args.command == "media":
            await cmd_media(client, args.channel, args.msg_id, args.path)
    finally:
        await client.disconnect()
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    asyncio.run(main())
