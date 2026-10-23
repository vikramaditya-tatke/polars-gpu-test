import asyncio
import json
from pathlib import Path
import sys

import aiohttp
from aiohttp import web
import polars as pl
from polars.testing import assert_frame_equal
import pytest

import download_dataset
import pipeline


@pytest.fixture
def shards(tmp_path):
    rows = [
        ('US', 'polars'), ('US', 'polars'), ('GB', 'pandas'), ('GB', 'pandas'),
        (None, 'polars'), ('', 'polars'), ('US', None), (None, None),
        ('DE', "quote's"), ('JP', '日本語'),
    ]
    source = tmp_path / 'input'
    source.mkdir()
    for index, part in enumerate([rows[:5], rows[5:]]):
        pl.DataFrame(part, schema={'COUNTRY_CODE': pl.String, 'PROJECT': pl.String},
                     orient='row').write_parquet(source / f'{index}.parquet')
    return source


def test_all_cpu_stages_and_artifacts(shards, tmp_path):
    output = tmp_path / 'results'
    report = pipeline.run_pipeline(str(shards / '*.parquet'), output, gpu='off')
    assert report['status'] == 'passed', report['failures']
    assert report['input_rows'] == 10
    assert report['groups'] == 8
    assert report['gpu_verified'] is False
    assert sum(row['Status'] == 'passed' for row in report['measurements']) == 6
    assert json.loads((output / 'verification.json').read_text()) == report
    frame = pl.read_parquet(output / 'downloads.parquet')
    assert frame['DOWNLOADS'].sum() == 10
    assert frame.filter(pl.col('COUNTRY_CODE').is_null()).height == 2
    assert (output / 'measurements.csv').is_file()
    assert 'vega' in (output / 'resource_usage.html').read_text()


def test_required_gpu_failure_is_recorded(shards, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, 'gpu_unavailable_reason', lambda: 'Unsupported test device')
    report = pipeline.run_pipeline(str(shards / '*.parquet'), tmp_path / 'results', gpu='required')
    assert report['status'] == 'failed'
    assert report['failures'] == ['Polars GPU: Unsupported test device']
    assert report['gpu_verified'] is False


def test_gpu_uses_strict_engine(shards, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, 'gpu_unavailable_reason', lambda: None)
    real_collect = pl.LazyFrame.collect
    engines = []

    def collect(frame, *args, **kwargs):
        engine = kwargs.get('engine')
        if isinstance(engine, pl.GPUEngine):
            engines.append(engine)
            # Simulate execution only to inspect the requested configuration.
            kwargs['engine'] = 'cpu'
        return real_collect(frame, *args, **kwargs)

    monkeypatch.setattr(pl.LazyFrame, 'collect', collect)
    pipeline.run_pipeline(str(shards / '*.parquet'), tmp_path / 'results')
    assert len(engines) == 1
    assert engines[0].config['raise_on_fail'] is True


def test_missing_input(tmp_path):
    with pytest.raises(FileNotFoundError, match='No Parquet'):
        pipeline.run_pipeline(str(tmp_path / '*.parquet'))


def test_oracle_and_canonical_order(shards):
    files = sorted(str(p) for p in shards.glob('*.parquet'))
    expected = pipeline.reference_counts(files)
    assert_frame_equal(expected, pipeline.canonical(expected.reverse()))


def test_resource_chart_averages_repeated_measurements(tmp_path):
    rows = [
        {'Technology': 'Polars CPU', 'Status': 'passed',
         'Time per loop (s)': 2.0, 'Peak Memory (MiB)': 100.0},
        {'Technology': 'Polars CPU', 'Status': 'passed',
         'Time per loop (s)': 4.0, 'Peak Memory (MiB)': 200.0},
    ]
    chart = pipeline.chart_results(rows, tmp_path / 'resource_usage.html')
    data = next(iter(chart.to_dict()['datasets'].values()))
    assert len(data) == 1
    assert data[0]['Time per loop (s)'] == 3.0
    assert data[0]['Peak Memory (MiB)'] == 150.0


def test_wrong_engine_results_fail_verification(shards, tmp_path, monkeypatch):
    real_collect = pl.LazyFrame.collect

    def wrong_count(frame, *args, **kwargs):
        result = real_collect(frame, *args, **kwargs)
        if kwargs.get('engine') == 'cpu':
            return result.with_columns(pl.col('DOWNLOADS') + 1)
        return result

    monkeypatch.setattr(pl.LazyFrame, 'collect', wrong_count)
    report = pipeline.run_pipeline(str(shards / '*.parquet'), tmp_path / 'results', gpu='off')
    assert report['status'] == 'failed'
    assert len(report['failures']) == 1
    assert report['failures'][0].startswith('Polars CPU: AssertionError:')


def test_notebook_executes_from_clean_kernel(shards, tmp_path, monkeypatch):
    import nbformat
    from nbclient import NotebookClient

    root = Path(__file__).resolve().parents[1]
    kernel_root = tmp_path / 'jupyter'
    kernel = kernel_root / 'kernels' / 'pipeline-test'
    kernel.mkdir(parents=True)
    (kernel / 'kernel.json').write_text(json.dumps({
        'argv': [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
        'display_name': 'Pipeline test', 'language': 'python'
    }))
    monkeypatch.setenv('JUPYTER_PATH', str(kernel_root))
    monkeypatch.setenv('IPYTHONDIR', str(tmp_path / 'ipython'))
    monkeypatch.setenv('PYPI_DATASET', str(shards / '*.parquet'))
    monkeypatch.setenv('PYPI_RESULTS_DIR', str(tmp_path / 'notebook-results'))
    monkeypatch.setenv('PYPI_GPU', 'off')
    notebook = nbformat.read(root / 'polars-gpu-test.ipynb', as_version=4)
    executed = NotebookClient(notebook, timeout=120, kernel_name='pipeline-test',
                              resources={'metadata': {'path': str(root)}}).execute()
    assert all(cell.execution_count is not None for cell in executed.cells if cell.cell_type == 'code')
    report = json.loads((tmp_path / 'notebook-results' / 'verification.json').read_text())
    assert report['status'] == 'passed'
    assert report['input_rows'] == 10


def test_downloader_http_errors_atomicity_and_no_head(shards, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async def scenario():
        payload = (shards / '0.parquet').read_bytes()
        app = web.Application()
        async def serve(request):
            if request.path == '/good.parquet':
                return web.Response(body=payload)
            return web.Response(status=404)
        app.router.add_get('/{name}', serve, allow_head=False)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        base = f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'
        output = tmp_path / 'downloads'
        try:
            paths = await download_dataset.main([base + '/good.parquet'], output)
            assert paths[0].read_bytes() == payload
            default_paths = await download_dataset.main([base + '/good.parquet'])
            assert default_paths == [Path('good.parquet')]
            assert Path('good.parquet').read_bytes() == payload
            async with aiohttp.ClientSession() as session:
                # A failed replacement must preserve an already valid file.
                with pytest.raises(aiohttp.ClientResponseError):
                    await download_dataset.download_parquet(session, base + '/missing.parquet',
                                                            'good.parquet', output_dir=output)
                assert paths[0].read_bytes() == payload
                nested = await download_dataset.download_parquet(
                    session, base + '/good.parquet', 'nested/custom.parquet', output_dir=output)
                assert nested.read_bytes() == payload
            with pytest.raises(ExceptionGroup):
                await download_dataset.main([base + '/missing.parquet'], output)
            assert not list(output.glob('*.part'))
            assert not list(output.glob('.*.part'))
        finally:
            await runner.cleanup()
    asyncio.run(scenario())
