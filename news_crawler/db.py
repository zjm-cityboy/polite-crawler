"""数据库层：PostgreSQL 连接池 + 统一的连接上下文管理器。

与气象 RAG 项目同款实现（已学技术复用）：
  - SimpleConnectionPool：连接建一次反复借还，省去每次握手
  - 双检锁单例：多线程下也只初始化一次池
  - pg_conn 上下文管理器：正常退出自动 commit、异常自动 rollback

踩坑记录：pg_conn 必须加 @contextmanager 装饰器 ——
不加的话它只是个普通生成器函数，with 进去直接 AttributeError: __enter__
（with 语句要求对象实现 __enter__/__exit__，装饰器负责把生成器包装成
具备这两个方法的上下文管理器）。
"""

import threading
from contextlib import contextmanager

from psycopg2.pool import SimpleConnectionPool

_pool = None                    # 模块级连接池，进程内共享
_pool_lock = threading.Lock()   # 保证初始化只发生一次


def get_pool(dsn):
    """拿连接池；不存在则初始化（双检锁：锁外查一次 + 锁内再查一次）。"""
    global _pool
    if _pool is None:                       # 第一次检查：无锁快路径
        with _pool_lock:                    # 加锁
            if _pool is None:               # 第二次检查：防排队线程重复建池
                # minconn=1 起步；maxconn=5 足够单机爬虫使用
                _pool = SimpleConnectionPool(1, 5, dsn)
    return _pool


@contextmanager
def pg_conn(dsn):
    """借出连接的上下文管理器：with pg_conn(dsn) as conn: ...

    yield 之前 = 进入 with 时借连接；finally = 退出 with 时必还连接，
    即使 with 块里抛异常也不漏还；正常走完 commit，异常则 rollback。
    """
    conn = get_pool(dsn).getconn()
    try:
        yield conn
        conn.commit()     # 正常结束：提交事务
    except Exception:
        conn.rollback()   # 出异常：整体回滚，不留半截数据
        raise             # 异常继续外抛，不吞
    finally:
        get_pool(dsn).putconn(conn)   # 无论如何都还连接


# 建表语句：幂等（IF NOT EXISTS），可反复执行。
# DDL 是不含外部输入的静态 SQL，无注入风险；
# 业务数据的增删改查一律走参数绑定（见 pipelines.py）。
DDL_ARTICLES = """
CREATE TABLE IF NOT EXISTS articles (
    id         SERIAL PRIMARY KEY,
    url        TEXT        NOT NULL,
    url_fp     CHAR(40)    NOT NULL,
    title      TEXT        NOT NULL DEFAULT '',
    published  TEXT        NOT NULL DEFAULT '',
    content_md TEXT        NOT NULL,
    content_fp CHAR(40)    NOT NULL UNIQUE,
    crawled_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_articles_url_fp ON articles (url_fp);
"""
