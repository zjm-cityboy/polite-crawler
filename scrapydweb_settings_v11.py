# ScrapydWeb 1.6.0 监控面板配置
# 注意：1.6.0 起配置文件名是 scrapydweb_settings_v11.py（v10 是老版本命名，
# 找不到 v11 文件时程序会复制默认配置后直接退出 —— 已实测踩坑）
# 文档：https://github.com/my8100/scrapydweb

# 被管理的 Scrapyd 节点列表（容器网络内用服务名 scrapyd 直连）
# 1.6.0 支持两种写法：
#   字符串：'host:port' 或 'user:pass@host:port'（推荐，最简洁）
#   五元组：(用户名, 密码, host, 端口字符串, 分组) —— 顺序与老版本不同，
#           且端口必须是字符串，传 int 直接 AttributeError（已实测踩坑）
SCRAPYD_SERVERS = [
    'scrapyd:6800',
]

# 监控面板自身
ENABLE_HTTPS = False        # 本地学习环境不开 HTTPS（生产必开）
SCRAPYDWEB_HOST = '0.0.0.0'  # 容器内必须监听 0.0.0.0
SCRAPYDWEB_PORT = 5000

# 面板功能开关
ENABLE_AUTH = False         # 本地学习环境不开登录（生产必开：账号密码）
LANGUAGE = 'en'
# 多节点视图显示 jobs 运行状态（含定时任务）
SHOW_SCRAPYD_JOB_COLUMN = True
