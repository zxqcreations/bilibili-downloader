# 📺 Bilibili 视频下载器

一个基于 Web 的 Bilibili 视频下载工具，支持下载视频、音频自动合并，以及弹幕抓取。

## 功能

- 🎬 解析 Bilibili 视频链接，获取视频信息（标题、封面、UP主、分P列表）
- 📥 下载 M4S 视频流和音频流，通过 FFmpeg 无损合并为 MP4
- 💬 下载弹幕（XML 格式），可统计弹幕数量和类型
- 🎛️ 画质选择（360P ~ 4K，高清需登录 Cookie）
- 📊 Web 界面实时显示下载进度
- 🍪 Cookie 持久化保存，一次粘贴多次使用

## 环境要求

- **Python** 3.10+
- **FFmpeg**（需提前安装）
- 操作系统：Windows / macOS / Linux

## 快速开始

### 1. 克隆项目

```bash
git clone <你的仓库地址>
cd bilibili-download
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 FFmpeg 路径

编辑 `downloader/downloader.py`，将 `FFMPEG_PATH` 修改为你本机的 FFmpeg 路径：

```python
FFMPEG_PATH = r"D:\ENV\ffmpeg-7.1-full_build\bin\ffmpeg.exe"
```

如果 FFmpeg 已在系统 PATH 中，可跳过此步骤。

### 4. 启动服务

```bash
python app.py
```

服务默认运行在 `http://127.0.0.1:8000`，浏览器打开即可使用。

## 使用说明

### 基本下载（360P/480P，无需登录）

1. 打开网页，粘贴 Bilibili 视频链接
2. 点击「解析」按钮
3. 选择画质，点击「开始下载」
4. 等待进度条完成，文件保存在 `downloads/` 目录

### 下载高清画质（720P/1080P/4K）

需要提供 Bilibili 的登录 Cookie：

1. 在浏览器中登录 [Bilibili](https://www.bilibili.com)
2. 按 `F12` → `Application` → `Cookies` → `bilibili.com`
3. 找到 `SESSDATA`，复制它的值
4. 在下载器页面点击 🍪 按钮，粘贴 `SESSDATA=你复制的内容`
5. 点击「解析」，高清画质选项将变为可选

> **提示：** Cookie 会自动保存到 `cookie.txt`，下次打开页面无需重新粘贴。该文件已加入 `.gitignore`，不会被上传到 Git。

### 多P视频

如果视频包含多个分P，解析后会出现选集下拉框，选择想要下载的分P即可。

### 弹幕

下载完成后，弹幕会以 XML 格式保存在视频同目录下，文件名相同、扩展名为 `.xml`。

## 项目结构

```
bilibili-download/
├── app.py                    # FastAPI 主程序（API 路由、SSE 进度推送）
├── requirements.txt          # Python 依赖
├── downloader/
│   ├── api_client.py         # Bilibili API 封装（视频信息/流地址/弹幕）
│   ├── wbi_sign.py           # WBI 签名算法
│   ├── downloader.py         # 下载流水线（M4S 下载 + FFmpeg 合并）
│   └── danmaku.py            # 弹幕下载与解析
├── static/
│   ├── index.html            # 前端页面
│   ├── style.css             # 界面样式
│   └── app.js                # 前端逻辑
├── downloads/                # 下载输出目录
└── temp/                     # 临时文件（自动清理）
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/parse` | 解析视频链接，返回元数据 |
| `POST` | `/api/download` | 创建下载任务，返回 task_id |
| `GET` | `/api/progress/{task_id}` | SSE 实时进度流 |
| `GET` | `/api/downloads` | 查看已下载文件列表 |
| `GET` | `/api/tasks` | 查看任务状态 |
| `GET` | `/api/cookie` | 读取已保存的 Cookie |
| `POST` | `/api/cookie` | 保存或清除 Cookie |

## 画质等级

| 画质 | 是否需要登录 | 是否需要 VIP |
|------|:----------:|:----------:|
| 360P / 480P | 否 | 否 |
| 720P / 1080P | 是 | 否 |
| 1080P+ / 1080P60 | 是 | 是 |
| 4K / HDR / 8K | 是 | 是 |

## 常见问题

**Q: 下载时报 "获取视频流信息" 后失败？**  
A: 检查网络连接，Bilibili API 可能需要稳定的网络环境。也有可能是 WBI 签名过期，重试即可。

**Q: FFmpeg 合并不成功？**  
A: 确认 `downloader/downloader.py` 中的 `FFMPEG_PATH` 配置正确，指向 `ffmpeg.exe` 的完整路径。

**Q: Cookie 复制后还是只能下载 480P？**  
A: 确保复制的是 `SESSDATA` 字段的值（不含 `SESSDATA=` 前缀需手动加上），格式为 `SESSDATA=xxxx%2Cxxxx`。

**Q: 视频文件名包含特殊字符？**  
A: 程序会自动过滤文件名中的非法字符（`<>:"/\|?*`），并用下划线替换。

## 免责声明

本工具仅供个人学习使用。请遵守 Bilibili 的用户协议和相关法律法规，不得用于商业用途或侵犯他人版权。
