# 品牌更名兼容登记

项目历经 `nas-tools` → `nexus-media` → **WolfNas** 两次更名。品牌清理后，
代码与文档中仍会出现少量旧名，**全部是向后兼容所需，不是遗漏**。

本文件登记每一处的用途，新增旧名引用前请先在此说明理由。

## 保留清单

### 1. 旧环境变量（读取时回退，不写入）

| 旧名 | 新名 | 位置 |
| --- | --- | --- |
| `NEXUS_PORT` | `WOLFNAS_PORT` | `run.py`、`src/initializer.py` |
| `NEXUS_MEDIA_CONFIG` | `WOLFNAS_CONFIG` | `src/app/core/settings.py`、`alembic/versions/6766a9cd1d4b_1_3_2.py` |
| `NEXUS_MEDIA_DATA` | `WOLFNAS_DATA` | `src/app/core/settings.py` |
| `NEXUS_SITES_DIR` | `WOLFNAS_SITES_DIR` | `src/app/sites/engine.py` |
| `NEXUS_EDITION_OVERRIDES` | `WOLFNAS_EDITION_OVERRIDES` | `src/app/media/identity/{graph,remapper}.py` |
| `NEXUS_NAMING_PATTERNS` | `WOLFNAS_NAMING_PATTERNS` | `src/app/media/parser/naming_patterns.py` |
| `NEXUS_MEDIA_INDEXER_TIMEOUT[_MIN]` | `WOLFNAS_INDEXER_TIMEOUT[_MIN]` | `src/app/indexer/indexer.py` |

**原因**：既有部署的 compose / .env 仍写着旧名。只删旧名会导致端口回落默认值、
配置路径找不到、超时设置失效——表现为升级后服务起不来或行为异常。

**何时可删**：确认所有部署方都已改用新名后（建议跨一个大版本）。

### 2. 数据库历史列名

`ONLY_NEXUS_MEDIA`（`alembic/versions/a2b3c4d5e6f1_*.py`、`b2c3d4e5f6a7_*.py`）

**原因**：这是旧版本实际建出的列名，迁移脚本靠它判断是否需要在
`ONLY_NEXUS_MEDIA` 与 `ONLY_WOLF_NAS` 之间转换。删掉会让老库升级失败。

### 3. 前端 localStorage 历史键

`nexus-*` / `nexus.*`（`apps/nexus-media/src/utils/legacy-storage.ts`）

**原因**：旧版本在这些键里存了服务端地址、通知设置、视图偏好。
`getMigratedItem()` 读取时回退旧键并自动迁移到新键，用户配置不会丢。

### 4. 外部依赖专有名称（不可改）

| 名称 | 说明 |
| --- | --- |
| `nexus-chrome` | 上游提供的浏览器自动化容器镜像 `linyuan0213/nexus-chrome`，服务名与容器名必须匹配 |
| `nexus-verify` | 同上，OCR 识别服务 |
| `NexusPHP` / `nexus_php` | PT 站点框架的行业术语（[NexusPHP](https://github.com/ZJUT/NexusPHP)），非本项目品牌 |
| `NexusMaster` | PT 站点返回的用户等级字段值（`config/sites/api/*.json`） |

### 5. 数据格式标识

字幕后缀风格 `suffix_style = "nexus"`（`.chi.zh-cn` 等）

**原因**：已入库字幕按此格式命名，改名会导致存量字幕无法被识别。
新增风格可选 `bcp47` / `iso639`，默认值保持 `nexus` 以兼容。

### 6. 外部仓库与真实路径

- `linyuan0213/nexus-media`、`linyuan0213/nexus-media-web`、`nexus-media-sites`、
  `nexus-media-plugins`：上游仓库链接，指向真实存在的项目
- `apps/nexus-media/`：前端应用的真实目录名，改动会牵连构建配置与 CI 路径

## 已清理（供对照）

以下旧名已全部替换，不应再出现：

- `NexusError` → `WolfNasError`、`NexusModel` → `WolfNasModel`
- `NEXUS_PORT` 等作为**写入值**（仅保留读取兼容）
- Docker 运行期用户/组 `nexus` → `wolfnas`（UID/GID 仍为 911，卷权限不受影响）
- 容器服务目录 `services.d/nexus-media` → `services.d/wolfnas`
- 网络名 `nexus-media-network` → `wolfnas-network`
- `PT_TAG`（种子标签）已是 `WOLFNAS`
- 前端 localStorage **写入**键、脚本名 `dev:nexus`/`build:nexus`、日志下载文件名
- 文档与 README 中的品牌文案
