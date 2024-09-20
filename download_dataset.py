import aiohttp
import asyncio
import os
from tqdm import tqdm
import time


async def download_parquet(session, url, filename, pbar):
    if filename is None:
        filename = url.split('/')[-1]

    save_path = os.path.join(os.getcwd(), filename)

    try:
        async with session.get(url) as response:
            total_size = int(response.headers.get('content-length', 0))
            with open(save_path, 'wb') as file:
                downloaded = 0
                async for chunk in response.content.iter_chunked(8192):
                    file.write(chunk)
                    downloaded += len(chunk)
                    pbar.update(len(chunk))
        print(f"\nFile downloaded and saved as /dataset/{save_path}")
    except Exception as e:
        print(f"An unexpected error occurred while downloading {filename}: {e}")


async def main(urls):
    start_time = time.time()
    async with aiohttp.ClientSession() as session:
        total_size = 0
        for url in urls:
            async with session.head(url) as response:
                total_size += int(response.headers.get('content-length', 0))

        with tqdm(total=total_size, unit='B', unit_scale=True, desc="Total Progress") as pbar:
            tasks = [download_parquet(session, url, None, pbar) for url in urls]
            await asyncio.gather(*tasks)
    end_time = time.time()
    total_time = end_time - start_time
    print(f"\nTotal download time: {total_time:.2f} seconds")


# Example usage
urls = [
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_20.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_21.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_22.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_23.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_24.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_25.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_26.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_27.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_28.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_29.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_30.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_31.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_32.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_33.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_34.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_35.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_36.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_37.snappy.parquet",
    "https://datasets-documentation.s3.eu-west-3.amazonaws.com/pypi/2023/pypi_0_7_38.snappy.parquet",
]

if __name__ == "__main__":
    asyncio.run(main(urls))
