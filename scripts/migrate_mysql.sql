-- =============================================================================
-- 入境定制游多 Agent 系统——MySQL 初始化脚本
-- =============================================================================
-- 此脚本在 MySQL 容器首次启动时自动执行
-- 手动执行：mysql -u travel -ptravel123 travel_agent < scripts/migrate_mysql.sql
-- =============================================================================

-- =============================================================================
-- LangGraph Checkpoint 表
-- =============================================================================

-- 检查点主表：存储每次图执行的完整 State
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id       VARCHAR(128)    NOT NULL COMMENT '会话 ID（对应 session_id）',
    checkpoint_ns   VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '命名空间',
    checkpoint_id   VARCHAR(255)    NOT NULL COMMENT '检查点 UUID',
    parent_checkpoint_id VARCHAR(255)         COMMENT '父检查点 UUID（链式链接）',
    type            VARCHAR(255)             COMMENT '序列化类型',
    checkpoint      LONGBLOB        NOT NULL COMMENT 'State 序列化数据（MsgPack）',
    metadata        LONGBLOB                 COMMENT '元数据（MsgPack）',
    created_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id),
    INDEX idx_thread (thread_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='LangGraph 检查点——存储每次图执行的完整 State';

-- 检查点写入队列表：存储待处理的 channel 写入
CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id       VARCHAR(255)    NOT NULL COMMENT '会话 ID',
    checkpoint_ns   VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '命名空间',
    checkpoint_id   VARCHAR(255)    NOT NULL COMMENT '检查点 UUID',
    task_id         VARCHAR(255)    NOT NULL COMMENT '任务 UUID',
    idx             INT             NOT NULL COMMENT '写入序号',
    channel         VARCHAR(255)    NOT NULL COMMENT '通道名（如 messages）',
    type            VARCHAR(255)             COMMENT '序列化类型',
    value           LONGBLOB                 COMMENT '序列化值',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx),
    INDEX idx_thread_ns (thread_id, checkpoint_ns)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='LangGraph 检查点写入——待合并的 channel 数据';


-- =============================================================================
-- 业务数据表
-- =============================================================================

-- 会话表：记录每次客户接入
CREATE TABLE IF NOT EXISTS sessions (
    session_id      VARCHAR(255)    PRIMARY KEY COMMENT '会话唯一标识',
    customer_id     VARCHAR(255)    NOT NULL COMMENT '客户 ID',
    channel         VARCHAR(50)     NOT NULL DEFAULT 'web' COMMENT '消息渠道',
    language        VARCHAR(10)     NOT NULL DEFAULT 'zh' COMMENT '语言偏好',
    status          VARCHAR(50)     NOT NULL DEFAULT 'active' COMMENT 'active/closed/handoff',
    current_branch  VARCHAR(50)              COMMENT '当前分支',
    intent_level    VARCHAR(20)              COMMENT '意向等级 high/mid/low',
    need_human      BOOLEAN         NOT NULL DEFAULT FALSE COMMENT '是否转人工',
    destination     VARCHAR(100)             COMMENT '目的地',
    days            INT                      COMMENT '行程天数',
    pax             INT                      COMMENT '人数',
    budget          VARCHAR(50)              COMMENT '预算',
    draft_version   INT             NOT NULL DEFAULT 0 COMMENT '行程草案版本',
    revision_count  INT             NOT NULL DEFAULT 0 COMMENT '修订次数',
    created_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_customer (customer_id),
    INDEX idx_status (status),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='会话记录——每次客户接入的基本信息与业务状态';


-- =============================================================================
-- 用户表
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id     VARCHAR(64)  PRIMARY KEY COMMENT '用户唯一标识 (UUID)',
    username    VARCHAR(50)  NOT NULL UNIQUE COMMENT '用户名',
    password    VARCHAR(255) NOT NULL COMMENT 'bcrypt 密码哈希',
    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间',
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户表——最简认证';

-- =============================================================================
-- 对话表
-- =============================================================================

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id VARCHAR(64)  PRIMARY KEY COMMENT '对话唯一标识',
    user_id         VARCHAR(64)  NOT NULL COMMENT '所属用户',
    title           VARCHAR(200) NOT NULL DEFAULT '新对话' COMMENT '对话标题',
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后活跃时间',
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_user (user_id),
    INDEX idx_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='对话列表——每个用户可有多个对话';
