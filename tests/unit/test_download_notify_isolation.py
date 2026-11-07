"""下载通知失败不得让「创建下载任务」判为失败。

种子里已经在下载器里建好、历史也已落库，此时通知渠道异常（模板取值、渠道超时等）
只能告警，不能把异常抛回 API 层 —— 否则用户看到「创建下载任务失败」，但任务其实在
下载器里跑着，还会被前端重复提交。
"""

from unittest.mock import MagicMock

from app.downloader.pipeline import DownloadPipeline
from app.media.models import MediaInfo


def _pipeline(message) -> DownloadPipeline:
    pipeline = DownloadPipeline.__new__(DownloadPipeline)
    pipeline._download_history_repo = MagicMock()
    pipeline._event_bus = MagicMock()
    pipeline._client_factory = MagicMock()
    pipeline._client_factory.get_download_visit_dir.return_value = "/downloads"
    pipeline._sitesubtitle = MagicMock()
    pipeline._message = message
    return pipeline


def _post(pipeline: DownloadPipeline) -> None:
    pipeline._stage_post(
        media_info=MediaInfo(),
        downloader_id="qb1",
        download_id="h1",
        page_url="",
        # 磁力链路：无需 dl_files 也能定位保存目录，避免走「目录不正确」提前返回分支
        content="magnet:?xt=urn:btih:deadbeef",
        dl_files_folder=None,
        dl_files=[],
        download_dir="/downloads",
        downloader_name="qBittorrent",
        download_setting_name="默认",
        site_info=None,
        torrent_attr=None,
        in_from="qb",
        user_name="u",
        user_id=1,
        history_id=None,
    )


def test_notify_exception_is_swallowed():
    message = MagicMock()
    message.send_download_message.side_effect = AttributeError("'NoneType' object has no attribute 'display_name'")
    pipeline = _pipeline(message)

    # 不应抛出
    _post(pipeline)
    message.send_download_message.assert_called_once()


def test_history_still_written_when_notify_fails():
    message = MagicMock()
    message.send_download_message.side_effect = RuntimeError("boom")
    pipeline = _pipeline(message)

    _post(pipeline)
    pipeline._download_history_repo.insert_download_history.assert_called_once()
