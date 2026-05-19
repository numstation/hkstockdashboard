# SCSP神器 - 快速開始指南

## 🚀 一鍵啟動應用程式

### 方法 1: 雙擊啟動（最簡單）

1. 在 Finder 中找到 `launch_app.command` 檔案
2. **右鍵點擊** → 選擇「**打開**」
3. 如果出現「無法打開，因為它來自未識別的開發者」的提示：
   - 點擊「**取消**」
   - 再次右鍵點擊 → 選擇「**打開**」
   - 這次會出現「**打開**」按鈕，點擊它
4. 終端機視窗會自動打開，應用程式會自動啟動
5. 瀏覽器會自動打開 `http://127.0.0.1:5000`（如果沒有，請手動打開）

### 方法 2: 從終端機啟動

```bash
cd /Users/chrislau/Documents/IT/stocktracker
./launch_app.command
```

## 📋 使用前準備

1. **確保 FutuOpenD 已啟動並登入**
   - 應用程式會自動檢查，但請確保 FutuOpenD 正在運行

2. **首次使用可能需要安裝依賴**
   - 啟動器會自動檢查並提示安裝

## 🔄 版本管理

### 查看當前版本
```bash
cat version.txt
```

### 更新版本號碼

當您有新的更新想法時，可以使用版本更新腳本：

```bash
# 小更新（修復錯誤）
./update_version.sh patch

# 新增功能
./update_version.sh minor

# 重大變更
./update_version.sh major
```

或手動編輯：
1. 編輯 `version.txt` 檔案
2. 編輯 `app.py` 中的 `VERSION` 變數
3. 在 `VERSION_HISTORY.md` 中記錄更新內容

### 版本號碼格式

使用語義化版本號：`主版本號.次版本號.修訂號`

- **1.0.0** → **1.0.1**: 修復小錯誤
- **1.0.1** → **1.1.0**: 新增功能
- **1.1.0** → **2.0.0**: 重大變更

## 🛠️ 故障排除

### 無法雙擊啟動

執行以下命令設定權限：
```bash
chmod +x launch_app.command
```

### 連接錯誤

確保：
1. FutuOpenD 已啟動
2. FutuOpenD 已登入
3. 端口 11111 沒有被其他程式佔用

### 缺少套件

執行：
```bash
pip3 install -r requirements.txt
```

## 📝 檔案說明

- `launch_app.command` - 一鍵啟動器（雙擊即可啟動）
- `version.txt` - 版本號碼檔案
- `update_version.sh` - 版本更新腳本
- `VERSION_HISTORY.md` - 版本歷史記錄
- `app.py` - 主應用程式
- `templates/index.html` - 網頁介面

## 💡 提示

- 啟動器會自動檢查依賴和 FutuOpenD 狀態
- 應用程式運行時，終端機視窗會顯示日誌
- 按 `Ctrl+C` 可以停止應用程式
- 關閉終端機視窗也會停止應用程式
