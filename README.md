# AI Core

A high-performance, real-time multimodal AI application built with FastAPI and Google's Gemini Live API. This service enables real-time voice conversations with AI assistants through WebRTC, supporting simultaneous audio and video processing for applications like screen sharing, video feeds, and interactive AI assistants.

## 🚀 Features

- **Real-time Voice Conversations**: Low-latency audio streaming with Google Gemini Live API
- **Multimodal Support**: Simultaneous processing of audio and video streams
- **WebRTC Integration**: Direct peer-to-peer connections for efficient media streaming
- **Parallel Queue Processing**: Independent audio and media queues prevent starvation and ensure smooth multimodal performance
- **Optimized Performance**: 
  - Image optimization (thumbnail, compression, format conversion)
  - Frame rate limiting and duplicate detection
  - Minimal latency with near-zero sleep intervals
  - Audio transcription support
- **Session Management**: Redis-backed session storage and management
- **WebSocket Support**: Real-time bidirectional communication for audio streaming
- **Production Ready**: FastAPI with async/await, proper error handling, and logging

## 📋 Requirements

- **Python**: >= 3.12
- **Redis**: For session management (can run via Docker)
- **Google Gemini API Key**: Required for Gemini Live API access
- **UV Package Manager**: For dependency management (recommended)

## 🛠️ Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd ai-core
```

### 2. Install UV (if not already installed)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or via pip
pip install uv
```

### 3. Install Dependencies

```bash
# Production dependencies
make install

# Or with development tools
make install-dev
```

### 4. Set Up Environment Variables

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash-native-audio-preview-09-2025

APP_HOST=0.0.0.0
APP_PORT=8000
DEBUG=True

REDIS_URL=redis://localhost:6379
```

## 🏃 Running the Application

### Start Redis (if not running)

```bash
# Using Docker (recommended)
make redis

# Or manually
docker run --name redis-dev -p 6379:6379 -d redis:latest
```

### Start the Application

```bash
# Using Make
make run

# Or directly with UV
uv run python src/main.py

# Or with uvicorn
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`

### Verify Installation

```bash
# Health check
curl http://localhost:8000/health

# Root endpoint
curl http://localhost:8000/
```

## 📡 API Endpoints

### REST Endpoints

#### `POST /api/v1/session`
Creates a new AI assistant session and returns a WebRTC offer.

**Request Body:**
```json
{
  "system_instruction": "You are a helpful AI assistant.",
  "audio_speaker_name": "Zephyr"
}
```

**Response:**
```json
{
  "session_id": "uuid-here",
  "offer": {
    "type": "offer",
    "sdp": "v=0\r\n..."
  }
}
```

#### `POST /api/v1/session/{session_id}/answer`
Receives the client's WebRTC SDP answer to establish the connection.

**Request Body:**
```json
{
  "answer": {
    "type": "answer",
    "sdp": "v=0\r\n..."
  }
}
```

#### `DELETE /api/v1/session/{session_id}`
Terminates a session and cleans up all resources.

#### `GET /health`
Health check endpoint.

#### `GET /`
Root endpoint with API status.

### WebSocket Endpoint

#### `WS /api/v1/ws/{session_id}`
WebSocket connection for real-time audio streaming. Used to receive audio responses from the AI assistant.

## 🏗️ Architecture

### Core Components

1. **GeminiLiveClient** (`services/gemini_client.py`)
   - Manages Gemini Live API sessions
   - Handles WebRTC peer connections
   - Processes audio and video queues in parallel
   - Optimizes media for API transmission

2. **SessionService** (`services/session_service.py`)
   - Manages session lifecycle
   - Handles WebRTC signaling (offer/answer)
   - Integrates with Redis for persistence

3. **ConnectionManager** (`services/connection_manager.py`)
   - Manages WebSocket connections
   - Routes audio responses to clients

4. **WebRTCManager**
   - Handles WebRTC peer connections
   - Optimizes video frames (thumbnail, compression)
   - Manages data channels for audio/video

### Queue Processing

The system uses **parallel queue processing** to prevent starvation:

- **Audio Queue**: Dedicated processor for audio and text inputs (maxsize=50)
- **Media Queue**: Dedicated processor for images/video (maxsize=1)
- Both processors run as independent `asyncio.Task` instances for true concurrency

This architecture ensures that continuous audio streams don't block video frame processing, enabling smooth multimodal interactions.

## 🔧 Development

### Available Make Commands

```bash
make help          # Show all available commands
make install       # Install production dependencies
make install-dev   # Install development dependencies
make run           # Run the application
make lint          # Run linting (ruff)
make format        # Format code (ruff format)
make type-check    # Run type checking (mypy)
make check         # Run all checks (lint, format, type-check)
make fix           # Fix linting issues automatically
make clean         # Clean up generated files
make redis         # Start Redis container
make redis-stop    # Stop Redis container
```

### Code Quality

The project uses:
- **Ruff**: Fast Python linter and formatter
- **MyPy**: Static type checking
- **Black**: Code formatting (via Ruff)
- **Pre-commit**: Git hooks for quality checks

### Running Tests

```bash
# Install test dependencies
uv sync --dev

# Run tests
uv run pytest

# With coverage
uv run pytest --cov=src --cov-report=html
```

## 📁 Project Structure

```
ai-core/
├── src/
│   ├── api/
│   │   ├── setup_middleware.py      # FastAPI middleware setup
│   │   └── v1/
│   │       └── endpoints/
│   │           └── session.py        # Session API endpoints
│   ├── core/
│   │   └── config.py                 # Configuration management
│   ├── schemas/
│   │   └── session.py                # Pydantic models
│   ├── services/
│   │   ├── connection_manager.py     # WebSocket connection management
│   │   ├── gemini_client.py          # Gemini Live API client
│   │   ├── redis_client.py           # Redis client wrapper
│   │   └── session_service.py        # Session business logic
│   └── main.py                       # FastAPI application entry point
├── examples/
│   └── index.html                    # Example client implementation
├── Makefile                          # Development commands
├── pyproject.toml                    # Project configuration
└── README.md                         # This file
```

## 🔐 Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | ✅ Yes | - | Google Gemini API key |
| `GEMINI_MODEL` | ✅ Yes | - | Gemini model name (e.g., `gemini-2.5-flash-native-audio-preview-09-2025`) |
| `APP_HOST` | No | `0.0.0.0` | Application host |
| `APP_PORT` | No | `8000` | Application port |
| `DEBUG` | No | `False` | Enable debug mode |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis connection URL |

## 🎯 Performance Optimizations

1. **Image Optimization**:
   - Automatic thumbnail generation (512x512 max)
   - JPEG compression (60% quality)
   - Format conversion (RGBA → RGB)
   - Duplicate frame detection

2. **Audio Processing**:
   - Minimal latency with near-zero sleep intervals
   - Audio transcription support
   - Automatic activity detection
   - Optimized queue sizes

3. **Concurrent Processing**:
   - Parallel audio and media queues
   - Independent async tasks
   - No blocking between modalities

## 🐛 Troubleshooting

### Redis Connection Issues

```bash
# Check if Redis is running
docker ps | grep redis

# Start Redis if not running
make redis

# Check Redis connection
redis-cli ping
```

### Gemini API Errors

- Verify your `GEMINI_API_KEY` is set correctly
- Check that `GEMINI_MODEL` matches a valid model name
- Ensure your API key has access to Gemini Live API

### Port Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill the process or change APP_PORT in .env
```

## 📚 Additional Resources

- [Google Gemini Live API Documentation](https://ai.google.dev/docs/live)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [WebRTC Documentation](https://webrtc.org/)
- [Redis Documentation](https://redis.io/docs/)

## 👥 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run quality checks (`make check`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## 📝 License

[Add your license information here]

## 👤 Author

**Mohammed Abbadi**
- Email: mhamedrhamnah@gmail.com

---

**Note**: This project requires a valid Google Gemini API key with access to the Gemini Live API. Make sure to set up your API credentials before running the application.
