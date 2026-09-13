"""冒烟测试：验证包结构与 import 改写正确。"""

import importlib

import pytest

SUBMODULES = [
    "hermes_telegram_downloader.module.app",
    "hermes_telegram_downloader.module.bot",
    "hermes_telegram_downloader.module.cloud_drive",
    "hermes_telegram_downloader.module.download_stat",
    "hermes_telegram_downloader.module.filter",
    "hermes_telegram_downloader.module.language",
    "hermes_telegram_downloader.module.task_store",
    "hermes_telegram_downloader.module.tg.client",
    "hermes_telegram_downloader.module.tg.download",
    "hermes_telegram_downloader.module.tg.history",
    "hermes_telegram_downloader.module.web",
    "hermes_telegram_downloader.utils.format",
    "hermes_telegram_downloader.utils.log",
    "hermes_telegram_downloader.utils.meta",
    "hermes_telegram_downloader.utils.meta_data",
    "hermes_telegram_downloader.utils.platform",
]


def test_import_package():
    import hermes_telegram_downloader

    assert hermes_telegram_downloader.__version__


def test_import_main_module():
    """主模块 import 时执行模块级 Application()，已确认无文件 IO，不会崩溃。"""
    import hermes_telegram_downloader.media_downloader

    assert callable(hermes_telegram_downloader.media_downloader.cli)


@pytest.mark.parametrize("mod", SUBMODULES)
def test_import_submodule(mod):
    importlib.import_module(mod)
