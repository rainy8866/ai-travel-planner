# 部署与运行指南

## 一、本地运行（开发调试）

1. 克隆仓库并进入目录

   ```bash
   git clone https://github.com/rainy8866/ai-travel-planner.git
   cd ai-travel-planner
   ```

2. （可选）创建虚拟环境

   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate
   # macOS/Linux: source .venv/bin/activate
   ```

3. 安装依赖

   ```bash
   pip install -r requirements.txt
   ```

4. 配置密钥

   ```bash
   cp .env.example .env
   # Windows PowerShell: Copy-Item .env.example .env
   ```

   编辑 `.env`，填入你自己的三个 Key：

   ```ini
   AMAP_KEY=你的高德Web服务key
   TIANDITU_KEY=你的天地图浏览器端key
   DEEPSEEK_KEY=你的DeepSeek key
   DEEPSEEK_BASE_URL=https://api.deepseek.com
   ```

   > `.env` 已被 `.gitignore` 忽略，不会进入版本库，请勿提交真实密钥。

5. 启动

   ```bash
   streamlit run app.py
   ```

   浏览器打开 `http://localhost:8501`。

## 二、如何申请三个 API Key

| 服务 | 用途 | 申请入口 | 说明 |
|------|------|---------|------|
| 高德地图 | POI 反查验证景点真实性 | https://lbs.amap.com （控制台→我的应用→Web 服务） | 个人实名认证后即可，免费额度够 Demo |
| 天地图 | 地图底图（矢量+注记） | https://www.tianditu.gov.cn （控制台→开发资源→申请 Key，选"浏览器端"） | 个人注册免费，实名后可用 |
| DeepSeek | 大模型生成店名与排版 | https://platform.deepseek.com | API Key 需在平台充值后获取 |

## 三、部署到 Streamlit Community Cloud（免费，推荐）

1. 先把仓库推送到你自己的 GitHub 账号：

   ```bash
   git push -u origin main
   ```

2. 打开 https://streamlit.io/cloud ，用 GitHub 账号登录。
3. 点 **New app** → 选你的仓库 → 入口文件填 `app.py` → **Deploy**。
4. 部署后进入 **Settings → Secrets**，添加环境变量（与 `.env` 相同）：

   ```ini
   AMAP_KEY=...
   TIANDITU_KEY=...
   DEEPSEEK_KEY=...
   DEEPSEEK_BASE_URL=https://api.deepseek.com
   ```

5. 重启应用，即可通过 `https://<你的账号>-<仓库名>.streamlit.app` 访问。

注意事项：
- Streamlit Cloud 免费版服务器在海外，国内访问可能较慢，首次冷启动约 10-20 秒属正常。
- 三个 Key 配额有限，多人高并发使用时请留意每日调用量，必要时在 `_config` 中加入缓存或限流。

## 四、故障排查

| 现象 | 可能原因 / 处理 |
|------|-----------------|
| 打开后进入"演示模式"提示 | `.env` 中 Key 缺失或无效，项目已自动降级为假数据演示，请核对 Key |
| 地图不显示文字 | 天地图 Key 未配置或已超配额，检查 `TIANDITU_KEY` |
| 无任何候选 | DeepSeek 或高德调用失败，查看 `log/errors.log` |
| 国内访问地图缓慢 | OSM 瓦片源在国内不稳定，配置了天地图 Key 后会自动优先使用天地图 |