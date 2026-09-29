"""Wait until the configured PostgreSQL database accepts application connections."""

import asyncio
import os

import asyncpg


async def wait_for_postgres() -> None:
    host = os.getenv("DB_HOST", "postgres")
    port = int(os.getenv("DB_PORT", "5432"))
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")
    database = os.getenv("DB_NAME", "kvs_bot")

    while True:
        try:
            connection = await asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                timeout=3,
            )
            await connection.close()
            print("PostgreSQL is available.")
            return
        except (OSError, asyncpg.PostgresError):
            print(f"PostgreSQL at {host}:{port} is not ready; retrying in 2 seconds.")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(wait_for_postgres())
