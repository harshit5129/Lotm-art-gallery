import requests
import json
import os
import argparse
import sys
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, TypedDict, Callable
from enum import IntEnum
from dataclasses import dataclass
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

# Async foundation imports (for future migration)
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


console = Console()


class ChannelType(IntEnum):
    GUILD_TEXT = 0
    GUILD_VOICE = 2
    GUILD_CATEGORY = 4
    GUILD_NEWS = 5


class DownloadStats(TypedDict):
    total_messages: int
    text_messages: int
    media_downloaded: int
    failed_downloads: int


class TransferStats(TypedDict):
    total_messages: int
    images_found: int
    images_transferred: int
    failed_transfers: int
    text_messages: int
    text_transferred: int


class TelegramStats(TypedDict):
    total_images: int
    images_uploaded: int
    albums_sent: int
    failed_uploads: int
    text_captions: int


class DiscordAPIError(Exception):
    pass


class TelegramAPIError(Exception):
    pass


@dataclass
class Config:
    # Discord API
    API_BASE_URL: str = "https://discord.com/api/v9"
    REQUEST_TIMEOUT: int = 30
    MESSAGE_LIMIT: int = 100
    IMAGE_EXTENSIONS: frozenset = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"})
    TEXT_CHANNEL_TYPES: frozenset = frozenset({ChannelType.GUILD_TEXT, ChannelType.GUILD_NEWS})
    TRANSFER_BATCH_SIZE: int = 5
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 1.0

    # Discord limits
    DISCORD_MESSAGE_LIMIT: int = 2000

    # Telegram API
    TELEGRAM_API_BASE: str = "https://api.telegram.org/bot{token}/{method}"
    TELEGRAM_MAX_ALBUM_SIZE: int = 10
    TELEGRAM_PHOTO_SIZE_LIMIT: int = 10 * 1024 * 1024  # 10MB
    TELEGRAM_CAPTION_LIMIT: int = 1024


config = Config()


class AsyncHTTPClient:
    """Async HTTP client foundation for future async migration."""

    def __init__(self):
        self._session: Optional[Any] = None

    async def __aenter__(self):
        if AIOHTTP_AVAILABLE:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()
            self._session = None

    async def request(self, url: str, method: str = "GET", **kwargs) -> Any:
        """Make async HTTP request (placeholder for future implementation)."""
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp is required for async operations")
        # Placeholder - full async implementation would go here
        pass


def get_env_var(var_name: str, default: Optional[str] = None) -> str:
    value = os.getenv(var_name, default)
    if not value:
        raise ValueError(f"Environment variable {var_name} is not set")
    return value


def get_headers(auth_token: str) -> Dict[str, str]:
    return {"authorization": auth_token}


def _parse_retry_after(response: requests.Response) -> float:
    """Parse Retry-After header from response."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except (ValueError, TypeError):
            pass
    return config.RETRY_DELAY


def make_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    files: Optional[Dict[str, Any]] = None,
    max_retries: int = config.MAX_RETRIES,
) -> Any:
    last_error = None

    for attempt in range(max_retries):
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=data,
                json=json_data,
                files=files,
                timeout=config.REQUEST_TIMEOUT,
            )

            # Handle rate limiting
            if response.status_code == 429:
                retry_after = _parse_retry_after(response)
                jitter = random.uniform(0, 0.5)
                sleep_time = retry_after + jitter
                console.print(f"[yellow]Rate limited. Waiting {sleep_time:.1f}s...[/yellow]")
                time.sleep(sleep_time)
                continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException as e:
            last_error = e
            if attempt < max_retries - 1:
                sleep_time = config.RETRY_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(sleep_time)

        except json.JSONDecodeError as e:
            raise DiscordAPIError(f"Failed to parse JSON response: {e}")

    raise DiscordAPIError(f"Request failed after {max_retries} attempts: {last_error}")


def truncate_text(text: str, max_length: int) -> str:
    """Truncate text to specified length with ellipsis."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def validate_file_size(file_path: Path, max_size: int) -> bool:
    """Check if file size is within limit."""
    if not file_path.exists():
        return False
    return file_path.stat().st_size <= max_size


def get_guilds(auth_token: str) -> List[Dict[str, Any]]:
    try:
        return make_request(
            f"{config.API_BASE_URL}/users/@me/guilds",
            headers=get_headers(auth_token),
        )
    except DiscordAPIError as e:
        console.print(f"[red]Failed to fetch guilds: {e}[/red]")
        return []


def get_channels(guild_id: str, auth_token: str) -> List[Dict[str, Any]]:
    try:
        return make_request(
            f"{config.API_BASE_URL}/guilds/{guild_id}/channels",
            headers=get_headers(auth_token),
        )
    except DiscordAPIError as e:
        console.print(f"[red]Failed to fetch channels: {e}[/red]")
        return []


def get_channel_messages(
    channel_id: str,
    auth_token: str,
    limit: int = config.MESSAGE_LIMIT,
    before: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params = {"limit": limit}
    if before:
        params["before"] = before

    try:
        return make_request(
            f"{config.API_BASE_URL}/channels/{channel_id}/messages",
            headers=get_headers(auth_token),
            params=params,
        )
    except DiscordAPIError:
        return []


def count_images_in_channel(channel_id: str, auth_token: str) -> int:
    image_count = 0
    last_message_id = None

    while True:
        messages = get_channel_messages(channel_id, auth_token, before=last_message_id)
        if not messages:
            break

        for message in messages:
            last_message_id = message.get("id")
            for attachment in message.get("attachments", []):
                content_type = attachment.get("content_type", "")
                if content_type.startswith("image/"):
                    image_count += 1

    return image_count


def download_media(url: str, folder_path: Path, filename: str, message_id: str) -> bool:
    try:
        response = requests.get(url, timeout=config.REQUEST_TIMEOUT)
        response.raise_for_status()

        file_extension = Path(filename).suffix
        safe_filename = f"{message_id}{file_extension}"
        file_path = folder_path / safe_filename

        with open(file_path, "wb") as file:
            file.write(response.content)

        return True
    except requests.RequestException:
        return False


def upload_image_to_channel(file_path: Path, channel_id: str, auth_token: str) -> bool:
    # File existence validation
    if not file_path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        return False

    try:
        with open(file_path, "rb") as file:
            files = {"file": (file_path.name, file, "image/*")}
            data = {"content": ""}
            make_request(
                f"{config.API_BASE_URL}/channels/{channel_id}/messages",
                method="POST",
                headers=get_headers(auth_token),
                files=files,
                data=data,
            )
            return True
    except (DiscordAPIError, IOError) as e:
        console.print(f"[red]Failed to upload {file_path.name}: {e}[/red]")
        return False


def upload_image_with_text(file_path: Path, channel_id: str, auth_token: str, text_content: str = "") -> bool:
    # File existence validation
    if not file_path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        return False

    # Truncate text to Discord's limit
    text_content = truncate_text(text_content, config.DISCORD_MESSAGE_LIMIT)

    try:
        with open(file_path, "rb") as file:
            files = {"file": (file_path.name, file, "image/*")}
            data = {"content": text_content}
            make_request(
                f"{config.API_BASE_URL}/channels/{channel_id}/messages",
                method="POST",
                headers=get_headers(auth_token),
                files=files,
                data=data,
            )
            return True
    except (DiscordAPIError, IOError) as e:
        console.print(f"[red]Failed to upload {file_path.name}: {e}[/red]")
        return False


# ==================== Telegram API Functions ====================


def telegram_api_request(bot_token: str, method: str, data: Optional[Dict] = None, files: Optional[Dict] = None) -> Dict:
    """Make a request to Telegram Bot API."""
    url = config.TELEGRAM_API_BASE.format(token=bot_token, method=method)

    try:
        if files:
            response = requests.post(url, data=data, files=files, timeout=config.REQUEST_TIMEOUT)
        else:
            response = requests.post(url, json=data, timeout=config.REQUEST_TIMEOUT)

        # Handle rate limiting
        if response.status_code == 429:
            retry_after = _parse_retry_after(response)
            console.print(f"[yellow]Telegram rate limited. Waiting {retry_after:.1f}s...[/yellow]")
            time.sleep(retry_after)
            return telegram_api_request(bot_token, method, data, files)

        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            raise TelegramAPIError(result.get("description", "Unknown error"))

        return result["result"]

    except requests.RequestException as e:
        raise TelegramAPIError(f"Request failed: {e}")


def verify_telegram_chat(bot_token: str, chat_id: str) -> bool:
    """Verify that bot has access to target chat."""
    try:
        result = telegram_api_request(bot_token, "getChat", {"chat_id": chat_id})
        chat_type = result.get("type", "unknown")
        chat_title = result.get("title") or result.get("username") or result.get("first_name", "Unknown")
        console.print(f"[green]Verified Telegram chat: {chat_title} (type: {chat_type})[/green]")
        return True
    except TelegramAPIError as e:
        console.print(f"[red]Failed to verify Telegram chat: {e}[/red]")
        return False


def send_telegram_photo(bot_token: str, chat_id: str, file_path: Path, caption: str = "") -> bool:
    """Send a single photo to Telegram."""
    # File existence validation
    if not file_path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        return False

    # File size validation
    if not validate_file_size(file_path, config.TELEGRAM_PHOTO_SIZE_LIMIT):
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        console.print(f"[yellow]Skipping {file_path.name}: {file_size_mb:.1f}MB exceeds 10MB limit[/yellow]")
        return False

    # Truncate caption
    caption = truncate_text(caption, config.TELEGRAM_CAPTION_LIMIT)

    try:
        with open(file_path, "rb") as photo:
            files = {"photo": photo}
            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            telegram_api_request(bot_token, "sendPhoto", data, files)
            return True
    except (TelegramAPIError, IOError) as e:
        console.print(f"[red]Failed to send photo {file_path.name}: {e}[/red]")
        return False


def send_telegram_media_group(bot_token: str, chat_id: str, media_group: List[Dict]) -> bool:
    """Send a media group (album) to Telegram."""
    if not media_group:
        return True

    # Prepare media array
    media = []
    files = {}

    for i, item in enumerate(media_group):
        file_path = item["file_path"]

        # File existence validation
        if not file_path.exists():
            console.print(f"[red]File not found: {file_path}[/red]")
            continue

        # File size validation
        if not validate_file_size(file_path, config.TELEGRAM_PHOTO_SIZE_LIMIT):
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            console.print(f"[yellow]Skipping {file_path.name}: {file_size_mb:.1f}MB exceeds 10MB limit[/yellow]")
            continue

        # Add to media array
        media_item = {
            "type": "photo",
            "media": f"attach://photo_{i}",
        }

        # Only first item can have caption
        if i == 0 and item.get("caption"):
            media_item["caption"] = truncate_text(item["caption"], config.TELEGRAM_CAPTION_LIMIT)
            media_item["parse_mode"] = "HTML"

        media.append(media_item)
        files[f"photo_{i}"] = open(file_path, "rb")

    if not media:
        console.print("[yellow]No valid photos in album batch[/yellow]")
        return False

    try:
        data = {"chat_id": chat_id, "media": json.dumps(media)}
        telegram_api_request(bot_token, "sendMediaGroup", data, files)
        return True
    except TelegramAPIError as e:
        console.print(f"[red]Failed to send media group: {e}[/red]")
        return False
    finally:
        # Close all file handles
        for f in files.values():
            f.close()


def upload_to_telegram_batch(
    files_to_upload: List[Dict[str, Any]],
    bot_token: str,
    chat_id: str,
    use_albums: bool = True,
) -> TelegramStats:
    """Upload images to Telegram with album support."""
    stats: TelegramStats = {
        "total_images": len(files_to_upload),
        "images_uploaded": 0,
        "albums_sent": 0,
        "failed_uploads": 0,
        "text_captions": 0,
    }

    if use_albums:
        # Process in album batches of 10
        for i in range(0, len(files_to_upload), config.TELEGRAM_MAX_ALBUM_SIZE):
            batch = files_to_upload[i : i + config.TELEGRAM_MAX_ALBUM_SIZE]

            # Filter out files that don't exist or are too large
            valid_batch = []
            for item in batch:
                file_path = item["file_path"]
                if file_path.exists():
                    if validate_file_size(file_path, config.TELEGRAM_PHOTO_SIZE_LIMIT):
                        valid_batch.append(item)
                    else:
                        file_size_mb = file_path.stat().st_size / (1024 * 1024)
                        console.print(f"[yellow]Skipping {file_path.name}: {file_size_mb:.1f}MB exceeds limit[/yellow]")
                        stats["failed_uploads"] += 1
                else:
                    console.print(f"[red]File not found: {file_path}[/red]")
                    stats["failed_uploads"] += 1

            if not valid_batch:
                continue

            if send_telegram_media_group(bot_token, chat_id, valid_batch):
                stats["images_uploaded"] += len(valid_batch)
                stats["albums_sent"] += 1
                # Count captions (only first item in album has caption)
                if valid_batch[0].get("caption"):
                    stats["text_captions"] += 1
            else:
                stats["failed_uploads"] += len(valid_batch)
    else:
        # Send individually
        for item in files_to_upload:
            file_path = item["file_path"]
            caption = item.get("caption", "")

            if send_telegram_photo(bot_token, chat_id, file_path, caption):
                stats["images_uploaded"] += 1
                if caption:
                    stats["text_captions"] += 1
            else:
                stats["failed_uploads"] += 1

    return stats


def retrieve_messages(
    channel_id: str, auth_token: str, base_directory: str = "extracted_media", skip_json_export: bool = False
) -> DownloadStats:
    media_folder = Path(base_directory) / datetime.now().strftime("%Y-%m-%d")
    media_folder.mkdir(parents=True, exist_ok=True)

    stats: DownloadStats = {
        "total_messages": 0,
        "text_messages": 0,
        "media_downloaded": 0,
        "failed_downloads": 0,
    }

    # FIX: Remove unbounded memory growth by using optional JSON export
    # If skip_json_export is True, we don't accumulate messages in memory
    all_messages = [] if not skip_json_export else None
    last_message_id = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading messages...", total=None)

        while True:
            messages = get_channel_messages(channel_id, auth_token, before=last_message_id)
            if not messages:
                break

            for message in messages:
                stats["total_messages"] += 1
                message_id = message.get("id", "")
                last_message_id = message_id

                message_data = {
                    "message_id": message_id,
                    "content": message.get("content", ""),
                    "timestamp": message.get("timestamp", ""),
                    "author": message.get("author", {}),
                    "attachments": [],
                }

                if message_data["content"]:
                    stats["text_messages"] += 1

                for attachment in message.get("attachments", []):
                    url = attachment.get("url")
                    filename = attachment.get("filename")
                    content_type = attachment.get("content_type", "")

                    attachment_data = {
                        "url": url,
                        "filename": filename,
                        "content_type": content_type,
                    }

                    if url and filename and message_id and content_type.startswith("image/"):
                        if download_media(url, media_folder, filename, message_id):
                            stats["media_downloaded"] += 1
                            attachment_data["downloaded"] = True
                        else:
                            stats["failed_downloads"] += 1
                            attachment_data["downloaded"] = False

                    message_data["attachments"].append(attachment_data)

                if all_messages is not None:
                    all_messages.append(message_data)

                progress.update(task, description=f"Downloaded {stats['total_messages']} messages")

    # Only write JSON if we collected messages
    if all_messages is not None:
        json_file_path = media_folder / "all_messages.json"
        with open(json_file_path, "w", encoding="utf-8") as json_file:
            json.dump(all_messages, json_file, indent=2, ensure_ascii=False)

    return stats


def get_channel_type_name(channel_type: int) -> str:
    return {
        ChannelType.GUILD_TEXT: "Text",
        ChannelType.GUILD_VOICE: "Voice",
        ChannelType.GUILD_CATEGORY: "Category",
        ChannelType.GUILD_NEWS: "News",
    }.get(channel_type, "Unknown")


def display_guilds(guilds: List[Dict[str, Any]]) -> None:
    table = Table(title="Discord Servers", show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=4)
    table.add_column("ID", style="dim", width=20)
    table.add_column("Name", style="green")
    table.add_column("Members", justify="right", style="yellow")

    for idx, guild in enumerate(guilds, 1):
        table.add_row(
            str(idx),
            guild.get("id", ""),
            guild.get("name", "Unknown"),
            str(guild.get("member_count", "N/A")),
        )

    console.print(table)


def display_channels(
    channels: List[Dict[str, Any]],
    auth_token: str,
    text_only: bool = False,
    count_images: bool = True,
) -> None:
    if text_only:
        channels = [c for c in channels if c.get("type") in config.TEXT_CHANNEL_TYPES]

    table = Table(title="Channels", show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=4)
    table.add_column("ID", style="dim", width=20)
    table.add_column("Name", style="green")
    table.add_column("Type", style="yellow")
    table.add_column("Images", justify="right", style="red")

    image_counts: Dict[str, int] = {}
    if count_images:
        for channel in channels:
            channel_id = channel.get("id")
            channel_type = channel.get("type")
            if channel_type in config.TEXT_CHANNEL_TYPES:
                image_counts[channel_id] = count_images_in_channel(channel_id, auth_token)

    for idx, channel in enumerate(channels, 1):
        channel_id = channel.get("id")
        channel_type = channel.get("type")
        images = image_counts.get(channel_id, 0) if channel_type in config.TEXT_CHANNEL_TYPES else "N/A"

        table.add_row(
            str(idx),
            channel_id,
            channel.get("name", "Unknown"),
            get_channel_type_name(channel_type),
            str(images),
        )

    console.print(table)


def select_from_list(items: List[Any], prompt: str) -> Optional[int]:
    while True:
        choice = input(f"{prompt} (or 0 to cancel): ").strip()
        if choice == "0":
            return None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(items):
                return idx
            console.print("[red]Invalid selection[/red]")
        except ValueError:
            console.print("[red]Invalid input[/red]")


def select_server(guilds: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    display_guilds(guilds)
    idx = select_from_list(guilds, "Select server number")
    return guilds[idx] if idx is not None else None


def select_channel(channels: List[Dict[str, Any]], auth_token: str, count_images: bool = False) -> Optional[Dict[str, Any]]:
    text_channels = [c for c in channels if c.get("type") in config.TEXT_CHANNEL_TYPES]
    if not text_channels:
        console.print("[red]No text channels found.[/red]")
        return None

    display_channels(channels, auth_token, text_only=True, count_images=count_images)
    idx = select_from_list(text_channels, "Select channel number")
    return text_channels[idx] if idx is not None else None


def select_channels(channels: List[Dict[str, Any]], auth_token: str, count_images: bool = False) -> List[Dict[str, Any]]:
    """Select multiple channels at once."""
    text_channels = [c for c in channels if c.get("type") in config.TEXT_CHANNEL_TYPES]
    if not text_channels:
        console.print("[red]No text channels found.[/red]")
        return []

    display_channels(channels, auth_token, text_only=True, count_images=count_images)

    console.print("\n[cyan]Enter channel numbers separated by commas (e.g., 1,3,5)[/cyan]")
    console.print("Or enter '0' to cancel, 'all' to select all channels")

    while True:
        choice = input("Select channel numbers: ").strip()

        if choice == "0":
            return []

        if choice.lower() == "all":
            return text_channels

        try:
            # Parse comma-separated indices
            indices = []
            for part in choice.split(","):
                idx = int(part.strip()) - 1
                if 0 <= idx < len(text_channels):
                    indices.append(idx)
                else:
                    console.print(f"[yellow]Skipping invalid selection: {part.strip()}[/yellow]")

            if indices:
                selected = [text_channels[i] for i in indices]
                console.print(f"[green]Selected {len(selected)} channel(s): {', '.join([c['name'] for c in selected])}[/green]")
                return selected
            else:
                console.print("[red]No valid channels selected. Try again.[/red]")
        except ValueError:
            console.print("[red]Invalid input. Please enter numbers separated by commas.[/red]")


def confirm_action(prompt: str) -> bool:
    return input(f"\n{prompt} (y/n): ").strip().lower() == "y"


def transfer_images_batch(
    source_channel_id: str,
    target_channel_id: str,
    auth_token: str,
    temp_dir: Path,
    batch_size: int = config.TRANSFER_BATCH_SIZE,
    include_text: bool = False,
) -> TransferStats:
    stats: TransferStats = {
        "total_messages": 0,
        "images_found": 0,
        "images_transferred": 0,
        "failed_transfers": 0,
        "text_messages": 0,
        "text_transferred": 0,
    }

    last_message_id = None
    batch = []
    batch_count = 0
    messages_with_text_sent = set()  # Track which messages have had text sent

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Transferring...", total=None)

        while True:
            messages = get_channel_messages(source_channel_id, auth_token, before=last_message_id)
            if not messages:
                break

            for message in messages:
                stats["total_messages"] += 1
                last_message_id = message.get("id")
                message_id = message.get("id", "")
                content = message.get("content", "")

                if content and include_text:
                    stats["text_messages"] += 1

                for attachment in message.get("attachments", []):
                    url = attachment.get("url")
                    filename = attachment.get("filename")
                    content_type = attachment.get("content_type", "")

                    if url and filename and message_id and content_type.startswith("image/"):
                        stats["images_found"] += 1

                        # Only include text for the first image from each message
                        should_include_text = include_text and content and message_id not in messages_with_text_sent
                        if should_include_text:
                            messages_with_text_sent.add(message_id)

                        batch.append({
                            "url": url,
                            "filename": filename,
                            "message_id": message_id,
                            "content": content if should_include_text else None,
                        })

                if len(batch) >= batch_size:
                    batch_count += 1
                    progress.update(task, description=f"Processing batch {batch_count} ({stats['images_transferred']} images, {stats['text_transferred']} text)")

                    for item in batch:
                        file_extension = Path(item["filename"]).suffix
                        safe_filename = f"{item['message_id']}{file_extension}"
                        file_path = temp_dir / safe_filename

                        if download_media(item["url"], temp_dir, item["filename"], item["message_id"]):
                            message_content = item["content"] if item["content"] else ""
                            if upload_image_with_text(file_path, target_channel_id, auth_token, message_content):
                                stats["images_transferred"] += 1
                                if item["content"]:
                                    stats["text_transferred"] += 1
                            else:
                                stats["failed_transfers"] += 1

                            file_path.unlink()

                    batch = []

                progress.update(task, description=f"Processing batch {batch_count + 1} ({stats['images_transferred']} images, {stats['text_transferred']} text)")

        if batch:
            batch_count += 1
            progress.update(task, description=f"Processing final batch {batch_count} ({stats['images_transferred']} images, {stats['text_transferred']} text)")

            for item in batch:
                file_extension = Path(item["filename"]).suffix
                safe_filename = f"{item['message_id']}{file_extension}"
                file_path = temp_dir / safe_filename

                if download_media(item["url"], temp_dir, item["filename"], item["message_id"]):
                    message_content = item["content"] if item["content"] else ""
                    if upload_image_with_text(file_path, target_channel_id, auth_token, message_content):
                        stats["images_transferred"] += 1
                        if item["content"]:
                            stats["text_transferred"] += 1
                    else:
                        stats["failed_transfers"] += 1

                    file_path.unlink()

        progress.update(task, description=f"Transfer complete! ({stats['images_transferred']} images, {stats['text_transferred']} text)")

    return stats


# ==================== Telegram Transfer Functions ====================


def transfer_discord_to_telegram_batch(
    source_channel_id: str,
    bot_token: str,
    chat_id: str,
    auth_token: str,
    temp_dir: Path,
    batch_size: int = config.TRANSFER_BATCH_SIZE,
    include_text: bool = False,
    use_albums: bool = True,
) -> TransferStats:
    """Transfer images from Discord channel to Telegram with batch processing."""
    stats: TransferStats = {
        "total_messages": 0,
        "images_found": 0,
        "images_transferred": 0,
        "failed_transfers": 0,
        "text_messages": 0,
        "text_transferred": 0,
    }

    last_message_id = None
    image_batch = []  # For Telegram upload
    messages_with_text_sent = set()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Transferring Discord → Telegram...", total=None)

        while True:
            messages = get_channel_messages(source_channel_id, auth_token, before=last_message_id)
            if not messages:
                break

            for message in messages:
                stats["total_messages"] += 1
                last_message_id = message.get("id")
                message_id = message.get("id", "")
                content = message.get("content", "")

                if content and include_text:
                    stats["text_messages"] += 1

                for attachment in message.get("attachments", []):
                    url = attachment.get("url")
                    filename = attachment.get("filename")
                    content_type = attachment.get("content_type", "")

                    if url and filename and message_id and content_type.startswith("image/"):
                        stats["images_found"] += 1

                        # Determine caption
                        should_include_text = include_text and content and message_id not in messages_with_text_sent
                        if should_include_text:
                            messages_with_text_sent.add(message_id)
                            caption = content
                        else:
                            caption = ""

                        # Download to temp
                        file_extension = Path(filename).suffix
                        safe_filename = f"{message_id}{file_extension}"
                        file_path = temp_dir / safe_filename

                        if download_media(url, temp_dir, filename, message_id):
                            image_batch.append({
                                "file_path": file_path,
                                "caption": caption,
                            })

                            # Process batch when full
                            if use_albums and len(image_batch) >= config.TELEGRAM_MAX_ALBUM_SIZE:
                                tg_stats = upload_to_telegram_batch(image_batch, bot_token, chat_id, use_albums=True)
                                stats["images_transferred"] += tg_stats["images_uploaded"]
                                stats["failed_transfers"] += tg_stats["failed_uploads"]
                                stats["text_transferred"] += tg_stats["text_captions"]

                                # Cleanup
                                for item in image_batch:
                                    if item["file_path"].exists():
                                        item["file_path"].unlink()

                                image_batch = []
                                progress.update(task, description=f"Transferred {stats['images_transferred']} images to Telegram")

                        else:
                            stats["failed_transfers"] += 1

        # Process remaining images
        if image_batch:
            tg_stats = upload_to_telegram_batch(image_batch, bot_token, chat_id, use_albums=use_albums)
            stats["images_transferred"] += tg_stats["images_uploaded"]
            stats["failed_transfers"] += tg_stats["failed_uploads"]
            stats["text_transferred"] += tg_stats["text_captions"]

            # Cleanup
            for item in image_batch:
                if item["file_path"].exists():
                    item["file_path"].unlink()

        progress.update(task, description=f"Transfer complete! ({stats['images_transferred']} images)")

    return stats


def telegram_upload_from_local(
    source_dir: str,
    bot_token: str,
    chat_id: str,
    use_albums: bool = True,
) -> TelegramStats:
    """Upload images from local directory to Telegram."""
    media_folder = Path(source_dir)
    if not media_folder.exists():
        console.print(f"[red]Directory not found: {source_dir}[/red]")
        return {
            "total_images": 0,
            "images_uploaded": 0,
            "albums_sent": 0,
            "failed_uploads": 0,
            "text_captions": 0,
        }

    # Collect image files
    image_files = []
    for ext in config.IMAGE_EXTENSIONS:
        image_files.extend(media_folder.glob(f"*{ext}"))
        image_files.extend(media_folder.glob(f"*{ext.upper()}"))

    # Remove duplicates
    image_files = list(set(image_files))

    console.print(f"\n[bold yellow]Found {len(image_files)} images to upload to Telegram[/bold yellow]")

    if not image_files:
        return {
            "total_images": 0,
            "images_uploaded": 0,
            "albums_sent": 0,
            "failed_uploads": 0,
            "text_captions": 0,
        }

    # Prepare upload items
    files_to_upload = [{"file_path": f, "caption": ""} for f in image_files]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Uploading to Telegram...", total=len(files_to_upload))

        if use_albums:
            total_uploaded = 0
            for i in range(0, len(files_to_upload), config.TELEGRAM_MAX_ALBUM_SIZE):
                batch = files_to_upload[i : i + config.TELEGRAM_MAX_ALBUM_SIZE]
                tg_stats = upload_to_telegram_batch(batch, bot_token, chat_id, use_albums=True)
                total_uploaded += tg_stats["images_uploaded"]
                progress.update(task, completed=total_uploaded)

    # Final stats
    stats = upload_to_telegram_batch(files_to_upload, bot_token, chat_id, use_albums)

    return stats


# ==================== Menu Functions ====================


def list_servers_menu(auth_token: str, media_base_dir: str) -> None:
    guilds = get_guilds(auth_token)
    if not guilds:
        console.print("[red]No guilds found. Check your auth token.[/red]")
        return

    while True:
        console.print("\n[cyan]Options:[/cyan]")
        console.print(f" [1-{len(guilds)}] Select server to view channels")
        console.print(" [0] Back to main menu\n")

        selected_guild = select_server(guilds)
        if not selected_guild:
            break

        console.print(f"\n[green]Selected: {selected_guild['name']}[/green]\n")

        channels = get_channels(selected_guild["id"], auth_token)
        selected_channel = select_channel(channels, auth_token, count_images=False)

        if selected_channel:
            console.print(f"\n[green]Selected: {selected_channel['name']}[/green]")
            console.print(f"Channel ID: {selected_channel['id']}")

            while True:
                console.print("\n[cyan]Options:[/cyan]")
                console.print(" [1] Transfer images from local directory")
                console.print(" [2] Transfer images from another server")
                console.print(" [3] Transfer images to Telegram")
                console.print(" [0] Back to server list\n")

                choice = input("Select an option: ").strip()

                if choice == "0":
                    break
                elif choice == "1":
                    _handle_local_transfer(selected_channel["id"], auth_token, media_base_dir)
                elif choice == "2":
                    _handle_server_transfer(selected_channel["id"], auth_token, media_base_dir)
                elif choice == "3":
                    _handle_discord_to_telegram(selected_channel["id"], auth_token, media_base_dir)
                else:
                    console.print("[red]Invalid option[/red]")


def _handle_discord_to_telegram(channel_id: str, auth_token: str, media_base_dir: str) -> None:
    """Handle Discord to Telegram transfer."""
    try:
        bot_token = get_env_var("TELEGRAM_BOT_TOKEN")
        chat_id = get_env_var("TELEGRAM_CHAT_ID")
    except ValueError as e:
        console.print(f"[red]Telegram configuration error: {e}[/red]")
        console.print("[yellow]Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your .env file[/yellow]")
        input("\nPress Enter to continue...")
        return

    # Verify Telegram chat
    console.print("\n[cyan]Verifying Telegram chat...[/cyan]")
    if not verify_telegram_chat(bot_token, chat_id):
        input("\nPress Enter to continue...")
        return

    include_text = confirm_action("Include text content as photo captions?")
    use_albums = confirm_action("Send as albums (groups of up to 10 photos)?")

    if confirm_action("Start transfer?"):
        temp_dir = Path(media_base_dir) / "temp_telegram_transfer"
        temp_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"\n[cyan]Transferring Discord → Telegram in batches...[/cyan]")

        stats = transfer_discord_to_telegram_batch(
            channel_id,
            bot_token,
            chat_id,
            auth_token,
            temp_dir,
            include_text=include_text,
            use_albums=use_albums,
        )

        console.print(f"\n[green]Transfer complete![/green]")
        console.print(f"Total messages processed: {stats['total_messages']}")
        console.print(f"Images found: {stats['images_found']}")
        console.print(f"Images transferred: {stats['images_transferred']}")
        if include_text:
            console.print(f"Text captions sent: {stats['text_transferred']}")
        console.print(f"Failed transfers: {stats['failed_transfers']}")

        _cleanup_temp_dir(temp_dir)
        input("\nPress Enter to continue...")


def _handle_local_telegram_upload(media_base_dir: str) -> None:
    """Handle local directory to Telegram upload."""
    try:
        bot_token = get_env_var("TELEGRAM_BOT_TOKEN")
        chat_id = get_env_var("TELEGRAM_CHAT_ID")
    except ValueError as e:
        console.print(f"[red]Telegram configuration error: {e}[/red]")
        console.print("[yellow]Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your .env file[/yellow]")
        input("\nPress Enter to continue...")
        return

    source_dir = input("Enter source directory (default: extracted_media): ").strip()
    if not source_dir:
        source_dir = media_base_dir

    # Verify Telegram chat
    console.print("\n[cyan]Verifying Telegram chat...[/cyan]")
    if not verify_telegram_chat(bot_token, chat_id):
        input("\nPress Enter to continue...")
        return

    use_albums = confirm_action("Send as albums (groups of up to 10 photos)?")

    if confirm_action("Start upload?"):
        stats = telegram_upload_from_local(source_dir, bot_token, chat_id, use_albums)

        console.print(f"\n[green]Upload complete![/green]")
        console.print(f"Total images: {stats['total_images']}")
        console.print(f"Images uploaded: {stats['images_uploaded']}")
        console.print(f"Albums sent: {stats['albums_sent']}")
        console.print(f"Failed uploads: {stats['failed_uploads']}")

        input("\nPress Enter to continue...")


def _handle_local_transfer(channel_id: str, auth_token: str, media_base_dir: str) -> None:
    source_dir = input("Enter source directory (default: extracted_media): ").strip()
    if not source_dir:
        source_dir = media_base_dir

    media_folder = Path(source_dir)
    if not media_folder.exists():
        console.print(f"[red]Directory not found: {source_dir}[/red]")
        input("\nPress Enter to continue...")
        return

    image_files = []
    for ext in config.IMAGE_EXTENSIONS:
        image_files.extend(media_folder.glob(f"*{ext}"))
        image_files.extend(media_folder.glob(f"*{ext.upper()}"))
    image_files = list(set(image_files))

    console.print(f"\n[bold yellow]Found {len(image_files)} images to upload[/bold yellow]")

    if confirm_action("Start upload?"):
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Uploading images...", total=len(image_files))

            uploaded = 0
            for image_file in image_files:
                if image_file.suffix.lower() in config.IMAGE_EXTENSIONS:
                    if upload_image_to_channel(image_file, channel_id, auth_token):
                        uploaded += 1
                    progress.update(task, advance=1)

        console.print(f"\n[green]Successfully uploaded {uploaded} images[/green]")
        input("\nPress Enter to continue...")


def _handle_server_transfer(channel_id: str, auth_token: str, media_base_dir: str) -> None:
    console.print("\n[cyan]Select source server and channel[/cyan]")

    source_guilds = get_guilds(auth_token)
    source_guild = select_server(source_guilds)
    if not source_guild:
        return

    console.print(f"\n[green]Source server: {source_guild['name']}[/green]\n")

    source_channels = get_channels(source_guild["id"], auth_token)
    source_channel = select_channel(source_channels, auth_token, count_images=False)

    if not source_channel:
        return

    console.print(f"\n[green]Source channel: {source_channel['name']}[/green]")
    console.print(f"\n[bold yellow]Transferring from {source_channel['name']} to selected channel[/bold yellow]")

    include_text = confirm_action("Include text content with images?")

    if confirm_action("Start transfer?"):
        temp_dir = Path(media_base_dir) / "temp_transfer"
        temp_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"\n[cyan]Transferring images in batches of {config.TRANSFER_BATCH_SIZE} to save disk space...[/cyan]")
        console.print(f"[yellow]Maximum disk usage: ~{config.TRANSFER_BATCH_SIZE} images at a time[/yellow]\n")

        stats = transfer_images_batch(
            source_channel["id"],
            channel_id,
            auth_token,
            temp_dir,
            include_text=include_text,
        )

        console.print(f"\n[green]Transfer complete![/green]")
        console.print(f"Total messages processed: {stats['total_messages']}")
        console.print(f"Images found: {stats['images_found']}")
        console.print(f"Images transferred: {stats['images_transferred']}")
        if include_text:
            console.print(f"Text messages found: {stats['text_messages']}")
            console.print(f"Text messages transferred: {stats['text_transferred']}")
        console.print(f"Failed transfers: {stats['failed_transfers']}")

        _cleanup_temp_dir(temp_dir)
        input("\nPress Enter to continue...")


def download_menu(auth_token: str, media_base_dir: str) -> None:
    guilds = get_guilds(auth_token)
    if not guilds:
        console.print("[red]No guilds found. Check your auth token.[/red]")
        return

    console.print("\n[cyan]Download Options:[/cyan]")
    console.print(" [1] Download from specific channel")
    console.print(" [2] Download from multiple channels")
    console.print(" [3] Download from whole server (all channels)")
    console.print(" [0] Back to main menu\n")

    download_choice = input("Select download type: ").strip()

    if download_choice == "0":
        return
    elif download_choice == "1":
        _download_from_channel(guilds, auth_token, media_base_dir)
    elif download_choice == "2":
        _download_from_multiple_channels(guilds, auth_token, media_base_dir)
    elif download_choice == "3":
        _download_from_server(guilds, auth_token, media_base_dir)
    else:
        console.print("[red]Invalid option[/red]")


def _download_from_channel(guilds: List[Dict[str, Any]], auth_token: str, media_base_dir: str) -> None:
    selected_guild = select_server(guilds)
    if not selected_guild:
        return

    console.print(f"\n[green]Selected: {selected_guild['name']}[/green]\n")

    channels = get_channels(selected_guild["id"], auth_token)
    selected_channel = select_channel(channels, auth_token, count_images=False)

    if selected_channel:
        console.print(f"\n[green]Selected: {selected_channel['name']}[/green]")

        if confirm_action("Start download?"):
            stats = retrieve_messages(selected_channel["id"], auth_token, media_base_dir)
            console.print(f"\n[green]Download complete![/green]")
            console.print(f"Total messages: {stats['total_messages']}")
            console.print(f"Text messages: {stats['text_messages']}")
            console.print(f"Images downloaded: {stats['media_downloaded']}")
            console.print(f"Failed downloads: {stats['failed_downloads']}")
            input("\nPress Enter to continue...")


def _download_from_multiple_channels(guilds: List[Dict[str, Any]], auth_token: str, media_base_dir: str) -> None:
    """Download from multiple selected channels."""
    selected_guild = select_server(guilds)
    if not selected_guild:
        return

    console.print(f"\n[green]Selected: {selected_guild['name']}[/green]\n")

    channels = get_channels(selected_guild["id"], auth_token)
    selected_channels = select_channels(channels, auth_token, count_images=False)

    if not selected_channels:
        console.print("[yellow]No channels selected.[/yellow]")
        return

    console.print(f"\n[bold yellow]Selected {len(selected_channels)} channel(s)[/bold yellow]")

    if confirm_action("Start download?"):
        total_stats = {
            "total_messages": 0,
            "text_messages": 0,
            "media_downloaded": 0,
            "failed_downloads": 0,
        }

        for idx, channel in enumerate(selected_channels, 1):
            console.print(f"\n[cyan]Processing channel {idx}/{len(selected_channels)}: {channel['name']}[/cyan]")

            stats = retrieve_messages(channel["id"], auth_token, media_base_dir)

            total_stats["total_messages"] += stats["total_messages"]
            total_stats["text_messages"] += stats["text_messages"]
            total_stats["media_downloaded"] += stats["media_downloaded"]
            total_stats["failed_downloads"] += stats["failed_downloads"]

            console.print(f"  Messages: {stats['total_messages']}, Images: {stats['media_downloaded']}")

        console.print(f"\n[green]Multi-channel download complete![/green]")
        console.print(f"Total messages: {total_stats['total_messages']}")
        console.print(f"Total text messages: {total_stats['text_messages']}")
        console.print(f"Total images downloaded: {total_stats['media_downloaded']}")
        console.print(f"Total failed downloads: {total_stats['failed_downloads']}")
        input("\nPress Enter to continue...")


def _download_from_server(guilds: List[Dict[str, Any]], auth_token: str, media_base_dir: str) -> None:
    selected_guild = select_server(guilds)
    if not selected_guild:
        return

    console.print(f"\n[green]Selected: {selected_guild['name']}[/green]\n")

    channels = get_channels(selected_guild["id"], auth_token)
    text_channels = [c for c in channels if c.get("type") in config.TEXT_CHANNEL_TYPES]

    if not text_channels:
        console.print("[red]No text channels found.[/red]")
        return

    console.print(f"\n[bold yellow]Found {len(text_channels)} text channels[/bold yellow]")

    if not confirm_action(f"Download from all {len(text_channels)} channels?"):
        return

    total_stats = {
        "total_messages": 0,
        "text_messages": 0,
        "media_downloaded": 0,
        "failed_downloads": 0,
    }

    for idx, channel in enumerate(text_channels, 1):
        console.print(f"\n[cyan]Processing channel {idx}/{len(text_channels)}: {channel['name']}[/cyan]")
        stats = retrieve_messages(channel["id"], auth_token, media_base_dir)

        total_stats["total_messages"] += stats["total_messages"]
        total_stats["text_messages"] += stats["text_messages"]
        total_stats["media_downloaded"] += stats["media_downloaded"]
        total_stats["failed_downloads"] += stats["failed_downloads"]

        console.print(f" Messages: {stats['total_messages']}, Images: {stats['media_downloaded']}")

    console.print(f"\n[green]Server download complete![/green]")
    console.print(f"Total messages: {total_stats['total_messages']}")
    console.print(f"Total text messages: {total_stats['text_messages']}")
    console.print(f"Total images downloaded: {total_stats['media_downloaded']}")
    console.print(f"Total failed downloads: {total_stats['failed_downloads']}")
    input("\nPress Enter to continue...")


def transfer_menu(auth_token: str, media_base_dir: str) -> None:
    console.print("\n[cyan]Transfer Options:[/cyan]")
    console.print(" [1] Transfer from local directory to Discord")
    console.print(" [2] Transfer from Discord server to Discord server")
    console.print(" [3] Transfer whole server to another server")
    console.print(" [4] Transfer from Discord to Telegram ← NEW")
    console.print(" [5] Transfer local files to Telegram ← NEW")
    console.print(" [0] Back to main menu\n")

    choice = input("Select transfer type: ").strip()

    if choice == "0":
        return
    elif choice == "1":
        _transfer_from_local(auth_token, media_base_dir)
    elif choice == "2":
        _transfer_from_server(auth_token, media_base_dir)
    elif choice == "3":
        _transfer_whole_server(auth_token, media_base_dir)
    elif choice == "4":
        _transfer_discord_to_telegram_menu(auth_token, media_base_dir)
    elif choice == "5":
        _handle_local_telegram_upload(media_base_dir)
    else:
        console.print("[red]Invalid option[/red]")


def _transfer_discord_to_telegram_menu(auth_token: str, media_base_dir: str) -> None:
    """Menu for Discord to Telegram transfer."""
    try:
        bot_token = get_env_var("TELEGRAM_BOT_TOKEN")
        chat_id = get_env_var("TELEGRAM_CHAT_ID")
    except ValueError as e:
        console.print(f"[red]Telegram configuration error: {e}[/red]")
        console.print("[yellow]Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your .env file[/yellow]")
        input("\nPress Enter to continue...")
        return

    console.print("\n[cyan]Select Discord source server and channel[/cyan]")

    guilds = get_guilds(auth_token)
    if not guilds:
        console.print("[red]No guilds found. Check your auth token.[/red]")
        return

    source_guild = select_server(guilds)
    if not source_guild:
        return

    console.print(f"\n[green]Source server: {source_guild['name']}[/green]\n")

    channels = get_channels(source_guild["id"], auth_token)
    source_channel = select_channel(channels, auth_token, count_images=False)

    if not source_channel:
        return

    # Verify Telegram chat
    console.print("\n[cyan]Verifying Telegram chat...[/cyan]")
    if not verify_telegram_chat(bot_token, chat_id):
        input("\nPress Enter to continue...")
        return

    console.print(f"\n[green]Source channel: {source_channel['name']}[/green]")
    console.print(f"\n[bold yellow]Transferring from Discord to Telegram[/bold yellow]")

    include_text = confirm_action("Include text content as photo captions?")
    use_albums = confirm_action("Send as albums (groups of up to 10 photos)?")

    if confirm_action("Start transfer?"):
        temp_dir = Path(media_base_dir) / "temp_telegram_transfer"
        temp_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"\n[cyan]Transferring Discord → Telegram in batches...[/cyan]")

        stats = transfer_discord_to_telegram_batch(
            source_channel["id"],
            bot_token,
            chat_id,
            auth_token,
            temp_dir,
            include_text=include_text,
            use_albums=use_albums,
        )

        console.print(f"\n[green]Transfer complete![/green]")
        console.print(f"Total messages processed: {stats['total_messages']}")
        console.print(f"Images found: {stats['images_found']}")
        console.print(f"Images transferred: {stats['images_transferred']}")
        if include_text:
            console.print(f"Text captions sent: {stats['text_transferred']}")
        console.print(f"Failed transfers: {stats['failed_transfers']}")

        _cleanup_temp_dir(temp_dir)
        input("\nPress Enter to continue...")


def _transfer_from_local(auth_token: str, media_base_dir: str) -> None:
    source_dir = input("Enter source directory (default: extracted_media): ").strip()
    if not source_dir:
        source_dir = media_base_dir

    guilds = get_guilds(auth_token)
    if not guilds:
        console.print("[red]No guilds found. Check your auth token.[/red]")
        return

    selected_guild = select_server(guilds)
    if not selected_guild:
        return

    console.print(f"\n[green]Selected: {selected_guild['name']}[/green]\n")

    channels = get_channels(selected_guild["id"], auth_token)
    selected_channel = select_channel(channels, auth_token, count_images=False)

    if selected_channel:
        console.print(f"\n[green]Selected: {selected_channel['name']}[/green]")

    media_folder = Path(source_dir)
    if not media_folder.exists():
        console.print(f"[red]Directory not found: {source_dir}[/red]")
        input("\nPress Enter to continue...")
        return

    image_files = []
    for ext in config.IMAGE_EXTENSIONS:
        image_files.extend(media_folder.glob(f"*{ext}"))
        image_files.extend(media_folder.glob(f"*{ext.upper()}"))
    image_files = list(set(image_files))

    console.print(f"\n[bold yellow]Found {len(image_files)} images to upload[/bold yellow]")

    if confirm_action("Start upload?"):
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Uploading images...", total=len(image_files))

            uploaded = 0
            for image_file in image_files:
                if image_file.suffix.lower() in config.IMAGE_EXTENSIONS:
                    if upload_image_to_channel(image_file, selected_channel["id"], auth_token):
                        uploaded += 1
                    progress.update(task, advance=1)

        console.print(f"\n[green]Successfully uploaded {uploaded} images[/green]")
        input("\nPress Enter to continue...")


def _transfer_from_server(auth_token: str, media_base_dir: str) -> None:
    console.print("\n[cyan]Select source server and channel[/cyan]")

    source_guilds = get_guilds(auth_token)
    if not source_guilds:
        console.print("[red]No guilds found. Check your auth token.[/red]")
        return

    source_guild = select_server(source_guilds)
    if not source_guild:
        return

    console.print(f"\n[green]Source server: {source_guild['name']}[/green]\n")

    source_channels = get_channels(source_guild["id"], auth_token)
    source_channel = select_channel(source_channels, auth_token, count_images=False)

    if not source_channel:
        return

    console.print(f"\n[green]Source channel: {source_channel['name']}[/green]")

    console.print("\n[cyan]Select target server and channel[/cyan]")

    target_guild = select_server(source_guilds)
    if not target_guild:
        return

    console.print(f"\n[green]Target server: {target_guild['name']}[/green]\n")

    target_channels = get_channels(target_guild["id"], auth_token)
    target_channel = select_channel(target_channels, auth_token, count_images=False)

    if not target_channel:
        return

    console.print(f"\n[green]Target channel: {target_channel['name']}[/green]")
    console.print(f"\n[bold yellow]Transferring from {source_channel['name']} to {target_channel['name']}[/bold yellow]")

    include_text = confirm_action("Include text content with images?")

    if confirm_action("Start transfer?"):
        temp_dir = Path(media_base_dir) / "temp_transfer"
        temp_dir.mkdir(parents=True, exist_ok=True)

        console.print(f"\n[cyan]Transferring images in batches of {config.TRANSFER_BATCH_SIZE} to save disk space...[/cyan]")
        console.print(f"[yellow]Maximum disk usage: ~{config.TRANSFER_BATCH_SIZE} images at a time[/yellow]\n")

        stats = transfer_images_batch(
            source_channel["id"],
            target_channel["id"],
            auth_token,
            temp_dir,
            include_text=include_text,
        )

        console.print(f"\n[green]Transfer complete![/green]")
        console.print(f"Total messages processed: {stats['total_messages']}")
        console.print(f"Images found: {stats['images_found']}")
        console.print(f"Images transferred: {stats['images_transferred']}")
        if include_text:
            console.print(f"Text messages found: {stats['text_messages']}")
            console.print(f"Text messages transferred: {stats['text_transferred']}")
        console.print(f"Failed transfers: {stats['failed_transfers']}")

        _cleanup_temp_dir(temp_dir)
        input("\nPress Enter to continue...")


def _transfer_whole_server(auth_token: str, media_base_dir: str) -> None:
    console.print("\n[cyan]Select source server[/cyan]")

    source_guilds = get_guilds(auth_token)
    if not source_guilds:
        console.print("[red]No guilds found. Check your auth token.[/red]")
        return

    source_guild = select_server(source_guilds)
    if not source_guild:
        return

    console.print(f"\n[green]Source server: {source_guild['name']}[/green]\n")

    source_channels = get_channels(source_guild["id"], auth_token)
    source_text_channels = [c for c in source_channels if c.get("type") in config.TEXT_CHANNEL_TYPES]

    if not source_text_channels:
        console.print("[red]No text channels found in source server.[/red]")
        return

    console.print(f"\n[bold yellow]Found {len(source_text_channels)} text channels in source server[/bold yellow]")

    console.print("\n[cyan]Select target server[/cyan]")
    target_guild = select_server(source_guilds)
    if not target_guild:
        return

    console.print(f"\n[green]Target server: {target_guild['name']}[/green]\n")

    console.print("\n[cyan]Transfer Options:[/cyan]")
    console.print(" [1] Send all images to one channel")
    console.print(" [2] Create category and send each channel's images to separate channels")
    console.print(" [0] Cancel\n")

    transfer_option = input("Select transfer option: ").strip()

    if transfer_option == "0":
        return
    elif transfer_option == "1":
        _transfer_to_single_channel(source_text_channels, target_guild, auth_token, media_base_dir)
    elif transfer_option == "2":
        _transfer_to_category(source_text_channels, target_guild, auth_token, media_base_dir)
    else:
        console.print("[red]Invalid option[/red]")


def _transfer_to_single_channel(
    source_text_channels: List[Dict[str, Any]],
    target_guild: Dict[str, Any],
    auth_token: str,
    media_base_dir: str,
) -> None:
    target_channels = get_channels(target_guild["id"], auth_token)
    target_channel = select_channel(target_channels, auth_token, count_images=False)

    if not target_channel:
        return

    console.print(f"\n[green]Target channel: {target_channel['name']}[/green]")
    console.print(f"\n[bold yellow]Transferring all images from {len(source_text_channels)} channels to {target_channel['name']}[/bold yellow]")

    if confirm_action("Start transfer?"):
        temp_dir = Path(media_base_dir) / "temp_transfer"
        temp_dir.mkdir(parents=True, exist_ok=True)

        total_stats: TransferStats = {
            "total_messages": 0,
            "images_found": 0,
            "images_transferred": 0,
            "failed_transfers": 0,
            "text_messages": 0,
            "text_transferred": 0,
        }

        for idx, source_channel in enumerate(source_text_channels, 1):
            console.print(f"\n[cyan]Processing channel {idx}/{len(source_text_channels)}: {source_channel['name']}[/cyan]")

            stats = transfer_images_batch(
                source_channel["id"],
                target_channel["id"],
                auth_token,
                temp_dir,
            )

            total_stats["total_messages"] += stats["total_messages"]
            total_stats["images_found"] += stats["images_found"]
            total_stats["images_transferred"] += stats["images_transferred"]
            total_stats["failed_transfers"] += stats["failed_transfers"]
            total_stats["text_messages"] += stats["text_messages"]
            total_stats["text_transferred"] += stats["text_transferred"]

            console.print(f" Images transferred: {stats['images_transferred']}")

        console.print(f"\n[green]Server transfer complete![/green]")
        console.print(f"Total messages processed: {total_stats['total_messages']}")
        console.print(f"Total images found: {total_stats['images_found']}")
        console.print(f"Total images transferred: {total_stats['images_transferred']}")
        console.print(f"Total failed transfers: {total_stats['failed_transfers']}")

        _cleanup_temp_dir(temp_dir)
        input("\nPress Enter to continue...")


def _transfer_to_category(
    source_text_channels: List[Dict[str, Any]],
    target_guild: Dict[str, Any],
    auth_token: str,
    media_base_dir: str,
) -> None:
    category_name = input("Enter category name: ").strip()
    if not category_name:
        console.print("[red]Category name is required[/red]")
        return

    try:
        category_data = make_request(
            f"{config.API_BASE_URL}/guilds/{target_guild['id']}/channels",
            method="POST",
            headers=get_headers(auth_token),
            json_data={
                "name": category_name,
                "type": ChannelType.GUILD_CATEGORY,
            },
        )
        category_id = category_data.get("id")
        console.print(f"\n[green]Created category: {category_name}[/green]")
    except DiscordAPIError as e:
        console.print(f"[red]Failed to create category: {e}[/red]")
        return

    if confirm_action(f"Create {len(source_text_channels)} channels and transfer images?"):
        temp_dir = Path(media_base_dir) / "temp_transfer"
        temp_dir.mkdir(parents=True, exist_ok=True)

        total_stats: TransferStats = {
            "total_messages": 0,
            "images_found": 0,
            "images_transferred": 0,
            "failed_transfers": 0,
            "text_messages": 0,
            "text_transferred": 0,
        }

        for idx, source_channel in enumerate(source_text_channels, 1):
            console.print(f"\n[cyan]Processing channel {idx}/{len(source_text_channels)}: {source_channel['name']}[/cyan]")

            try:
                channel_data = make_request(
                    f"{config.API_BASE_URL}/guilds/{target_guild['id']}/channels",
                    method="POST",
                    headers=get_headers(auth_token),
                    json_data={
                        "name": source_channel["name"],
                        "type": ChannelType.GUILD_TEXT,
                        "parent_id": category_id,
                    },
                )
                target_channel_id = channel_data.get("id")
                console.print(f" Created channel: {source_channel['name']}")
            except DiscordAPIError as e:
                console.print(f" [red]Failed to create channel: {e}[/red]")
                continue

            stats = transfer_images_batch(
                source_channel["id"],
                target_channel_id,
                auth_token,
                temp_dir,
            )

            total_stats["total_messages"] += stats["total_messages"]
            total_stats["images_found"] += stats["images_found"]
            total_stats["images_transferred"] += stats["images_transferred"]
            total_stats["failed_transfers"] += stats["failed_transfers"]
            total_stats["text_messages"] += stats["text_messages"]
            total_stats["text_transferred"] += stats["text_transferred"]

            console.print(f" Images transferred: {stats['images_transferred']}")

        console.print(f"\n[green]Server transfer complete![/green]")
        console.print(f"Total messages processed: {total_stats['total_messages']}")
        console.print(f"Total images found: {total_stats['images_found']}")
        console.print(f"Total images transferred: {total_stats['images_transferred']}")
        console.print(f"Total failed transfers: {total_stats['failed_transfers']}")

        _cleanup_temp_dir(temp_dir)
        input("\nPress Enter to continue...")


def _cleanup_temp_dir(temp_dir: Path) -> None:
    if temp_dir.exists():
        for file in temp_dir.glob("*.*"):
            file.unlink()
        temp_dir.rmdir()
        console.print("[green]Temporary files cleaned up[/green]")


def interactive_menu(auth_token: str, media_base_dir: str) -> None:
    if not sys.stdin.isatty():
        console.print("[red]Error: Interactive mode requires a terminal (TTY).[/red]")
        console.print("[yellow]Please run this command in an interactive terminal.[/yellow]")
        console.print("\n[cyan]Alternative: Use command-line arguments:[/cyan]")
        console.print(" uv run main.py --help")
        return

    menu_options = {
        "1": ("List Servers", list_servers_menu),
        "2": ("Download Images from Channel", download_menu),
        "3": ("Transfer Images", transfer_menu),
    }

    while True:
        console.print("\n")
        console.print(Panel.fit("[bold green]Discord Art Gallery Manager[/bold green]", padding=1))
        console.print("[cyan]Main Menu:[/cyan]")
        for key, (name, _) in menu_options.items():
            console.print(f" [{key}] {name}")
        console.print(" [0] Exit")
        console.print("\n")

        choice = input("Select an option: ").strip()

        if choice == "0":
            console.print("[yellow]Goodbye![/yellow]")
            break

        if choice in menu_options:
            _, handler = menu_options[choice]
            handler(auth_token, media_base_dir)
        else:
            console.print("[red]Invalid option[/red]")


def list_servers(auth_token: str) -> None:
    console.print(Panel.fit("[bold green]Discord Art Gallery Manager[/bold green]", padding=1))
    guilds = get_guilds(auth_token)
    if not guilds:
        console.print("[red]No guilds found. Check your auth token.[/red]")
        return
    display_guilds(guilds)


def list_channels(guild_id: str, auth_token: str) -> None:
    channels = get_channels(guild_id, auth_token)
    if not channels:
        console.print("[red]No channels found.[/red]")
        return
    display_channels(channels, auth_token, count_images=False)


def download_images(channel_id: str, auth_token: str, base_directory: str) -> None:
    console.print(f"\n[cyan]Downloading images from channel: {channel_id}[/cyan]")
    stats = retrieve_messages(channel_id, auth_token, base_directory)
    console.print(f"[green]Download complete![/green]")
    console.print(f"Total messages: {stats['total_messages']}")
    console.print(f"Images downloaded: {stats['media_downloaded']}")
    console.print(f"Failed downloads: {stats['failed_downloads']}")


def transfer_images(source_dir: str, target_channel_id: str, auth_token: str) -> None:
    media_folder = Path(source_dir)
    if not media_folder.exists():
        console.print(f"[red]Directory not found: {source_dir}[/red]")
        return

    image_files = []
    for ext in config.IMAGE_EXTENSIONS:
        image_files.extend(media_folder.glob(f"*{ext}"))
        image_files.extend(media_folder.glob(f"*{ext.upper()}"))
    image_files = list(set(image_files))

    console.print(f"\n[bold yellow]Found {len(image_files)} images to upload[/bold yellow]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Uploading images...", total=len(image_files))

        uploaded = 0
        for image_file in image_files:
            if image_file.suffix.lower() in config.IMAGE_EXTENSIONS:
                if upload_image_to_channel(image_file, target_channel_id, auth_token):
                    uploaded += 1
                progress.update(task, advance=1)

    console.print(f"\n[green]Successfully uploaded {uploaded} images[/green]")


# ==================== CLI Telegram Functions ====================


def telegram_upload_cli(source_dir: str, bot_token: str, chat_id: str, use_albums: bool = True) -> None:
    """CLI handler for uploading local files to Telegram."""
    stats = telegram_upload_from_local(source_dir, bot_token, chat_id, use_albums)

    console.print(f"\n[green]Upload complete![/green]")
    console.print(f"Total images: {stats['total_images']}")
    console.print(f"Images uploaded: {stats['images_uploaded']}")
    console.print(f"Albums sent: {stats['albums_sent']}")
    console.print(f"Failed uploads: {stats['failed_uploads']}")


def telegram_transfer_cli(
    channel_id: str,
    auth_token: str,
    bot_token: str,
    chat_id: str,
    media_base_dir: str,
    include_text: bool = False,
    use_albums: bool = True,
) -> None:
    """CLI handler for Discord to Telegram transfer."""
    # Verify Telegram chat
    console.print("\n[cyan]Verifying Telegram chat...[/cyan]")
    if not verify_telegram_chat(bot_token, chat_id):
        return

    temp_dir = Path(media_base_dir) / "temp_telegram_transfer"
    temp_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[cyan]Transferring Discord → Telegram...[/cyan]")

    stats = transfer_discord_to_telegram_batch(
        channel_id,
        bot_token,
        chat_id,
        auth_token,
        temp_dir,
        include_text=include_text,
        use_albums=use_albums,
    )

    console.print(f"\n[green]Transfer complete![/green]")
    console.print(f"Total messages processed: {stats['total_messages']}")
    console.print(f"Images found: {stats['images_found']}")
    console.print(f"Images transferred: {stats['images_transferred']}")
    if include_text:
        console.print(f"Text captions sent: {stats['text_transferred']}")
    console.print(f"Failed transfers: {stats['failed_transfers']}")

    _cleanup_temp_dir(temp_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discord Art Gallery Manager")
    parser.add_argument("--interactive", action="store_true", help="Run in interactive mode")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("list-servers", help="List all Discord servers")

    list_channels_parser = subparsers.add_parser("list-channels", help="List channels in a server")
    list_channels_parser.add_argument("--guild-id", required=True, help="Server ID")

    download_parser = subparsers.add_parser("download", help="Download images from a channel")
    download_parser.add_argument("--channel-id", required=True, help="Channel ID to download from")
    download_parser.add_argument("--output-dir", default="extracted_media", help="Output directory")

    transfer_parser = subparsers.add_parser("transfer", help="Transfer images to a Discord channel")
    transfer_parser.add_argument("--source-dir", required=True, help="Source directory with images")
    transfer_parser.add_argument("--target-channel-id", required=True, help="Target Discord channel ID")

    # Telegram commands
    telegram_parser = subparsers.add_parser("telegram", help="Telegram upload/transfer commands")
    telegram_subparsers = telegram_parser.add_subparsers(dest="telegram_command", help="Telegram commands")

    # telegram upload
    telegram_upload_parser = telegram_subparsers.add_parser("upload", help="Upload local directory to Telegram")
    telegram_upload_parser.add_argument("--source-dir", required=True, help="Source directory with images")
    telegram_upload_parser.add_argument("--bot-token", help="Telegram Bot Token (or set TELEGRAM_BOT_TOKEN env)")
    telegram_upload_parser.add_argument("--chat-id", help="Telegram Chat ID (or set TELEGRAM_CHAT_ID env)")
    telegram_upload_parser.add_argument("--albums", action="store_true", help="Send as albums")

    # telegram transfer
    telegram_transfer_parser = telegram_subparsers.add_parser("transfer", help="Transfer Discord channel to Telegram")
    telegram_transfer_parser.add_argument("--channel-id", required=True, help="Discord channel ID")
    telegram_transfer_parser.add_argument("--auth-token", help="Discord Auth Token (or set DISCORD_AUTH_TOKEN env)")
    telegram_transfer_parser.add_argument("--bot-token", help="Telegram Bot Token (or set TELEGRAM_BOT_TOKEN env)")
    telegram_transfer_parser.add_argument("--chat-id", help="Telegram Chat ID (or set TELEGRAM_CHAT_ID env)")
    telegram_transfer_parser.add_argument("--include-text", action="store_true", help="Include text content as captions")
    telegram_transfer_parser.add_argument("--albums", action="store_true", help="Send as albums")

    args = parser.parse_args()

    load_dotenv()

    try:
        AUTH_TOKEN = get_env_var("DISCORD_AUTH_TOKEN")
        MEDIA_BASE_DIR = get_env_var("MEDIA_DIRECTORY", "extracted_media")
    except ValueError as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        return

    if args.interactive or (len(sys.argv) == 1 and sys.stdin.isatty()):
        interactive_menu(AUTH_TOKEN, MEDIA_BASE_DIR)
    elif args.command == "list-servers":
        list_servers(AUTH_TOKEN)
    elif args.command == "list-channels":
        list_channels(args.guild_id, AUTH_TOKEN)
    elif args.command == "download":
        download_images(args.channel_id, AUTH_TOKEN, args.output_dir)
    elif args.command == "transfer":
        transfer_images(args.source_dir, args.target_channel_id, AUTH_TOKEN)
    elif args.command == "telegram":
        if args.telegram_command == "upload":
            bot_token = args.bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = args.chat_id or os.getenv("TELEGRAM_CHAT_ID")

            if not bot_token or not chat_id:
                console.print("[red]Error: Telegram bot token and chat ID required[/red]")
                console.print("[yellow]Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env or use --bot-token and --chat-id[/yellow]")
                return

            telegram_upload_cli(args.source_dir, bot_token, chat_id, args.albums)

        elif args.telegram_command == "transfer":
            auth_token = args.auth_token or AUTH_TOKEN
            bot_token = args.bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = args.chat_id or os.getenv("TELEGRAM_CHAT_ID")

            if not bot_token or not chat_id:
                console.print("[red]Error: Telegram bot token and chat ID required[/red]")
                console.print("[yellow]Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env or use --bot-token and --chat-id[/yellow]")
                return

            telegram_transfer_cli(
                args.channel_id,
                auth_token,
                bot_token,
                chat_id,
                MEDIA_BASE_DIR,
                args.include_text,
                args.albums,
            )
        else:
            telegram_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
