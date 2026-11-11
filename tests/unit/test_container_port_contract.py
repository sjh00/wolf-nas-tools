"""容器端口契约：Python 内部端口不能与容器内 nginx 网关端口相同。

真实故障：把镜像的 WOLFNAS_PORT 从 3000 改成 8080 后，容器启动即报
「端口 8080 被其他程序占用：cmd=nginx -g daemon off」，Python 应用无限重启。

架构是两段式的，两个端口各有归属，绝不可混为一谈：
  WOLFNAS_PORT  → Python 应用监听（容器内部，默认 3000）
  8080          → 容器内 nginx 网关固定监听，反代到上面的 WOLFNAS_PORT
对外只暴露 nginx 的 8080，所以 docker-compose 映射成 `<host>:8080`。
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# nginx 网关端口：docker/rootfs/etc/nginx/nginx.conf.template 里写死的监听端口
NGINX_GATEWAY_PORT = 8080


def _dockerfile_env_port() -> int:
    text = (REPO / "Dockerfile").read_text(encoding="utf-8")
    m = re.search(r"WOLFNAS_PORT=(\d+)", text)
    assert m, "Dockerfile 里找不到 WOLFNAS_PORT"
    return int(m.group(1))


def _nginx_listen_port() -> int:
    tpl = REPO / "docker/rootfs/etc/nginx/nginx.conf.template"
    text = tpl.read_text(encoding="utf-8")
    m = re.search(r"listen\s+(\d+)\s+default_server", text)
    assert m, "nginx 模板里找不到 listen ... default_server"
    return int(m.group(1))


class TestPortContract:
    def test_nginx_gateway_listens_on_8080(self):
        assert _nginx_listen_port() == NGINX_GATEWAY_PORT

    def test_app_port_differs_from_nginx_port(self):
        """核心断言：两者相同 = Python 抢占 nginx 端口，容器起不来。"""
        app_port = _dockerfile_env_port()

        assert app_port != NGINX_GATEWAY_PORT, (
            f"WOLFNAS_PORT 是 Python 应用内部端口，不能等于 nginx 网关端口 "
            f"{NGINX_GATEWAY_PORT}；否则应用启动即报端口占用"
        )

    def test_nginx_upstream_uses_wolfnas_port(self):
        """nginx 必须反代到 WOLFNAS_PORT 渲染出的上游，而不是写死。"""
        tpl = (REPO / "docker/rootfs/etc/nginx/nginx.conf.template").read_text(encoding="utf-8")

        assert "127.0.0.1:__WOLFNAS_PORT__" in tpl

    def test_nginx_port_script_renders_from_env(self):
        """渲染脚本每次启动重写 nginx.conf，避免改了端口仍代理到旧值。"""
        script = (REPO / "docker/rootfs/etc/cont-init.d/021-nginx-port").read_text(encoding="utf-8")

        assert "__WOLFNAS_PORT__" in script
        assert "WOLFNAS_PORT" in script

    def test_healthcheck_targets_nginx_gateway(self):
        """健康检查打的是 nginx 的 8080（再反代到应用），不是应用端口。"""
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        m = re.search(r"HEALTHCHECK[^\n]*\n[^\n]*localhost:(\d+)/health", text)
        assert m, "找不到健康检查里的 /health 地址"

        assert int(m.group(1)) == NGINX_GATEWAY_PORT

    def test_expose_matches_public_gateway(self):
        """对外可用的是 nginx 的 8080，EXPOSE 应与之相符。"""
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        m = re.search(r"^EXPOSE\s+(\d+)", text, re.M)

        assert m and int(m.group(1)) == NGINX_GATEWAY_PORT
