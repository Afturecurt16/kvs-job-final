"""MAX mini application entry point."""

import asyncio
import logging

import uvicorn

from config import MINIAPP_HOST, MINIAPP_PORT


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


async def main() -> None:
    """Run the MAX mini application server."""
    server = uvicorn.Server(
        uvicorn.Config(
            "miniapp.app:app",
            host=MINIAPP_HOST,
            port=MINIAPP_PORT,
            log_level="info",
            lifespan="on",
        )
    )
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
