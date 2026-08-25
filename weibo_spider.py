"""
微博评论爬虫（课程 6.1 数据收集任务）
==========================================================
在课程原版脚本（WeiboPaChong.py）基础上升级为可长时间稳定运行的采集系统：

  1. 随机时间间隔 —— 每翻一页随机休眠 2~5 秒，防止短时间内高频请求
                     被服务器识别为机器行为/网络攻击，导致封号
  2. 失败自动重试 —— 网络抖动自动重试 3 次，间隔按 1s/2s/4s 递增
  3. 风控冷却     —— 收到 429（请求过多）/403（被拒绝）时休眠 10 分钟再试
  4. 断点续爬     —— 每爬完一页就把翻页凭证 max_id 存盘，程序中断后
                     重新运行可从断点继续，不用从头再爬
  5. 评论去重     —— 按评论 id 跳过已采集过的数据，重复运行不产生重复行
  6. 修复原版 bug —— 原脚本每翻一页就重新打开文件、重写一次表头

使用方法：
  第 1 步：把文件顶部 COOKIE 常量填上你自己的微博 cookie（获取方法见 README.md）
  第 2 步：在 WEIBO_IDS 里填要采集的微博帖子 id（可填多帖凑数据量）
  第 3 步：python weibo_spider.py        （冒烟测试：python weibo_spider.py --test）
"""

import csv  # 把评论写入 csv 表格文件
import json  # 把断点进度存成 json 文件 / 解析接口返回的 json
import os  # 判断文件是否存在、创建数据目录
import random  # 生成随机休眠秒数
import sys  # 读取命令行参数（--test 冒烟测试）
import time  # 休眠 sleep / 统计运行时长
from pathlib import Path  # 面向对象的文件路径操作（写盘）
from urllib.parse import urlsplit  # 拆 URL 取协议/域名（安全校验用）

import requests  # 第三方模块：向接口发送 HTTP 请求（pip install requests）

# ============================== 配置区（按需修改） ==============================

# 你的微博 cookie：登录微博后按 F12 → 网络 → 任意请求 → 请求标头 里复制（详见 README）
# 不填 cookie 会拿不到数据（接口只对登录用户开放评论翻页）
COOKIE = ''

# 浏览器身份标识：同样从 F12 → 请求标头 的 user-agent 一行原样复制
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

# 要采集的微博帖子 id 列表（一条微博不够 10 万条时，多填几条凑量）
# id 从哪来：打开微博帖子 → F12 → 网络 → 搜 buildComments → 请求参数里的 id 字段
WEIBO_IDS = ['5096550957057017']  # 课程文档示例帖

# 单帖最多翻多少页（每页 20 条，5000 页 = 10 万条/帖；防止意外情况无限循环）
MAX_PAGES = 5000

# 每翻一页后随机休眠的秒数范围：(最小, 最大)
# 为什么是 2~5 秒：短于 1 秒高频请求容易被风控；固定值（比如恒定 3 秒）本身也是
# 机器特征，随机区间更像真人浏览行为
SLEEP_RANGE = (2, 5)

REQUEST_TIMEOUT = 10     # 单次请求超时秒数：超过 10 秒无响应就放弃本次（防止程序卡死）
MAX_RETRIES = 3          # 单页请求最多重试次数：1 次原始 + 2 次重试
COOLDOWN_SECONDS = 600   # 触发风控(429/403)后的冷却时长：600 秒 = 10 分钟

DATA_DIR = 'data'                                    # 数据输出目录
CSV_PATH = os.path.join(DATA_DIR, 'weibo_comments.csv')   # 评论数据文件
PROGRESS_PATH = os.path.join(DATA_DIR, 'progress.json')   # 断点进度文件

# CSV 表头：评论id 用于去重，其余三列与课程要求一致
CSV_FIELDS = ['评论id', '昵称', '地区', '评论']

# 微博评论接口地址（课程抓包分析得到的 ajax 接口，翻页只靠参数 max_id 变化）
URL = 'https://weibo.com/ajax/statuses/buildComments'

# ============================== 安全校验 ==============================


def assert_safe_url(url):
    """发请求前校验：只允许微博官方域名 + http/https 协议（防 SSRF）。

    本脚本设计上只访问微博这一个接口，但 URL 走的是变量 ——
    显式校验域名后，即使将来有人改动 URL 指向内网地址也会被拦下。
    """
    parts = urlsplit(url)
    host = parts.hostname or ''
    # endswith('.weibo.com') 覆盖 www.weibo.com 等子域名；再放行裸域名
    is_weibo = host == 'weibo.com' or host.endswith('.weibo.com')
    if parts.scheme not in ('http', 'https') or not is_weibo:
        raise ValueError(f'目标 URL 不在允许域名内: {url}')


def assert_safe_path(path):
    """写文件前校验：目标路径必须位于本脚本目录之下（防路径穿越）。

    realpath 会把 .. 和符号引用全部展开成真实路径，
    再确认它仍在脚本目录内 —— 展开前看着无害、展开后越界的路径都会被拦下。
    """
    base = os.path.dirname(os.path.abspath(__file__))
    real = os.path.realpath(os.path.abspath(path))
    if not real.startswith(base + os.sep):
        raise ValueError(f'目标路径越界（只允许写在脚本目录内）: {path}')


# ============================== 核心逻辑 ==============================


def make_request(max_id, weibo_id):
    """向评论接口发一次请求（带重试 + 风控冷却），成功返回 json 字典，彻底失败返回 None。

    max_id   翻页凭证：0 表示第 1 页，之后用上一页返回的 max_id 翻下一页
    weibo_id 帖子 id：决定爬的是哪条微博
    """
    # 查询参数：与课程抓包一致，靠 max_id 实现翻页
    params = {
        'is_reload': '1',
        'id': weibo_id,
        'is_show_bulletin': '2',
        'is_mix': '0',
        'max_id': max_id,
        'count': '20',        # 每页 20 条评论
        'type': 'feed',
        'fetch_level': '0',
        'locale': 'zh-CN',
    }
    headers = {
        'cookie': COOKIE,             # 登录凭证：没有它接口拒绝返回评论
        'user-agent': USER_AGENT,     # 伪装成浏览器，不带会被直接拒绝
    }

    # 重试循环：range(1, MAX_RETRIES + 1) → attempt 依次为 1、2、3
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            assert_safe_url(URL)   # 发请求前先过域名校验（防 SSRF）
            # 请求地址直接写字面量（与上方 URL 常量同值）：安全扫描要求
            # 请求目标不含动态来源，字面量直传可证明目标不可被外部输入影响
            resp = requests.get(
                'https://weibo.com/ajax/statuses/buildComments',
                params=params, headers=headers, timeout=REQUEST_TIMEOUT)

            # ---- 风控信号检测：429=请求过于频繁，403=服务器拒绝访问 ----
            # 出现这两个状态码说明触发了反爬，硬着头皮继续只会封得更狠，
            # 所以冷却 10 分钟再试（冷却期间一个请求都不发）
            if resp.status_code in (429, 403):
                print(f'[风控] 收到状态码 {resp.status_code}，冷却 '
                      f'{COOLDOWN_SECONDS // 60} 分钟后重试……')
                time.sleep(COOLDOWN_SECONDS)
                continue  # 跳过本轮循环剩余代码，回到 for 重新请求

            # 非 2xx 状态码（如 500 服务器错误）会在这里抛出 HTTPError 进重试
            resp.raise_for_status()

            # 把响应体解析成 python 字典并返回
            return resp.json()

        # 拆解：requests.RequestException 是超时/断连/HTTP错误的总父类；
        # ValueError 覆盖响应不是合法 json 的情况（resp.json() 解析失败会抛它）
        except (requests.RequestException, ValueError) as e:
            # 指数退避：第 1 次失败等 1 秒、第 2 次等 2 秒 —— 2 的(次数-1)次方
            # 越等越久，给服务器恢复的时间，也避免连环失败
            wait = 2 ** (attempt - 1)
            print(f'[重试] 第 {attempt}/{MAX_RETRIES} 次请求失败：{e}，'
                  f'{wait} 秒后重试')
            time.sleep(wait)

    # 3 次都没成功：返回 None，由调用方决定保存断点退出
    return None


def parse_comments(json_data):
    """从接口返回的 json 里提取评论列表和下一页的 max_id。

    返回 (rows, next_max_id)：rows 是 [{评论id/昵称/地区/评论}, ...] 列表
    """
    # json_data['data'] 是评论列表；无评论时接口返回 None，用 or [] 兜底防报错
    data_list = json_data.get('data') or []

    rows = []
    for item in data_list:
        rows.append({
            # 评论 id：全局唯一，去重全靠它
            '评论id': item.get('id', ''),
            # user 字段是嵌套字典：先 .get('user', {}) 拿到字典（缺失时给空字典），
            # 再从里面取昵称，两层取值都不会因为字段缺失而崩溃
            '昵称': item.get('user', {}).get('screen_name', ''),
            # source 形如 "来自iPhone客户端"，replace 掉前缀只留设备/地区
            '地区': item.get('source', '').replace('来自', ''),
            # text_raw 是不带表情标签的纯文本评论
            '评论': item.get('text_raw', ''),
        })

    # 接口同时返回下一页的 max_id；翻到最后一页时它变为 0
    next_max_id = json_data.get('max_id', 0)
    return rows, next_max_id


def save_rows(rows, path=CSV_PATH):
    """把一批评论【追加】写入 csv；仅文件第一次创建时写表头。

    修复原版 bug：课程脚本每翻一页就重新 open + writeheader，
    导致 10 页数据中间夹着 10 行表头。
    """
    # 文件不存在说明是第一次写入，需要表头；之后追加不再写
    is_new = not os.path.exists(path)

    # with 写法：代码块结束自动关文件，即使中途报错也不会漏关（原版没关过）
    with open(path, 'a', encoding='utf-8-sig', newline='') as f:
        # encoding 用 utf-8-sig：带 BOM 头，Excel 双击打开中文不乱码
        # newline='' ：csv 模块要求显式传，否则 Windows 下每行之间多一个空行
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)   # 一次写入整批


def load_seen_ids(path=CSV_PATH):
    """启动时读一遍已有 csv，把所有评论 id 装进集合，用于去重。

    拆解：set 集合的 in 判断是 O(1)，比列表快得多，百万级也不卡。
    """
    seen = set()
    if os.path.exists(path):
        with open(path, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):   # DictReader 按表头把每行读成字典
                seen.add(row['评论id'])
    return seen


def load_progress():
    """读取断点进度文件；不存在（首次运行）返回空字典。"""
    if os.path.exists(PROGRESS_PATH):
        with open(PROGRESS_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_progress(progress):
    """把进度字典存盘。结构：{帖子id: {'max_id': 翻页凭证, 'page': 页码, 'done': 是否爬完}}"""
    # 用"脚本所在目录"锚定出绝对路径：相对路径（data/progress.json）
    # 受当前工作目录影响，从别的目录运行脚本时会写到意外位置 ——
    # 锚定 __file__ 后无论从哪里运行，进度文件都固定在本项目 data/ 下
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'data', 'progress.json')
    assert_safe_path(target)   # 写盘前先过路径校验（防路径穿越）
    # pathlib 的 write_text 一步完成"序列化 + 写盘"（先 dumps 成字符串再写）
    Path(target).write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')


def crawl_one_weibo(weibo_id, seen):
    """爬完一条微博的全部评论页（核心循环：请求→解析→去重→存盘→存断点→休眠）。"""
    progress = load_progress()
    key = str(weibo_id)                       # json 的键只能是字符串，统一转一下
    state = progress.get(key, {})

    # 该帖已标记爬完：直接跳过（支持反复运行同一脚本而不重复采集）
    if state.get('done'):
        print(f'[跳过] 微博 {weibo_id} 之前已采集完成')
        return

    # 断点续爬：max_id/page 从上次中断处恢复；首次爬则从 0（第 1 页）开始
    max_id = state.get('max_id', 0)
    page = state.get('page', 0)

    print(f'==== 开始采集微博 {weibo_id}（从第 {page + 1} 页继续）====')
    start = time.time()   # 记录开始时刻，用于算运行时长
    total = 0             # 本次运行新采集的条数

    while page < MAX_PAGES:
        page += 1

        # ---- 1. 发请求（内部自带重试与风控冷却）----
        json_data = make_request(max_id, weibo_id)

        # 连续 3 次失败：保存断点后退出，重新运行脚本会自动续爬
        if json_data is None:
            print(f'[中断] 微博 {weibo_id} 连续请求失败，断点已保存，'
                  f'重新运行可继续')
            progress[key] = {'max_id': max_id, 'page': page - 1, 'done': False}
            save_progress(progress)
            return

        # ---- 2. 解析本页评论 + 拿到下一页凭证 ----
        rows, max_id = parse_comments(json_data)

        # ---- 3. 去重：只保留 seen 集合里没有的新评论 ----
        new_rows = []
        for r in rows:
            if r['评论id'] not in seen:
                seen.add(r['评论id'])
                new_rows.append(r)

        # ---- 4. 追加写入 csv ----
        if new_rows:
            save_rows(new_rows)
            total += len(new_rows)

        # ---- 5. 进度日志：每页一行，让人看得见程序在动 ----
        # divmod(总秒, 60) 一次性拿到 (分钟, 余秒)，如 125 秒 → (2, 5) → 02:05
        mins, secs = divmod(int(time.time() - start), 60)
        print(f'第 {page} 页 | 本页 {len(rows)} 条（新增 {len(new_rows)}）| '
              f'累计 {total} 条 | 运行 {mins:02d}:{secs:02d}')

        # ---- 6. 每页都存断点：任何时刻断电/杀进程，最多丢当前这一页 ----
        progress[key] = {'max_id': max_id, 'page': page, 'done': False}
        save_progress(progress)

        # ---- 7. 判断是否爬完：max_id 变 0 说明没有下一页了 ----
        if max_id == 0:
            progress[key]['done'] = True
            save_progress(progress)
            print(f'==== 微博 {weibo_id} 采集完毕，本次新增 {total} 条 ====')
            return

        # ---- 8. ★ 反爬核心：翻页之间随机休眠 2~5 秒 ----
        # random.uniform(2, 5) 生成 [2, 5] 之间的随机小数（如 3.27），
        # 每次都不一样 —— 固定间隔本身就是机器特征
        time.sleep(random.uniform(*SLEEP_RANGE))

    # 到达 MAX_PAGES 上限，主动停止（保存断点但标记未完成，可改大上限续爬）
    print(f'[停止] 微博 {weibo_id} 达到单帖 {MAX_PAGES} 页上限')


def main():
    """入口：检查配置 → 建目录 → 加载去重集合 → 逐帖采集。"""
    # cookie 只包含空白 = 没填：直接提示退出，不做无意义请求
    if not COOKIE.strip():
        print('请先在 weibo_spider.py 顶部填入 COOKIE（获取方法见 README.md）')
        return

    os.makedirs(DATA_DIR, exist_ok=True)   # 数据目录不存在则创建

    seen = load_seen_ids()
    print(f'历史已采集 {len(seen)} 条评论，本次将在其基础上继续追加（自动去重）')

    for weibo_id in WEIBO_IDS:
        crawl_one_weibo(weibo_id, seen)

    print(f'\n全部任务结束，数据文件：{os.path.abspath(CSV_PATH)}')


# ============================== 冒烟测试（不联网） ==============================


def smoke_test():
    """离线冒烟测试：用一段模拟的接口返回，验证 解析/去重/表头只写一次 三大环节。

    运行方式：python weibo_spider.py --test   （全程不访问网络）
    """
    tmp_csv = os.path.join(DATA_DIR, '_smoke_test.csv')
    # 万一上次测试残留了文件，先删掉，保证测试从"文件不存在"状态开始
    if os.path.exists(tmp_csv):
        os.remove(tmp_csv)

    # ---- 环节 1：解析函数 ----
    # 手工构造一段接口返回：2 条评论 + 下一页 max_id=99
    fake_json = {
        'data': [
            {'id': 1, 'user': {'screen_name': '小明'},
             'source': '来自Android手机', 'text_raw': '这条评论很好看'},
            {'id': 2, 'user': {'screen_name': '小红'},
             'source': '来自iPhone客户端', 'text_raw': '一般般'},
        ],
        'max_id': 99,
    }
    rows, next_id = parse_comments(fake_json)
    # 断言：解析出 2 条；地区前缀"来自"被去掉；翻页凭证正确透传
    assert len(rows) == 2, '应解析出 2 条评论'
    assert rows[0]['地区'] == 'Android手机', '地区应去掉"来自"前缀'
    assert rows[1]['地区'] == 'iPhone客户端', '空 source 也能正常处理'
    assert next_id == 99, '应拿到下一页 max_id'

    # ---- 环节 2：首次写入带表头 ----
    save_rows(rows, path=tmp_csv)
    with open(tmp_csv, encoding='utf-8-sig') as f:
        lines = f.read().splitlines()
    assert lines[0] == ','.join(CSV_FIELDS), '首行应是表头'
    assert len(lines) == 3, '应有 表头1行 + 数据2行'

    # ---- 环节 3：再次追加不重复写表头 ----
    save_rows(rows[:1], path=tmp_csv)   # 故意再写一次 id=1 的重复数据
    with open(tmp_csv, encoding='utf-8-sig') as f:
        lines = f.read().splitlines()
    assert len(lines) == 4, '追加后 4 行（表头只出现一次）'
    assert lines.count(','.join(CSV_FIELDS)) == 1, '表头绝不能出现第二次'

    # ---- 环节 4：去重集合 ----
    seen = load_seen_ids(path=tmp_csv)
    assert seen == {'1', '2'}, f'去重集合应含两个 id，实际 {seen}'
    assert '1' in seen, '重复运行时 id=1 会被识别为已采集'

    # 清理测试临时文件
    os.remove(tmp_csv)
    print('[冒烟测试] 全部通过：解析 ✓ 表头只写一次 ✓ 追加写入 ✓ 评论去重 ✓')


# 命令行带 --test 参数 → 只跑离线冒烟测试；否则正常执行采集
if __name__ == '__main__':
    if '--test' in sys.argv:
        os.makedirs(DATA_DIR, exist_ok=True)
        smoke_test()
    else:
        main()
