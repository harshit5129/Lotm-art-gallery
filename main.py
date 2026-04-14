import requests
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


def get_env_var(var_name: str, default: Optional[str] = None) -> str:
    """Get environment variable with optional default."""
    value = os.getenv(var_name, default)
    if not value:
        raise ValueError(f"Environment variable {var_name} is not set")
    return value


def get_media_folder(base_path: str, create_subfolders: bool = True) -> Path:
    """Get organized media folder structure."""
    base = Path(base_path)

    if create_subfolders:
        today = datetime.now().strftime("%Y-%m-%d")
        return base / today
    return base


def download_media(url: str, folder_path: Path, filename: str, message_id: str) -> bool:
    """Downloads media from URL and saves it to the specified folder with organized naming."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        file_extension = Path(filename).suffix
        safe_filename = f"{message_id}{file_extension}"
        file_path = folder_path / safe_filename

        with open(file_path, "wb") as file:
            file.write(response.content)

        print(f"Downloaded: {safe_filename}")
        return True
    except requests.RequestException as e:
        print(f"Failed to download {filename}: {e}")
        return False


def retrieve_messages(
    channel_id: str, auth_token: str, base_directory: str = "extracted_media"
) -> dict:
    """Retrieves all messages from a Discord channel and downloads media attachments."""
    headers = {"authorization": auth_token}

    media_folder = get_media_folder(base_directory)
    media_folder.mkdir(parents=True, exist_ok=True)

    stats = {
        "total_messages": 0,
        "text_messages": 0,
        "media_downloaded": 0,
        "failed_downloads": 0,
    }

    media_data = []
    all_messages = []
    last_message_id = None
    limit = 100

    while True:
        params = {"limit": limit}
        if last_message_id:
            params["before"] = last_message_id

        try:
            response = requests.get(
                f"https://discord.com/api/v9/channels/{channel_id}/messages",
                headers=headers,
                params=params,
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"API request failed: {e}")
            break

        try:
            json_data = response.json()
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON response: {e}")
            break

        if not json_data:
            print("No more messages to retrieve")
            break

        for message in json_data:
            stats["total_messages"] += 1
            message_id = message.get("id", "")
            last_message_id = message_id

            content = message.get("content", "")
            timestamp = message.get("timestamp", "")
            author = message.get("author", {})
            author_name = author.get("username", "Unknown")
            author_id = author.get("id", "")

            message_data = {
                "message_id": message_id,
                "content": content,
                "timestamp": timestamp,
                "author": {
                    "username": author_name,
                    "id": author_id,
                },
                "attachments": [],
            }

            if content:
                stats["text_messages"] += 1

            attachments = message.get("attachments", [])
            for attachment in attachments:
                url = attachment.get("url")
                filename = attachment.get("filename")
                content_type = attachment.get("content_type", "")
                size = attachment.get("size", 0)

                attachment_data = {
                    "url": url,
                    "filename": filename,
                    "content_type": content_type,
                    "size": size,
                }

                if url and filename and message_id:
                    if download_media(url, media_folder, filename, message_id):
                        stats["media_downloaded"] += 1
                        file_extension = Path(filename).suffix
                        safe_filename = f"{message_id}{file_extension}"
                        attachment_data["saved_filename"] = safe_filename
                        attachment_data["downloaded"] = True
                    else:
                        stats["failed_downloads"] += 1
                        attachment_data["downloaded"] = False

                message_data["attachments"].append(attachment_data)

            all_messages.append(message_data)

        print(f"Retrieved {len(json_data)} messages (Total: {stats['total_messages']})")

    json_file_path = media_folder / "all_messages.json"
    with open(json_file_path, "w", encoding="utf-8") as json_file:
        json.dump(all_messages, json_file, indent=2, ensure_ascii=False)

    print(f"\nDownload complete! Stats: {stats}")
    print(f"All messages saved to: {json_file_path}")
    return stats


if __name__ == "__main__":
    load_dotenv()

    try:
        CHANNEL_ID = get_env_var("DISCORD_CHANNEL_ID")
        AUTH_TOKEN = get_env_var("DISCORD_AUTH_TOKEN")
        MEDIA_BASE_DIR = get_env_var("MEDIA_DIRECTORY", "extracted_media")

        print(f"Downloading media from channel {CHANNEL_ID} to {MEDIA_BASE_DIR}")
        retrieve_messages(CHANNEL_ID, AUTH_TOKEN, MEDIA_BASE_DIR)

    except ValueError as e:
        print(f"Configuration error: {e}")
        print("Please set the following environment variables:")
        print("  DISCORD_CHANNEL_ID - Your Discord channel ID")
        print("  DISCORD_AUTH_TOKEN - Your Discord authorization token")
        print("  MEDIA_DIRECTORY - (Optional) Base directory for media storage")
