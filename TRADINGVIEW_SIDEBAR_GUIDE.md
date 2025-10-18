# TradingView Charting Library 左侧边栏二次开发指南

## 理解 TradingView 的原生侧边栏结构

TradingView Charting Library 提供了两种侧边栏：
- **左侧边栏**：Object Tree（对象树）- 显示图表上所有的绘图对象、指标等
- **右侧边栏**：Watchlist、Details、News、Data Window 等面板

## 官方提供的侧边栏定制功能

### 1. Widget 配置选项

```javascript
const widget = new TradingView.widget({
    // 启用/禁用相关功能
    enabled_features: [
        'show_object_tree',           // 显示对象树（左侧边栏）
        'object_tree_legend_mode',    // 对象树图例模式
        'right_bar_stays_on_scroll',  // 右侧边栏固定
        'side_toolbar_in_fullscreen_mode',  // 全屏模式下显示侧边工具栏
    ],

    // 侧边栏相关配置
    left_toolbar: true,  // 显示左侧工具栏
    right_toolbar: true, // 显示右侧工具栏

    // 自定义侧边栏宽度
    widgetbar: {
        details: true,
        watchlist: true,
        watchlist_settings: {
            default_symbols: ["NASDAQ:AAPL", "NYSE:SPY"],
            readonly: false
        }
    },

    // 工具栏背景色
    toolbar_bg: '#f1f3f6',
});
```

### 2. 使用 Widget Methods 操作侧边栏

```javascript
// 获取 widget 实例后
widget.onChartReady(() => {
    const chart = widget.chart();

    // 控制左侧对象树
    chart.executeActionById("objectTree"); // 切换对象树显示/隐藏

    // 获取并操作右侧面板
    widget.activeChart().executeActionById("symbolSearch");
});
```

### 3. 自定义左侧边栏内容的方法

#### 方法 1：使用 Custom Indicators（推荐）
```javascript
// 创建自定义指标，会显示在对象树中
widget.onChartReady(() => {
    widget.chart().createStudy('Custom Indicator', false, false, {
        // 指标参数
    });
});
```

#### 方法 2：使用 Widget Constructor 扩展
```javascript
// 在 widget 初始化后注入自定义内容
widget.onChartReady(() => {
    // 获取 iframe 内容
    const iframeDocument = document.querySelector('#chartContainer iframe').contentDocument;

    // 查找对象树容器
    const objectTreeContainer = iframeDocument.querySelector('.object-tree-wrapper');

    if (objectTreeContainer) {
        // 注入自定义内容
        const customSection = document.createElement('div');
        customSection.className = 'custom-object-section';
        customSection.innerHTML = `
            <div class="custom-tools">
                <!-- 自定义工具内容 -->
            </div>
        `;
        objectTreeContainer.appendChild(customSection);
    }
});
```

#### 方法 3：使用 Custom CSS 注入
```javascript
const widget = new TradingView.widget({
    custom_css_url: './custom_styles.css',
    // 或使用内联样式
    loading_screen: {
        backgroundColor: "#000000",
        foregroundColor: "#ffffff",
    },
    // 通过 overrides 修改样式
    overrides: {
        "paneProperties.background": "#131722",
        "paneProperties.vertGridProperties.color": "#363c4e",
    }
});
```

### 4. 高级定制：Widget Constructor API

```javascript
// 扩展 Widget 构造函数
class CustomTradingViewWidget extends TradingView.widget {
    constructor(options) {
        super(options);
        this.customInit();
    }

    customInit() {
        this.onChartReady(() => {
            this.injectCustomPanel();
        });
    }

    injectCustomPanel() {
        // 自定义面板注入逻辑
        const customPanel = {
            name: 'Custom Analysis',
            content: this.createCustomContent(),
            position: 'left' // 或 'right'
        };

        // 注入到 widget 中
        this.addCustomPanel(customPanel);
    }

    createCustomContent() {
        return `
            <div class="custom-panel">
                <h3>Custom Analysis Tools</h3>
                <!-- 自定义工具内容 -->
            </div>
        `;
    }
}
```

### 5. 使用 Trading Terminal 特性（付费版本）

Trading Terminal 提供了更多的定制选项：

```javascript
const widget = new TradingView.TradingTerminal({
    // Trading Terminal 专有配置
    widgetbar: {
        details: true,
        watchlist: true,
        news: true,
        datawindow: true,

        // 自定义面板
        customTabs: [
            {
                id: 'custom_tab_1',
                title: 'My Analysis',
                content: '<div>Custom content</div>'
            }
        ]
    },

    // 左侧边栏配置
    left_toolbar: {
        visible: true,
        tools: [
            { id: 'custom_tool_1', icon: 'icon-url', action: customAction }
        ]
    }
});
```

## 二次开发限制和注意事项

### 官方支持的定制范围：
1. ✅ 启用/禁用原生功能
2. ✅ 修改样式和主题
3. ✅ 添加自定义指标和绘图工具
4. ✅ 通过 API 控制面板显示/隐藏
5. ✅ 监听事件和用户交互

### 不推荐或受限的操作：
1. ❌ 直接修改 iframe 内部 DOM（可能被更新覆盖）
2. ❌ 破坏原有功能逻辑
3. ❌ 违反许可协议的修改

## 推荐的实现方案

### 方案 1：保留原生对象树，添加浮动面板
```javascript
widget.onChartReady(() => {
    // 创建浮动的自定义面板
    const floatingPanel = widget.createButton();
    floatingPanel.setAttribute('title', 'Custom Tools');
    floatingPanel.textContent = '🛠';
    floatingPanel.addEventListener('click', () => {
        // 显示自定义工具面板
        showCustomToolsPanel();
    });
});
```

### 方案 2：使用 Widget 的扩展点
```javascript
// 利用 widget 提供的扩展点
widget.subscribe('drawing', (drawingId) => {
    // 当用户绘图时触发自定义逻辑
    updateCustomPanel(drawingId);
});

widget.subscribe('study_event', (studyId, eventName) => {
    // 当指标事件触发时更新自定义面板
});
```

### 方案 3：结合外部 UI 框架
```javascript
// 在 TradingView widget 外部创建独立的侧边栏
// 通过 API 与 widget 交互
const customSidebar = new CustomSidebar({
    onToolSelect: (tool) => {
        widget.chart().executeActionById(tool);
    },
    onIndicatorAdd: (indicator) => {
        widget.chart().createStudy(indicator);
    }
});

// 双向同步
widget.subscribe('onAutoSaveNeeded', () => {
    customSidebar.sync(widget.save());
});
```

## 实用代码示例

### 添加自定义工具到对象树
```javascript
widget.onChartReady(() => {
    // 方法1：添加自定义按钮到工具栏
    const customButton = widget.createButton();
    customButton.textContent = 'My Tool';
    customButton.addEventListener('click', () => {
        // 在对象树中添加自定义项
        const customObject = {
            type: 'custom',
            name: 'My Analysis',
            data: { /* 自定义数据 */ }
        };

        // 通过 widget API 添加
        widget.chart().createMultipointShape(
            [{time: Date.now(), price: 100}],
            {
                shape: 'icon',
                icon: 0x1F4CA,  // Unicode emoji
                text: 'Custom Marker'
            }
        );
    });

    // 方法2：监听对象树变化
    widget.subscribe('onObjectsChanged', (objects) => {
        console.log('Objects in tree:', objects);
        // 更新自定义面板
    });
});
```

### 获取和操作对象树内容
```javascript
widget.onChartReady(() => {
    const chart = widget.chart();

    // 获取所有图表对象
    const allShapes = chart.getAllShapes();
    const allStudies = chart.getAllStudies();

    // 创建自定义对象管理器
    class ObjectManager {
        constructor(widget) {
            this.widget = widget;
            this.objects = new Map();
        }

        syncWithObjectTree() {
            const shapes = this.widget.chart().getAllShapes();
            const studies = this.widget.chart().getAllStudies();

            // 同步到自定义面板
            this.updateCustomPanel([...shapes, ...studies]);
        }

        updateCustomPanel(objects) {
            // 更新自定义 UI
            const panel = document.getElementById('myCustomPanel');
            panel.innerHTML = objects.map(obj => `
                <div class="object-item">
                    <span>${obj.name}</span>
                    <button onclick="removeObject('${obj.id}')">删除</button>
                </div>
            `).join('');
        }
    }

    const objectManager = new ObjectManager(widget);

    // 定期同步
    setInterval(() => {
        objectManager.syncWithObjectTree();
    }, 1000);
});
```

## 总结

TradingView Charting Library 的左侧边栏（Object Tree）定制选项：

1. **基础定制**：通过配置项启用/禁用功能
2. **样式定制**：通过 CSS 和 overrides 修改外观
3. **功能扩展**：通过 API 添加自定义工具和指标
4. **深度定制**：结合外部 UI 框架实现完全自定义的侧边栏

建议根据具体需求选择合适的方案，优先使用官方 API，避免直接操作 DOM。