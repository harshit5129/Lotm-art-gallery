# Discord Art Gallery Manager

A CLI tool for downloading and transferring images between Discord servers with batch processing to minimize disk usage.

## Setup

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your Discord credentials
```

## Environment Variables

Required in `.env`:
- `DISCORD_AUTH_TOKEN` - Your Discord authorization token
- `MEDIA_DIRECTORY` - Base directory for media storage (default: extracted_media)

## Running

```bash
# Interactive mode (requires TTY)
uv run main.py --interactive

# Command-line mode
uv run main.py list-servers
uv run main.py list-channels --guild-id <server_id>
uv run main.py download --channel-id <channel_id> --output-dir <directory>
uv run main.py transfer --source-dir <directory> --target-channel-id <channel_id>
```

## Key Features

- **Batch Transfer**: Processes images in batches (default: 5) to minimize disk usage
- **Server-to-Server Transfer**: Transfer entire servers or specific channels
- **Text Content**: Option to include message text with image transfers
- **Category Creation**: Auto-create categories and channels for organized transfers
- **Progress Tracking**: Rich console output with progress bars

## Architecture

- `Config` class: Centralized configuration (API URLs, timeouts, batch sizes)
- `ChannelType` enum: Discord channel type constants
- `make_request()`: Centralized API request handler with error handling
- `transfer_images_batch()`: Core transfer logic with disk-space optimization
- Interactive menu system with numbered selections

## Important Notes

- **Disk Usage**: Batch processing limits disk usage to ~5 images at a time
- **Rate Limits**: No built-in rate limiting - may hit Discord API limits on large transfers
- **Image Counting**: Disabled by default in channel selection for performance
- **Temporary Files**: Automatically cleaned up after transfers
- **TTY Required**: Interactive mode requires a terminal; use CLI args for scripts

## Development

```bash
# Check syntax
python3 -m py_compile main.py

# Run with uv
source $HOME/.local/bin/env
uv run main.py --help
```
