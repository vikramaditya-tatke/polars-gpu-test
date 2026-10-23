"""Download the public PyPI Parquet shards, failing on incomplete downloads."""

import argparse
import asyncio
from pathlib import Path
import tempfile
import time

import aiohttp
from tqdm import tqdm


urls = [
    f"https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/"
    f"pypi_0_7_{day}.snappy.parquet"
    for day in range(20, 39)
]


async def download_parquet(session, url, filename=None, pbar=None, output_dir="."):
    if filename is None:
        filename = url.split('/')[-1]
    destination = Path(output_dir) / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=f".{destination.name}.", suffix=".part", delete=False
            ) as file:
                temporary = Path(file.name)
                async for chunk in response.content.iter_chunked(1024 * 1024):
                    file.write(chunk)
                    if pbar is not None:
                        pbar.update(len(chunk))
            temporary.replace(destination)
            return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def main(urls, output_dir=".", concurrency=4):
    start = time.perf_counter()
    semaphore = asyncio.Semaphore(concurrency)
    timeout = aiohttp.ClientTimeout(total=1800, sock_connect=30, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # GET is sufficient; servers need not implement HEAD or Content-Length.
        with tqdm(unit="B", unit_scale=True, desc="Downloaded") as pbar:
            async def download(url):
                async with semaphore:
                    return await download_parquet(session, url, pbar=pbar, output_dir=output_dir)

            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(download(url)) for url in urls]
    paths = [task.result() for task in tasks]
    print(f"Downloaded {len(paths)} file(s) to {Path(output_dir).resolve()} "
          f"in {time.perf_counter() - start:.2f}s")
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--limit", type=int, default=len(urls), help="Number of default shards")
    parser.add_argument("--url", action="append", help="Custom URL; repeat for multiple shards")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.limit <= len(urls):
        parser.error(f"--limit must be between 1 and {len(urls)}")
    if args.concurrency < 1:
        parser.error("--concurrency must be positive")
    asyncio.run(main(args.url or urls[:args.limit], args.output_dir, args.concurrency))
