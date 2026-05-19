# SCSP神器 - 啟動說明

## 一鍵啟動器使用說明

### 方法 1: 雙擊啟動（推薦）

1. 找到 `launch_app.command` 檔案
2. 右鍵點擊 → 選擇「打開」
3. 如果出現安全提示，選擇「打開」
4. 應用程式會自動啟動

### 方法 2: 從終端機啟動

```bash
cd /Users/chrislau/Documents/IT/stocktracker
./launch_app.command
```

### 首次使用設定

如果無法雙擊啟動，請執行以下命令設定權限：

```bash
chmod +x launch_app.command
```

### 版本管理

- 版本號碼儲存在 `version.txt` 檔案中
- 更新版本時，請修改 `version.txt` 和 `app.py` 中的版本號碼
- 建議使用語義化版本號：主版本號.次版本號.修訂號 (例如: 1.0.0)

### 系統需求

- macOS 10.13 或更高版本
- Python 3.6 或更高版本
- FutuOpenD 必須正在運行

### 故障排除

1. **無法啟動**: 檢查 Python 3 是否已安裝
2. **缺少套件**: 執行 `pip3 install -r requirements.txt`
3. **連接錯誤**: 確保 FutuOpenD 已啟動並登入
4. **端口被佔用**: 關閉其他正在運行的實例
