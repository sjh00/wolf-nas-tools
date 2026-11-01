from types import SimpleNamespace
from unittest.mock import MagicMock

from app.plugin_framework.builtin_plugins.mediasyncdel.backend.plugin import (
    MediaSyncDelPlugin,
)


def test_emby_delete_without_tmdb_uses_transfer_path():
    ctx = MagicMock()
    ctx.get_config.return_value = {
        "enable": True,
        "check_file_exists": False,
        "send_notify": False,
    }
    transfer = MagicMock()
    transfer.get_transfer_info_by_path.return_value = [
        SimpleNamespace(ID=7, DEST="/media/movies", DEST_FILENAME="movie.mkv")
    ]
    plugin = MediaSyncDelPlugin(ctx, transfer)
    plugin._sync_del(
        {
            "Event": "library.deleted",
            "Item": {
                "Type": "Movie",
                "Name": "豆瓣电影",
                "Path": "/media/movies/movie.mkv",
                "ProviderIds": {},
            },
        }
    )
    transfer.delete_history.assert_called_once_with(logids=[7], flag="")
