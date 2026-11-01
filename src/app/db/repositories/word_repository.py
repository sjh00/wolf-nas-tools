"""
Word Repository
Handles custom words and word groups related database operations.
"""

from app.db.models import CUSTOMWORDGROUPS, CUSTOMWORDS
from app.db.repositories.base_repository import BaseRepository


class WordRepository(BaseRepository):
    """
    自定义识别词仓储
    处理自定义识别词和词组的数据库操作
    """

    # ==================== Custom Words ====================

    def insert_custom_word(
        self, replaced, replace, front, back, offset, wtype, gid, season, enabled, regex, whelp, note=None
    ):
        """
        增加自定义识别词

        Args:
            replaced: 被替换的词
            replace: 替换为的词
            front: 前置词
            back: 后置词
            offset: 偏移量
            wtype: 类型
            gid: 组ID
            season: 季
            enabled: 是否启用
            regex: 是否正则
            whelp: 帮助信息
            note: 备注
        """
        note = note or ""
        whelp = whelp or ""
        with self.session() as db:
            db.add(
                CUSTOMWORDS(
                    REPLACED=str(replaced or ""),
                    REPLACE=str(replace or ""),
                    FRONT=str(front or ""),
                    BACK=str(back or ""),
                    OFFSET=str(offset or ""),
                    TYPE=int(wtype),
                    GROUP_ID=int(gid),
                    SEASON=int(season),
                    ENABLED=int(enabled),
                    REGEX=int(regex),
                    HELP=whelp,
                    NOTE=note,
                )
            )
            db.commit()
            return True

    def delete_custom_word(self, wid=None):
        """
        删除自定义识别词

        Args:
            wid: 词ID，None则删除所有
        """
        with self.session() as db:
            if not wid:
                db.query(CUSTOMWORDS).delete()
            db.query(CUSTOMWORDS).filter(CUSTOMWORDS.ID == int(wid or 0)).delete()
            db.commit()
            return True

    def check_custom_word(self, wid=None, enabled=None):
        """
        设置自定义识别词状态

        Args:
            wid: 词ID，None则更新所有
            enabled: 是否启用
        """
        if enabled is None:
            return True
        with self.session() as db:
            if wid:
                db.query(CUSTOMWORDS).filter(CUSTOMWORDS.ID == int(wid)).update({"ENABLED": int(enabled)})
            else:
                db.query(CUSTOMWORDS).update({"ENABLED": int(enabled)})
            db.commit()
            return True

    def get_custom_words(self, wid=None, gid=None, enabled=None):
        """
        查询自定义识别词

        Args:
            wid: 词ID
            gid: 组ID
            enabled: 是否启用

        Returns:
            自定义识别词列表
        """
        with self.session() as db:
            if wid:
                return db.query(CUSTOMWORDS).filter(CUSTOMWORDS.ID == int(wid)).all()
            elif gid:
                return (
                    db.query(CUSTOMWORDS)
                    .filter(CUSTOMWORDS.GROUP_ID == int(gid))
                    .order_by(CUSTOMWORDS.ENABLED.desc(), CUSTOMWORDS.TYPE, CUSTOMWORDS.REGEX, CUSTOMWORDS.ID)
                    .all()
                )
            elif enabled is not None:
                return (
                    db.query(CUSTOMWORDS)
                    .filter(CUSTOMWORDS.ENABLED == int(enabled))
                    .order_by(CUSTOMWORDS.GROUP_ID, CUSTOMWORDS.TYPE, CUSTOMWORDS.REGEX, CUSTOMWORDS.ID)
                    .all()
                )
            return (
                db.query(CUSTOMWORDS)
                .order_by(
                    CUSTOMWORDS.GROUP_ID,
                    CUSTOMWORDS.ENABLED.desc(),
                    CUSTOMWORDS.TYPE,
                    CUSTOMWORDS.REGEX,
                    CUSTOMWORDS.ID,
                )
                .all()
            )

    def is_custom_words_existed(self, replaced=None, front=None, back=None):
        """
        查询自定义识别词是否存在

        Args:
            replaced: 被替换的词
            front: 前置词
            back: 后置词

        Returns:
            是否存在
        """
        with self.session() as db:
            if replaced:
                count = db.query(CUSTOMWORDS).filter(replaced == CUSTOMWORDS.REPLACED).count()
            elif front and back:
                count = db.query(CUSTOMWORDS).filter(front == CUSTOMWORDS.FRONT, back == CUSTOMWORDS.BACK).count()
            else:
                return False
            return count > 0

    # ==================== Custom Word Groups ====================

    def insert_custom_word_groups(self, title, year, gtype, tmdbid, season_count, note=None):
        """
        增加自定义识别词组

        Args:
            title: 标题
            year: 年份
            gtype: 类型
            tmdbid: TMDB ID
            season_count: 季数
            note: 备注
        """
        note = note or ""
        with self.session() as db:
            db.add(
                CUSTOMWORDGROUPS(
                    TITLE=str(title or ""),
                    YEAR=str(year or ""),
                    TYPE=int(gtype or 0),
                    TMDBID=int(tmdbid or 0),
                    SEASON_COUNT=int(season_count or 0),
                    NOTE=note,
                )
            )
            db.commit()
            return True

    def delete_custom_word_group(self, gid):
        """
        删除自定义识别词组

        Args:
            gid: 组ID
        """
        if not gid:
            return True
        with self.session() as db:
            db.query(CUSTOMWORDS).filter(CUSTOMWORDS.GROUP_ID == int(gid)).delete()
            db.query(CUSTOMWORDGROUPS).filter(CUSTOMWORDGROUPS.ID == int(gid)).delete()
            db.commit()
            return True

    def get_custom_word_groups(self, gid=None, tmdbid=None, gtype=None):
        """
        查询自定义识别词组

        Args:
            gid: 组ID
            tmdbid: TMDB ID
            gtype: 类型

        Returns:
            自定义识别词组列表
        """
        with self.session() as db:
            if gid:
                return db.query(CUSTOMWORDGROUPS).filter(CUSTOMWORDGROUPS.ID == int(gid)).all()
            if tmdbid and gtype:
                return (
                    db.query(CUSTOMWORDGROUPS)
                    .filter(CUSTOMWORDGROUPS.TMDBID == int(tmdbid), CUSTOMWORDGROUPS.TYPE == int(gtype))
                    .all()
                )
            if tmdbid:
                return db.query(CUSTOMWORDGROUPS).filter(CUSTOMWORDGROUPS.TMDBID == int(tmdbid)).all()
            return db.query(CUSTOMWORDGROUPS).all()

    def is_custom_word_group_existed(self, tmdbid=None, gtype=None):
        """
        查询自定义识别词组是否存在

        Args:
            tmdbid: TMDB ID
            gtype: 类型

        Returns:
            是否存在
        """
        if not gtype or not tmdbid:
            return False
        with self.session() as db:
            count = (
                db.query(CUSTOMWORDGROUPS)
                .filter(CUSTOMWORDGROUPS.TMDBID == int(tmdbid), CUSTOMWORDGROUPS.TYPE == int(gtype))
                .count()
            )
            return count > 0
