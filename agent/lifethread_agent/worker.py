"""Standalone Agent Daemon / Worker for LifeThread Autonomous Execution.

Runs the background agent orchestration loop, handles health checks on port 8002,
and processes autonomous execution tasks.
"""

import asyncio
import json
import logging
import os
import signal
from datetime import UTC, datetime

from lifethread_agent.orchestrator import AgentOrchestrator

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("lifethread.agent.worker")

PORT = int(os.getenv("AGENT_WORKER_PORT", "8002"))
HOST = os.getenv("AGENT_WORKER_HOST", "0.0.0.0")


class AgentWorkerService:
    """Agent Background Worker with embedded HTTP Health Check."""

    def __init__(self) -> None:
        self.running = False
        self.orchestrator = AgentOrchestrator(orchestrator_id="worker-daemon-01")
        self.started_at = datetime.now(UTC)
        self.processed_runs = 0

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming HTTP requests for container health checks and status."""
        try:
            line = await reader.readline()
            request_line = line.decode().strip()
            # Read until empty line (end of headers)
            while True:
                header = await reader.readline()
                if not header or header == b"\r\n":
                    break

            parts = request_line.split()
            path = parts[1] if len(parts) > 1 else "/"

            if path in ("/health", "/healthz", "/ready"):
                uptime = (datetime.now(UTC) - self.started_at).total_seconds()
                body = json.dumps({
                    "status": "healthy",
                    "service": "lifethread-agent-worker",
                    "uptime_seconds": round(uptime, 1),
                    "processed_runs": self.processed_runs,
                    "timestamp": datetime.now(UTC).isoformat(),
                }).encode("utf-8")
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\n".encode()
                    + b"Connection: close\r\n\r\n"
                    + body
                )
            else:
                body = b'{"status": "not_found"}'
                response = (
                    b"HTTP/1.1 404 Not Found\r\n"
                    b"Content-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\n".encode()
                    + b"Connection: close\r\n\r\n"
                    + body
                )

            writer.write(response)
            await writer.drain()
        except Exception as e:
            logger.debug("Error handling client request: %s", e)
        finally:
            writer.close()
            await writer.wait_closed()

    async def start(self) -> None:
        """Launch health server and agent worker loop."""
        self.running = True
        logger.info(
            "Starting LifeThread Agent Worker on %s:%d (Environment: %s)",
            HOST,
            PORT,
            os.getenv("ENVIRONMENT", "production"),
        )

        server = await asyncio.start_server(self.handle_client, HOST, PORT)

        # Worker background task processing loop
        async def worker_loop():
            while self.running:
                try:
                    # In a production environment, poll queue / Redis / DB for pending agent runs
                    await asyncio.sleep(5)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Error in agent worker cycle: %s", e)

        _worker_task = asyncio.create_task(worker_loop())

        async with server:
            logger.info("Agent Worker health server listening on %s:%d", HOST, PORT)
            await server.serve_forever()

    def stop(self) -> None:
        """Gracefully terminate worker."""
        logger.info("Stopping Agent Worker...")
        self.running = False


async def main() -> None:
    service = AgentWorkerService()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, service.stop)
        except NotImplementedError:
            # On Windows, add_signal_handler may not be implemented for all signals
            pass

    try:
        await service.start()
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Agent Worker terminated.")


if __name__ == "__main__":
    asyncio.run(main())
