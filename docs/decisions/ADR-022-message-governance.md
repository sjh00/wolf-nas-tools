# ADR-022: 消息治理层（去重/聚合）

## 背景

批量事件会在短时间内产生海量通知。典型场景：1000+ 文件入库失败时，
`MessageDispatcher.sendmsg` 每个转移任务发送一条 `transfer_fail`，
用户绑定的 Telegram/微信等渠道瞬间收到 1000+ 条消息，既淹没重点也易触发渠道限流。

原有能力零散：`message_builder` 仅对 `download_fail` 做了 600s 去重缓存；
`RedisMessageQueue` 的 `msg_id` 是随机 UUID，只能防重复消费，无法对相同内容去重；
内存队列 `maxsize=1000` 且满时静默丢弃。均无法覆盖批量场景。

## 决策

在唯一出站单点 `MessageDispatcher.sendmsg` 前引入通用治理层 `MessageGovernor`，
按 `msg_type` 表驱动策略，所有业务无需改动：

- **immediate**：直接发送（插件/统计等低量或有即时性要求的类型）
- **dedup**：TTL 内相同内容（`msg_type + client + user_id + title/text 摘要`）只发一次
- **digest**：窗口内前 N 条直接发送，超出部分聚合为**一条摘要**，由定时任务 flush

关键设计：

1. **单点接入**：`sendmsg` 渲染模板后调用 `governor.intercept(...)`；
   返回拦截则不发送。`submit_now` 为绕过治理层的直接入队接口，供摘要回调使用，
   投递仍复用既有 `MessageQueue`，不新增发送通道。
2. **状态外置**：窗口计数、去重标记、聚合缓冲放在 `GovernorStore`；
   `RedisGovernorStore`（Lua 保证 `INCR+EXPIRE`、`SET NX EX`、`LRANGE+DEL` 原子性）
   优先，Redis 不可用时降级 `MemoryGovernorStore`。多 worker/多实例判定一致。
3. **flush 交给调度器**：`SchedulerCore.register_interval` 注册
   `MessageGovernor.flush`（间隔取 `message_governor.flush_seconds`），
   复用调度器生命周期与分布式锁 `scheduler:lock:MessageGovernor.flush`，
   不另起私有线程。缓冲项只存可序列化字段，flush 时按 `client_id` 从
   `ClientManager` 解析目标客户端。
4. **用户隔离**：聚合键含 `user_id` 与客户端 `id`，避免跨用户混合（ADR-021）。
5. **模板驱动**：摘要走 `message_digest` 模板（`TemplateEngine.apply_client_template`），
   支持客户端级模板覆盖；渲染失败或无引擎时回退内置文案。
6. **配置化**：`message_governor`（enabled / flush_seconds / max_samples /
   modes / thresholds），`modes` 与 `thresholds` 覆盖默认策略。
7. **明细不丢**：Web 消息中心仍保留逐条明细，外部渠道只推摘要。
8. **异常隔离**：治理层或存储抛错时回退直接发送，绝不阻断消息链路。

## 后果

- 批量失败从 N 条降为「阈值条 + 1 条摘要」，渠道压力可控。
- 新增消息类型默认即时；需要治理时在 `DEFAULT_POLICIES` 或配置中登记。
- 摘要发送延迟最多一个 `flush_seconds`（默认 30s）。
- 无 Redis 时降级为进程内状态，多 worker 下各进程独立计数（可接受降级）。

## 备选方案

- **每个业务自行去重**：改动分散、易漏，且无法统一阈值与摘要。
- **直接依赖消息队列**：队列是传输层，无延迟/窗口原语；其去重键为随机 UUID，
  且 Redis 队列 payload 丢弃 `msg_type`，无法承担按类型的聚合。
- **发送侧简单限流丢弃**：会静默丢消息，丢失失败上下文。
- **HTTP 网关限流**：粒度在渠道层，无法按消息类型与用户聚合。
