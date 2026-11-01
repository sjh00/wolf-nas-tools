"""豆瓣 HTML 分集解析与 PoW 测试（无网络）."""

import hashlib

from app.infrastructure.external.doubanapi.episodes import parse_episode_html, solve_pow


def test_parse_episode_html_extracts_fields():
    html = """
    <html><head><title>某剧 第2集 - 豆瓣</title></head><body>
      <span>本集中文名</span><span>第二集标题</span>
      <span>本集原名</span><span>Episode Two</span>
      <span>播放时间</span><span>2026-01-02</span>
      <span>剧情简介</span><span>这一集的简介</span>
      <div class="ep-pic"><img src="https://img/still.jpg"></div>
    </body></html>
    """
    item = parse_episode_html(html, 2)

    assert item["episode_number"] == 2
    assert item["title"] == "第二集标题"
    assert item["original_title"] == "Episode Two"
    assert item["air_date"] == "2026-01-02"
    assert item["overview"] == "这一集的简介"
    assert item["still"] == "https://img/still.jpg"


def test_solve_pow_returns_valid_nonce():
    cha = "abc"
    nonce = solve_pow(cha, difficulty=2)
    assert hashlib.sha512((cha + str(nonce)).encode()).hexdigest().startswith("00")
