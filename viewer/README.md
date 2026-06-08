# LLM 量化论文阅读页

## 功能
- 读取 `../papers_record.xlsx` 并转换为 `papers_data.json`
- 本地静态页面展示论文卡片
- 按日期区间筛选（抓取日期或发表日期）
- 支持关键词检索（标题/作者/单位/分类/摘要）
- 收藏保存在浏览器 `localStorage`，适合 GitHub Pages 纯静态部署

## 启动
在本目录执行：

```bash
python3 run_viewer.py
```

如果端口被占用，可换端口启动：

```bash
python3 run_viewer.py --port 7770
```

浏览器打开：

```text
http://127.0.0.1:8765
```

局域网设备可访问：

```text
http://<你的机器局域网IP>:8765
```

启动后终端会打印实际 LAN 访问地址。

## GitHub Pages 部署

`viewer/` 目录可以直接作为 GitHub Pages 的发布产物。

- `index.html`、`app.js`、`styles.css`、`papers_data.json` 会被部署到静态站点
- 收藏只保存在访问者当前浏览器，不做多设备同步
- 每次更新 `viewer/papers_data.json` 后执行：

```bash
bash scripts/publish_viewer.sh
```

推送成功后，GitHub Actions 会自动更新 Pages。

## 仅更新数据

```bash
python3 build_data.py
```
