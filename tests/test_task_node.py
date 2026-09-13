from hermes_telegram_downloader.module.app import DownloadStatus, TaskNode, TaskType


def test_direct_task_finishes_after_stat():
    node = TaskNode(chat_id=1, limit=1, task_type=TaskType.Download)
    node.is_running = True
    node.total_task = 1
    assert node.is_finish() is False
    node.stat(DownloadStatus.SuccessDownload)
    assert node.is_finish() is True
