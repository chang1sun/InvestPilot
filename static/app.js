const { createApp, ref, computed, nextTick, watch, onMounted } = Vue;

createApp({
    delimiters: ['[[', ']]'],
    setup() {
        // 迁移旧的 localStorage key 到新的 key
        if (localStorage.getItem('quantAgentState') || localStorage.getItem('quantAgentPreferences')) {
            try {
                const oldState = JSON.parse(localStorage.getItem('quantAgentState') || localStorage.getItem('quantAgentPreferences') || '{}');
                localStorage.setItem('investPilotPreferences', JSON.stringify({
                    currentTab: oldState.currentTab,
                    currentLanguage: oldState.currentLanguage,
                    selectedModel: oldState.selectedModel
                }));
                localStorage.removeItem('quantAgentState'); // 删除旧 key
                localStorage.removeItem('quantAgentPreferences'); // 删除旧 key
            } catch (e) {
                console.warn('Failed to migrate old state:', e);
            }
        }
        
        // State Initialization with Persistence Check
        const getSavedPreferences = () => {
            try {
                return JSON.parse(localStorage.getItem('investPilotPreferences') || '{}');
            } catch {
                return {};
            }
        };
        
        const getSessionData = () => {
            try {
                return JSON.parse(sessionStorage.getItem('investPilotSession') || '{}');
            } catch {
                return {};
            }
        };
        
        const savedPreferences = getSavedPreferences();
        const sessionData = getSessionData();

        const currentTab = ref(savedPreferences.currentTab || 'tracking');
        const currentLanguage = ref(savedPreferences.currentLanguage || 'en');
        
        // Disclaimer Banner State
        const showDisclaimer = ref(!localStorage.getItem('disclaimerDismissed'));
        
        // Toast Notification
        const toastMessage = ref('');
        const toastType = ref('info'); // 'success', 'error', 'info'
        
        // Duplicate Task Dialog
        const showDuplicateTaskDialog = ref(false);
        const duplicateTaskInfo = ref({ symbol: '', task_id: '', created_at: '' });
        const pendingAnalysisSymbol = ref(null);
        
        // Loading States (Independent)
        const loadingAnalysis = ref(false);
        const loadingRecommend = ref(false);
        const loadingPortfolio = ref(false);
        const creatingTask = ref(false);

        // Stock Tracking State
        const loadingTracking = ref(false);
        const trackingRefreshing = ref(false);
        const trackingRunning = ref(false);
        const trackingSummary = ref(null);
        const trackingHoldings = ref([]);
        const trackingTransactions = ref([]);
        const trackingDecisions = ref([]);
        const trackingBenchmark = ref(null);
        const trackingChartRef = ref(null);
        let trackingChartInstance = null;
        const selectedDecision = ref(null);
        const expandedHoldingId = ref(null);
        
        // 从 sessionStorage 恢复会话数据（刷新页面时保留）
        const recCriteria = ref(sessionData.recCriteria || { market: 'Any', asset_type: 'STOCK', include_etf: 'false', capital: 'Any', risk: 'Any', frequency: 'Any' });
        const recommendationResult = ref(sessionData.recommendationResult || null);
        const portfolio = ref(sessionData.portfolio || { symbol: '', avg_price: '', percentage: '', asset_type: 'STOCK' });
        const portfolioResult = ref(sessionData.portfolioResult || null);
        
        const query = ref(sessionData.query || '');
        const selectedAssetType = ref('STOCK');
        const suggestions = ref([]);
        const klineSymbolSelected = ref(false); // Track if user selected from suggestions
        const klineAssetType = ref(sessionData.klineAssetType || 'STOCK'); // K线分析的资产类型
        const analysisResult = ref(sessionData.analysisResult || null);
        const chartRef = ref(null);
        let chartInstance = null;
        
        // Model Management
        const models = ref([]);
        const selectedModel = ref(savedPreferences.selectedModel || 'gemini-3-flash-preview');
        
        // Market Indices Dashboard
        const marketIndices = ref([]);
        const loadingMarketIndices = ref(false);
        const showTooltip = ref(null);
        const tooltipPosition = ref({ x: 0, y: 0 });
        
        // Hot Stocks Management
        const hotStocks = ref([]);
        const loadingHotStocks = ref(false);
        
        // Market News Management
        const marketNews = ref([]);
        const loadingMarketNews = ref(false);

        // Portfolio Management State
        const portfolios = ref([]);
        const loadingPortfolios = ref(false);
        const displayCurrency = ref('USD');
        const rates = ref({ USD_CNY: 7.2 }); // Default fallback
        const hideAmounts = ref(localStorage.getItem('investPilotHideAmounts') === 'false' ? false : true); // 从localStorage读取，默认隐藏
        const lastRefreshTime = ref(0); // 记录上次刷新时间（用于限频）
        const showAddTransactionModal = ref(false);
        const selectedPortfolio = ref(null);
        const searchType = ref('ALL');
        const transactionForm = ref({
            symbol: '',
            asset_type: 'STOCK',
            transaction_type: 'BUY',
            trade_date: new Date().toISOString().split('T')[0],
            price: '',
            quantity: '',
            total_amount: '',
            notes: '',
            currency: 'USD'
        });
        
        // Transaction symbol search
        const transactionSymbolSuggestions = ref([]);
        const transactionSymbolSelected = ref(false);
        
        // Portfolio expansion and transactions
        const expandedPortfolios = ref([]);
        const portfolioTransactions = ref({});
        const loadingTransactions = ref({});
        
        // Edit Mode
        const editMode = ref(false);
        const showEditTransactionModal = ref(false);
        const editingTransaction = ref(null);
        const editTransactionForm = ref({
            trade_date: '',
            price: '',
            quantity: '',
            notes: ''
        });
        const showEditCashModal = ref(false);
        const editingCash = ref(null);
        const editCashForm = ref({
            balance: ''
        });
        
        // Cash Management
        const showCashModal = ref(false);
        const cashForm = ref({
            transaction_type: 'BUY', // BUY = 入金, SELL = 出金
            trade_date: new Date().toISOString().split('T')[0],
            amount: '',
            notes: '',
            currency: 'USD'
        });
        
        // Portfolio Stats (v2.0 - Investment Return Tracking)
        const portfolioStats = ref({
            currency: 'USD',
            net_deposit: 0,           // 净入金
            total_market_value: 0,    // 总市值
            cash_balance: 0,          // 现金余额
            total_cost: 0,            // 总成本（不含现金）
            realized_pnl: 0,          // 已实现盈亏
            unrealized_pnl: 0,        // 未实现盈亏
            total_pnl: 0,             // 总盈亏
            total_return_rate: 0,     // 总收益率
            total_daily_change: 0     // 今日涨跌总金额
        });
        
        // Cash Flow Management (v2.0)
        const showCashFlowModal = ref(false);
        const cashFlowForm = ref({
            flow_type: 'DEPOSIT',
            flow_date: new Date().toISOString().split('T')[0],
            amount: '',
            currency: 'USD',
            notes: ''
        });
        const cashFlows = ref([]);
        
        // Computed: Group portfolios by asset type
        const portfoliosByType = computed(() => {
            const grouped = {
                CASH: [],
                STOCK: [],
                FUND_CN: [],
                BITCOIN: [],
                GOLD: []
            };
            portfolios.value.forEach(p => {
                if (!grouped[p.asset_type]) {
                    grouped[p.asset_type] = [];
                }
                grouped[p.asset_type].push(p);
            });
            return grouped;
        });
        
        // Computed: Total assets value (using current market value)
        const totalAssetsValue = computed(() => {
            return portfolios.value.reduce((sum, p) => {
                // Use value_in_usd for all assets to ensure proper currency conversion
                if (p.value_in_usd !== undefined) {
                    return sum + p.value_in_usd;
                }
                // Fallback for assets without value_in_usd
                if (p.asset_type === 'CASH') {
                    return sum + p.total_quantity;
                }
                // Use current_value if available, otherwise use total_cost
                return sum + (p.current_value || p.total_cost);
            }, 0);
        });
        
        // Computed: Total cost (original investment)
        const totalCost = computed(() => {
            return portfolios.value.reduce((sum, p) => {
                // For cash, use value_in_usd if available for proper currency conversion
                if (p.asset_type === 'CASH') {
                    if (p.value_in_usd !== undefined) {
                        return sum + p.value_in_usd;
                    }
                    return sum + p.total_quantity; // Fallback
                }
                return sum + p.total_cost;
            }, 0);
        });
        
        // Computed: Total profit/loss
        const totalProfitLoss = computed(() => {
            return portfolios.value.reduce((sum, p) => {
                if (p.asset_type === 'CASH') {
                    return sum + 0; // Cash has no profit/loss
                }
                return sum + (p.profit_loss || 0);
            }, 0);
        });
        
        // Computed: Total profit/loss percentage
        const totalProfitLossPercent = computed(() => {
            if (totalCost.value === 0) return 0;
            return (totalProfitLoss.value / totalCost.value) * 100;
        });
        
        // Computed: Displayed total assets (with currency conversion)
        const displayedTotalAssets = computed(() => {
            const usdValue = totalAssetsValue.value;
            const currency = displayCurrency.value;
            const rate = rates.value?.USD_CNY || 7.2;
            if (currency === 'CNY') {
                return usdValue * rate;
            }
            return usdValue;
        });
        
        // Computed: Displayed total profit/loss (with currency conversion)
        const displayedTotalProfitLoss = computed(() => {
            const usdValue = totalProfitLoss.value;
            if (displayCurrency.value === 'CNY') {
                const rate = rates.value?.USD_CNY || 7.2;
                return usdValue * rate;
            }
            return usdValue;
        });
        
        // Computed: Displayed total daily change (with currency conversion)
        const displayedTotalDailyChange = computed(() => {
            const usdValue = portfolioStats.value.total_daily_change || 0;
            if (displayCurrency.value === 'CNY') {
                const rate = rates.value?.USD_CNY || 7.2;
                return usdValue * rate;
            }
            return usdValue;
        });
        
        // User Authentication
        const currentUser = ref(null);
        const showLoginModal = ref(false);
        const isRegisterMode = ref(false);
        const showPassword = ref(false);
        const authError = ref('');
        const authLoading = ref(false);
        const showUserMenu = ref(false);
        const loginForm = ref({ nickname: '', email: '', password: '' });
        const sessionId = ref(localStorage.getItem('investPilotSessionId') || null);
        
        // Email confirmation dialog
        const showEmailConfirmDialog = ref(false);
        const emailConfirmInfo = ref({
            email: '',
            typo_suggestion: '',
            score: 0
        });
        
        // Task Management
        const tasks = ref([]);
        const taskListVisible = ref(false);
        const taskFilterStatus = ref(null); // null = all, 'running', 'completed', 'terminated', 'failed'
        const taskButtonRef = ref(null);
        const taskButtonPosition = ref({ x: 0, y: 0 });
        const isDragging = ref(false);
        const dragStartPos = ref({ x: 0, y: 0 });
        const taskStatusFilters = computed(() => {
            const isZh = currentLanguage.value === 'zh';
            return [
                { value: null, label: isZh ? '全部' : 'All' },
                { value: 'running', label: isZh ? '运行中' : 'Running' },
                { value: 'completed', label: isZh ? '已完成' : 'Completed' },
                { value: 'terminated', label: isZh ? '已终止' : 'Terminated' },
                { value: 'failed', label: isZh ? '失败' : 'Failed' }
            ];
        });
        let taskPollInterval = null;
        
        // Computed: Filtered tasks
        const filteredTasks = computed(() => {
            if (!tasks.value || !Array.isArray(tasks.value)) {
                return [];
            }
            if (!taskFilterStatus.value) {
                return tasks.value;
            }
            return tasks.value.filter(t => t.status === taskFilterStatus.value);
        });
        
        // Computed: Running tasks count
        const runningTasksCount = computed(() => {
            if (!tasks.value || !Array.isArray(tasks.value)) return 0;
            return tasks.value.filter(t => t.status === 'running').length;
        });
        
        // Load models from API
        const loadModels = async () => {
            try {
                const res = await fetch('/api/models');
                const modelList = await res.json();
                
                // Group models by provider
                const grouped = {};
                modelList.forEach(m => {
                    if (!grouped[m.provider]) {
                        grouped[m.provider] = [];
                    }
                    grouped[m.provider].push({
                        id: m.id,
                        name: m.name,
                        provider: m.provider,
                        supports_search: m.supports_search,
                        supports_tools: m.supports_tools || false,
                        status: 'normal'
                    });
                });
                
                // Flatten with provider labels
                const flattened = [];
                const providerOrder = ['gemini', 'openai', 'anthropic', 'xai', 'qwen', 'local'];
                const providerNames = {
                    'gemini': 'Google Gemini',
                    'openai': 'OpenAI GPT',
                    'anthropic': 'Anthropic Claude',
                    'xai': 'xAI Grok',
                    'qwen': 'Alibaba Qwen',
                    'local': 'Local Strategy'
                };
                
                providerOrder.forEach(provider => {
                    if (grouped[provider]) {
                        flattened.push({
                            id: `header_${provider}`,
                            name: `━━━ ${providerNames[provider]} ━━━`,
                            isHeader: true,
                            disabled: true
                        });
                        flattened.push(...grouped[provider]);
                    }
                });
                
                models.value = flattened;
                
                // Validate saved model
                const validIds = modelList.map(m => m.id);
                if (!validIds.includes(selectedModel.value)) {
                    console.warn(`Invalid saved model: ${selectedModel.value}, resetting to default`);
                    selectedModel.value = 'gemini-3-flash-preview';
                }
            } catch (err) {
                console.error('Failed to load models:', err);
                // Fallback to default models
                models.value = [
                    { id: 'gemini-3-flash-preview', name: 'Gemini 3 Flash (Preview)', status: 'normal' },
                    { id: 'local-strategy', name: 'Local Algo (MA+RSI)', status: 'normal' }
                ];
            }
        };
        
        // Load trending stocks from API
        const loadTrendingStocks = async () => {
            loadingHotStocks.value = true;
            try {
                const res = await fetch('/api/trending');
                if (res.ok) {
                    const trendingList = await res.json();
                    if (Array.isArray(trendingList)) {
                        hotStocks.value = trendingList;
                    } else {
                        console.error('Trending stocks data is not an array:', trendingList);
                        hotStocks.value = [];
                    }
                } else {
                    throw new Error('Failed to fetch trending stocks');
                }
            } catch (err) {
                console.error('Failed to load trending stocks:', err);
                // Fallback to default stocks
                hotStocks.value = [
                    { symbol: 'NVDA', name: 'NVIDIA', price: '$850', change: 2.5, volume: '50M', market: 'NASDAQ', trendData: '10,35 30,28 50,32 70,25 90,30' },
                    { symbol: 'TSLA', name: 'Tesla', price: '$245', change: -1.2, volume: '95M', market: 'NASDAQ', trendData: '10,15 30,18 50,22 70,25 90,20' },
                    { symbol: 'AAPL', name: 'Apple', price: '$195', change: 1.8, volume: '42M', market: 'NASDAQ', trendData: '10,28 30,25 50,30 70,27 90,32' },
                    { symbol: 'MSFT', name: 'Microsoft', price: '$420', change: 1.2, volume: '22M', market: 'NASDAQ', trendData: '10,25 30,22 50,28 70,24 90,30' },
                    { symbol: '600519.SS', name: '贵州茅台', price: '¥1,680', change: 0.5, volume: '1M', market: 'SSE', trendData: '10,20 30,23 50,19 70,25 90,22' },
                    { symbol: '0700.HK', name: '腾讯控股', price: 'HK$380', change: -0.8, volume: '18M', market: 'HKEX', trendData: '10,30 30,28 50,32 70,29 90,34' },
                    { symbol: '300750.SZ', name: '宁德时代', price: '¥235', change: 3.5, volume: '8M', market: 'SZSE', trendData: '10,35 30,32 50,37 70,34 90,38' },
                    { symbol: '9988.HK', name: '阿里巴巴', price: 'HK$90', change: 1.5, volume: '40M', market: 'HKEX', trendData: '10,22 30,25 50,20 70,27 90,24' }
                ];
            } finally {
                loadingHotStocks.value = false;
            }
        };
        
        // Load market indices for dashboard
        const loadMarketIndices = async () => {
            loadingMarketIndices.value = true;
            try {
                const res = await fetch('/api/market_indices');
                if (res.ok) {
                    const indicesList = await res.json();
                    if (Array.isArray(indicesList)) {
                        marketIndices.value = indicesList;
                    } else {
                        console.error('Market indices data is not an array:', indicesList);
                        throw new Error('Invalid data format');
                    }
                } else {
                    throw new Error('Failed to fetch market indices');
                }
            } catch (err) {
                console.error('Failed to load market indices:', err);
                // Fallback to default indices
                marketIndices.value = [
                    { symbol: '^GSPC', name: 'S&P 500', name_zh: '标普500', market: 'US', icon: '🇺🇸', price: '4,783.45', price_raw: 4783.45, change: 25.6, change_pct: 0.54, high: 4800.2, low: 4765.3, volume: '', trend_data: '0,35 25,32 50,38 75,34 100,40', is_up: true },
                    { symbol: '^NDX', name: 'NASDAQ 100', name_zh: '纳斯达克100', market: 'US', icon: '🇺🇸', price: '15,011.35', price_raw: 15011.35, change: 102.5, change_pct: 0.69, high: 15050.8, low: 14980.2, volume: '', trend_data: '0,30 25,28 50,35 75,32 100,38', is_up: true },
                    { symbol: '^HSI', name: 'Hang Seng Index', name_zh: '恒生指数', market: 'HK', icon: '🇭🇰', price: '16,543.21', price_raw: 16543.21, change: 125.5, change_pct: 0.76, high: 16600.0, low: 16500.0, volume: '', trend_data: '0,25 25,28 50,30 75,27 100,32', is_up: true },
                    { symbol: 'HSTECH.HK', name: 'Hang Seng Tech', name_zh: '恒生科技指数', market: 'HK', icon: '🇭🇰', price: '3,456.78', price_raw: 3456.78, change: -23.4, change_pct: -0.67, high: 3480.0, low: 3450.0, volume: '', trend_data: '0,30 25,28 50,25 75,27 100,24', is_up: false },
                    { symbol: '^N225', name: 'Nikkei 225', name_zh: '日经225', market: 'JP', icon: '🇯🇵', price: '33,464.17', price_raw: 33464.17, change: -156.2, change_pct: -0.46, high: 33650.5, low: 33420.8, volume: '', trend_data: '0,25 25,28 50,22 75,26 100,20', is_up: false },
                    { symbol: 'BTC-USD', name: 'Bitcoin', name_zh: '比特币', market: 'CRYPTO', icon: '₿', price: '$43,256.80', price_raw: 43256.80, change: 1250.3, change_pct: 2.98, high: 43500.0, low: 42800.5, volume: '25.3B', trend_data: '0,20 25,25 50,22 75,30 100,35', is_up: true }
                ];
            } finally {
                loadingMarketIndices.value = false;
            }
        };
        
        // Load market news from API
        const loadMarketNews = async () => {
            loadingMarketNews.value = true;
            try {
                const res = await fetch('/api/market_news');
                if (res.ok) {
                    const newsList = await res.json();
                    if (Array.isArray(newsList)) {
                        marketNews.value = newsList;
                    } else {
                        marketNews.value = [];
                    }
                } else {
                    marketNews.value = [];
                }
            } catch (err) {
                console.error('Failed to load market news:', err);
                marketNews.value = [];
            } finally {
                loadingMarketNews.value = false;
            }
        };

        // Load portfolios
        const loadPortfolios = async () => {
            if (!currentUser.value) return;
            
            // 尝试从缓存加载数据
            const cachedData = localStorage.getItem('portfolios_cache');
            const hasCachedData = cachedData && cachedData !== 'null';
            
            if (hasCachedData) {
                try {
                    const cached = JSON.parse(cachedData);
                    // 检查缓存是否属于当前用户
                    if (cached.userId === currentUser.value.id) {
                        portfolios.value = cached.portfolios || [];
                        if (cached.rates) {
                            rates.value = { ...rates.value, ...cached.rates };
                        }
                        if (cached.stats) {
                            portfolioStats.value = cached.stats;
                        }
                        // 有缓存时不显示加载状态
                        loadingPortfolios.value = false;
                    }
                } catch (err) {
                    console.error('Failed to parse cached data:', err);
                }
            } else {
                // 没有缓存时显示加载状态
                loadingPortfolios.value = true;
            }
            
            try {
                // 1. 快速加载基础数据（不含实时价格和名称）
                const res = await fetch('/api/portfolios', {
                    headers: { 'X-Session-ID': sessionId.value }
                });
                if (res.ok) {
                    const data = await res.json();
                    // 如果没有缓存，使用基础数据
                    if (!hasCachedData) {
                        portfolios.value = (data && Array.isArray(data.portfolios)) ? data.portfolios : [];
                        if (data.rates) {
                            rates.value = { ...rates.value, ...data.rates };
                        }
                    }
                }
            } catch (err) {
                console.error('Failed to load portfolios:', err);
                if (!hasCachedData) {
                    showToast('加载持仓失败', 'error');
                }
            } finally {
                loadingPortfolios.value = false;
            }
            
            // Load portfolio stats (v2.0) - 如果没有缓存才加载
            if (!hasCachedData) {
                await loadPortfolioStats();
            }
            
            // 2. 异步刷新实时数据（后台进行）
            refreshPortfoliosData();
        };
        
        // 异步刷新持仓数据（获取实时价格和标的名称）
        const refreshPortfoliosData = async () => {
            if (!currentUser.value) return;
            
            // 限频检查：30秒内只允许刷新一次
            const now = Date.now();
            const REFRESH_COOLDOWN = 30 * 1000; // 30秒
            if (now - lastRefreshTime.value < REFRESH_COOLDOWN) {
                return;
            }
            
            lastRefreshTime.value = now;
            
            try {
                const res = await fetch('/api/portfolios/refresh', {
                    headers: { 'X-Session-ID': sessionId.value }
                });
                if (res.ok) {
                    const data = await res.json();
                    portfolios.value = (data && Array.isArray(data.portfolios)) ? data.portfolios : [];
                    if (data.rates) {
                        rates.value = { ...rates.value, ...data.rates };
                    }
                    
                    // 刷新统计数据
                    await loadPortfolioStats();
                    
                    // 保存到缓存
                    try {
                        const cacheData = {
                            userId: currentUser.value.id,
                            portfolios: portfolios.value,
                            rates: rates.value,
                            stats: portfolioStats.value,
                            timestamp: Date.now()
                        };
                        localStorage.setItem('portfolios_cache', JSON.stringify(cacheData));
                    } catch (err) {
                        console.error('Failed to cache portfolios:', err);
                    }
                    
                    // 显示美观的提示通知
                    showRefreshNotification();
                }
            } catch (err) {
                console.error('Failed to refresh portfolios:', err);
            }
        };
        
        // 显示刷新完成通知
        const showRefreshNotification = () => {
            // 创建通知元素
            const notification = document.createElement('div');
            notification.className = 'fixed top-20 right-4 bg-gradient-to-r from-green-500 to-emerald-600 text-white px-6 py-3 rounded-lg shadow-lg flex items-center gap-3 z-50 animate-slide-in-right';
            notification.innerHTML = `
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                <span class="font-medium">${currentLanguage.value === 'zh' ? '已获取实时数据' : 'Real-time data updated'}</span>
            `;
            
            document.body.appendChild(notification);
            
            // 3秒后自动消失
            setTimeout(() => {
                notification.style.opacity = '0';
                notification.style.transform = 'translateX(100%)';
                notification.style.transition = 'all 0.3s ease-out';
                setTimeout(() => {
                    document.body.removeChild(notification);
                }, 300);
            }, 3000);
        };
        
        // Load portfolio statistics (v2.0 - Investment Return Tracking)
        const loadPortfolioStats = async () => {
            if (!currentUser.value) return;
            
            try {
                const currency = displayCurrency.value || 'USD';
                const res = await fetch(`/api/portfolio-stats?currency=${currency}`, {
                    headers: { 'X-Session-ID': sessionId.value }
                });
                if (res.ok) {
                    const data = await res.json();
                    portfolioStats.value = data;
                    // 确保总收益率是数字类型
                    if (typeof portfolioStats.value.total_return_rate !== 'number') {
                        console.warn('⚠️ 总收益率不是数字类型:', portfolioStats.value.total_return_rate);
                        portfolioStats.value.total_return_rate = parseFloat(portfolioStats.value.total_return_rate) || 0;
                    }
                    
                    // 计算今日涨跌总金额
                    let totalDailyChange = 0;
                    portfolios.value.forEach(p => {
                        if (p.daily_change_percent !== null && p.daily_change_percent !== undefined && p.current_price && p.total_quantity) {
                            const dailyChangeAmount = p.current_price * p.daily_change_percent / 100 * p.total_quantity;
                            const dailyChangeInUSD = dailyChangeAmount * (p.exchange_rate || 1);
                            totalDailyChange += dailyChangeInUSD;
                        }
                    });
                    portfolioStats.value.total_daily_change = totalDailyChange;
                } else {
                    // 处理错误响应
                    const errorData = await res.json().catch(() => ({ error: '获取持仓统计数据失败' }));
                    const errorMsg = errorData.error || '获取持仓统计数据失败';
                    const details = errorData.details || [];
                    
                    // 显示错误提示
                    alert(`${errorMsg}\n\n${details.length > 0 ? '详细信息：\n' + details.join('\n') : ''}`);
                    console.error('Failed to load portfolio stats:', errorData);
                }
            } catch (err) {
                console.error('Failed to load portfolio stats:', err);
                alert('获取持仓统计数据时发生网络错误，请稍后重试');
            }
        };
        
        // Load cash flows (v2.0)
        const loadCashFlows = async () => {
            if (!currentUser.value) return;
            
            try {
                const currency = displayCurrency.value || 'USD';
                const res = await fetch(`/api/cash-flows?currency=${currency}`, {
                    headers: { 'X-Session-ID': sessionId.value }
                });
                if (res.ok) {
                    const data = await res.json();
                    cashFlows.value = data.cash_flows || [];
                }
            } catch (err) {
                console.error('Failed to load cash flows:', err);
            }
        };
        
        // Open cash flow modal (v2.0)
        const openCashFlowModal = () => {
            cashFlowForm.value = {
                flow_type: 'DEPOSIT',
                flow_date: new Date().toISOString().split('T')[0],
                amount: '',
                currency: displayCurrency.value || 'USD',
                notes: ''
            };
            showCashFlowModal.value = true;
        };
        
        // Submit cash flow (v2.0)
        const submitCashFlow = async () => {
            if (!cashFlowForm.value.amount || parseFloat(cashFlowForm.value.amount) <= 0) {
                showToast(currentLanguage.value === 'zh' ? '请输入有效金额' : 'Please enter a valid amount', 'error');
                return;
            }
            
            try {
                const res = await fetch('/api/cash-flows', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Session-ID': sessionId.value
                    },
                    body: JSON.stringify(cashFlowForm.value)
                });
                
                if (res.ok) {
                    const successMsg = cashFlowForm.value.flow_type === 'DEPOSIT' 
                        ? (currentLanguage.value === 'zh' ? '入金成功' : 'Deposit successful')
                        : (currentLanguage.value === 'zh' ? '出金成功' : 'Withdrawal successful');
                    showToast(successMsg, 'success');
                    showCashFlowModal.value = false;
                    
                    // Refresh data
                    await loadPortfolios();
                    await loadCashFlows();
                } else {
                    const error = await res.json();
                    showToast(error.error || (currentLanguage.value === 'zh' ? '操作失败' : 'Operation failed'), 'error');
                }
            } catch (err) {
                console.error('Cash flow error:', err);
                showToast(currentLanguage.value === 'zh' ? '操作失败' : 'Operation failed', 'error');
            }
        };
        
        // Delete cash flow (v2.0)
        const deleteCashFlow = async (cashFlowId) => {
            if (!confirm(currentLanguage.value === 'zh' ? '确定要删除这条资金流水吗？' : 'Are you sure you want to delete this cash flow?')) {
                return;
            }
            
            try {
                const res = await fetch(`/api/cash-flows/${cashFlowId}`, {
                    method: 'DELETE',
                    headers: { 'X-Session-ID': sessionId.value }
                });
                
                if (res.ok) {
                    showToast(currentLanguage.value === 'zh' ? '删除成功' : 'Deleted successfully', 'success');
                    await loadCashFlows();
                    await loadPortfolioStats();
                    await loadPortfolios();
                } else {
                    const error = await res.json();
                    showToast(error.error || (currentLanguage.value === 'zh' ? '删除失败' : 'Delete failed'), 'error');
                }
            } catch (err) {
                console.error('Delete cash flow error:', err);
                showToast(currentLanguage.value === 'zh' ? '删除失败' : 'Delete failed', 'error');
            }
        };

        // Calculate total amount based on price and quantity
        const calculateTotal = () => {
            if (transactionForm.value.price && transactionForm.value.quantity) {
                transactionForm.value.total_amount = (parseFloat(transactionForm.value.price) * parseFloat(transactionForm.value.quantity)).toFixed(2);
            }
        };

        // Calculate quantity based on price and total amount
        const calculateQuantity = () => {
            if (transactionForm.value.price && transactionForm.value.total_amount) {
                transactionForm.value.quantity = (parseFloat(transactionForm.value.total_amount) / parseFloat(transactionForm.value.price)).toFixed(4);
            }
        };

        // Toggle display currency
        const toggleCurrency = () => {
            console.log('Before toggle:', displayCurrency.value);
            console.log('totalAssetsValue:', totalAssetsValue.value);
            console.log('rates:', rates.value);
            displayCurrency.value = displayCurrency.value === 'USD' ? 'CNY' : 'USD';
            console.log('After toggle:', displayCurrency.value);
            console.log('displayedTotalAssets:', displayedTotalAssets.value);
        };

        // 新增：切换金额显示/隐藏
        const toggleAmountVisibility = () => {
            hideAmounts.value = !hideAmounts.value;
            // 保存状态到localStorage
            localStorage.setItem('investPilotHideAmounts', hideAmounts.value.toString());
        };

        // 新增：遮罩金额显示
        const maskAmount = (value) => {
            if (!hideAmounts.value) {
                return formatNumber(value);
            }
            // 统一显示 3 个星号，避免泄露金额大小信息
            return '***';
        };

        // Add transaction
        const addTransaction = async () => {
            if (!transactionForm.value.symbol || !transactionForm.value.price || (!transactionForm.value.quantity && !transactionForm.value.total_amount)) {
                showToast('请填写完整信息', 'error');
                return;
            }
            
            try {
                const res = await fetch('/api/transactions', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Session-ID': sessionId.value
                    },
                    body: JSON.stringify(transactionForm.value)
                });
                
                if (res.ok) {
                    const data = await res.json();
                    showToast('交易记录添加成功', 'success');
                    showAddTransactionModal.value = false;
                    
                    // Reset form
                    transactionForm.value = {
                        symbol: '',
                        asset_type: 'STOCK',
                        transaction_type: 'BUY',
                        trade_date: new Date().toISOString().split('T')[0],
                        price: '',
                        quantity: '',
                        total_amount: '',
                        notes: '',
                        currency: 'USD'
                    };
                    
                    // Reload portfolios and stats
                    await loadPortfolios();
                    await loadPortfolioStats();                        } else {
                    const error = await res.json();
                    showToast(error.error || '添加失败', 'error');
                }
            } catch (err) {
                console.error('Failed to add transaction:', err);
                showToast('添加交易记录失败', 'error');
            }
        };

        // Open edit transaction modal
        const openEditTransactionModal = (transaction, portfolioId) => {
            editingTransaction.value = { ...transaction, portfolioId };
            editTransactionForm.value = {
                trade_date: transaction.trade_date,
                price: transaction.price,
                quantity: transaction.quantity,
                notes: transaction.notes || ''
            };
            showEditTransactionModal.value = true;
        };

        // Update transaction
        const updateTransaction = async () => {
            if (!editingTransaction.value || !editTransactionForm.value.price || !editTransactionForm.value.quantity) {
                showToast(currentLanguage.value === 'zh' ? '请填写完整信息' : 'Please fill in all required fields', 'error');
                return;
            }
            
            const portfolioId = editingTransaction.value.portfolioId;
            const transactionId = editingTransaction.value.id;
            
            try {
                const res = await fetch(`/api/transactions/${transactionId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Session-ID': sessionId.value
                    },
                    body: JSON.stringify(editTransactionForm.value)
                });
                
                if (res.ok) {
                    showToast(currentLanguage.value === 'zh' ? '交易记录已更新' : 'Transaction updated', 'success');
                    showEditTransactionModal.value = false;
                    editingTransaction.value = null;
                    
                    // Reload portfolios and transactions
                    await loadPortfolios();
                    await loadPortfolioStats();
                    if (portfolioId) {
                        await loadPortfolioTransactions(portfolioId);
                    }
                } else {
                    const error = await res.json();
                    showToast(error.error || (currentLanguage.value === 'zh' ? '更新失败' : 'Update failed'), 'error');
                }
            } catch (err) {
                console.error('Failed to update transaction:', err);
                showToast(currentLanguage.value === 'zh' ? '更新交易记录失败' : 'Failed to update transaction', 'error');
            }
        };

        // Delete transaction
        const deleteTransaction = async (transactionId, portfolioId) => {
            if (!confirm(currentLanguage.value === 'zh' ? '确定要删除这条交易记录吗？' : 'Are you sure you want to delete this transaction?')) {
                return;
            }
            
            try {
                const res = await fetch(`/api/transactions/${transactionId}`, {
                    method: 'DELETE',
                    headers: {
                        'X-Session-ID': sessionId.value
                    }
                });
                
                if (res.ok) {
                    showToast(currentLanguage.value === 'zh' ? '交易记录已删除' : 'Transaction deleted', 'success');
                    
                    // Reload portfolios and transactions
                    await loadPortfolios();
                    await loadPortfolioStats();
                    await loadPortfolioTransactions(portfolioId);
                } else {
                    const error = await res.json();
                    showToast(error.error || (currentLanguage.value === 'zh' ? '删除失败' : 'Delete failed'), 'error');
                }
            } catch (err) {
                console.error('Failed to delete transaction:', err);
                showToast(currentLanguage.value === 'zh' ? '删除交易记录失败' : 'Failed to delete transaction', 'error');
            }
        };

        // Open edit cash modal
        const openEditCashModal = (cashPortfolio) => {
            editingCash.value = cashPortfolio;
            editCashForm.value.balance = cashPortfolio.total_quantity;
            showEditCashModal.value = true;
        };

        // Update cash balance
        const updateCashBalance = async () => {
            if (!editingCash.value || !editCashForm.value.balance) {
                showToast(currentLanguage.value === 'zh' ? '请输入新余额' : 'Please enter new balance', 'error');
                return;
            }
            
            const newBalance = parseFloat(editCashForm.value.balance);
            if (isNaN(newBalance) || newBalance < 0) {
                showToast(currentLanguage.value === 'zh' ? '余额必须为非负数' : 'Balance must be non-negative', 'error');
                return;
            }
            
            try {
                const res = await fetch(`/api/portfolios/${editingCash.value.id}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Session-ID': sessionId.value
                    },
                    body: JSON.stringify({
                        total_quantity: newBalance
                    })
                });
                
                if (res.ok) {
                    showToast(currentLanguage.value === 'zh' ? '现金余额已更新' : 'Cash balance updated', 'success');
                    showEditCashModal.value = false;
                    editingCash.value = null;
                    
                    // Reload portfolios and stats
                    await loadPortfolios();
                    await loadPortfolioStats();
                } else {
                    const error = await res.json();
                    showToast(error.error || (currentLanguage.value === 'zh' ? '更新失败' : 'Update failed'), 'error');
                }
            } catch (err) {
                console.error('Failed to update cash balance:', err);
                showToast(currentLanguage.value === 'zh' ? '更新现金余额失败' : 'Failed to update cash balance', 'error');
            }
        };

        // Open add transaction modal
        const openAddTransactionModal = (portfolio = null) => {
            if (portfolio) {
                transactionForm.value.symbol = portfolio.symbol;
                transactionForm.value.asset_type = portfolio.asset_type;
                transactionForm.value.currency = portfolio.currency;
                transactionSymbolSelected.value = true;
            } else {
                transactionSymbolSelected.value = false;
            }
            transactionSymbolSuggestions.value = [];
            showAddTransactionModal.value = true;
        };
        
        // Handle transaction symbol search
        let transactionSearchTimeout = null;
        const handleTransactionSymbolSearch = (e) => {
            const val = e.target.value;
            if (val.length < 1) {
                transactionSymbolSuggestions.value = [];
                transactionSymbolSelected.value = false;
                return;
            }
            
            if (transactionSymbolSelected.value) {
                return; // Don't search if already selected
            }
            
            // Clear previous timeout
            if (transactionSearchTimeout) {
                clearTimeout(transactionSearchTimeout);
            }
            
            // Set new timeout for debounce
            transactionSearchTimeout = setTimeout(async () => {
                try {
                    const res = await fetch(`/api/search?q=${val}&type=${searchType.value}`);
                    transactionSymbolSuggestions.value = await res.json();
                } catch (err) {
                    console.error(err);
                }
            }, 300);
        };
        
        // Select transaction symbol from suggestions
        const selectTransactionSymbol = async (item) => {
            transactionForm.value.symbol = item.symbol;
            transactionForm.value.asset_type = item.type || 'STOCK';
            if (item.type === 'FUND_CN') {
                transactionForm.value.currency = 'CNY';
            }
            transactionForm.value.trade_date = new Date().toISOString().split('T')[0];
            transactionSymbolSuggestions.value = [];
            transactionSymbolSelected.value = true;
            
            // Auto-fetch current price
            try {
                const res = await fetch(`/api/current-price?symbol=${item.symbol}&asset_type=${item.type || 'STOCK'}`);
                if (res.ok) {
                    const data = await res.json();
                    transactionForm.value.price = data.price;
                }
            } catch (err) {
                console.error('Failed to fetch current price:', err);
                // If price fetch fails, leave price empty for user to input
            }
        };
        
        // Clear transaction symbol selection
        const clearTransactionSymbol = () => {
            transactionForm.value.symbol = '';
            transactionForm.value.asset_type = 'STOCK';
            transactionForm.value.price = '';
            transactionForm.value.trade_date = new Date().toISOString().split('T')[0];
            transactionSymbolSelected.value = false;
            transactionSymbolSuggestions.value = [];
        };
        
        // Open cash modal
        const openCashModal = () => {
            showCashModal.value = true;
        };
        
        // Add cash transaction
        const addCashTransaction = async () => {
            if (!cashForm.value.amount) {
                showToast(currentLanguage.value === 'zh' ? '请填写金额' : 'Please enter amount', 'error');
                return;
            }
            
            try {
                const res = await fetch('/api/transactions', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Session-ID': sessionId.value
                    },
                    body: JSON.stringify({
                        symbol: 'CASH',
                        asset_type: 'CASH',
                        transaction_type: cashForm.value.transaction_type,
                        trade_date: cashForm.value.trade_date,
                        price: 1, // 现金价格固定为1
                        quantity: parseFloat(cashForm.value.amount),
                        notes: cashForm.value.notes,
                        currency: cashForm.value.currency
                    })
                });
                
                if (res.ok) {
                    const data = await res.json();
                    showToast(
                        currentLanguage.value === 'zh' 
                            ? (cashForm.value.transaction_type === 'BUY' ? '入金成功' : '出金成功')
                            : (cashForm.value.transaction_type === 'BUY' ? 'Deposit successful' : 'Withdrawal successful'),
                        'success'
                    );
                    showCashModal.value = false;
                    
                    // Reset form
                    cashForm.value = {
                        transaction_type: 'BUY',
                        trade_date: new Date().toISOString().split('T')[0],
                        amount: '',
                        notes: '',
                        currency: 'USD'
                    };
                    
                    // Refresh portfolios
                    await loadPortfolios();
                } else {
                    const error = await res.json();
                    showToast(error.error || (currentLanguage.value === 'zh' ? '操作失败' : 'Operation failed'), 'error');
                }
            } catch (err) {
                console.error('Failed to add cash transaction:', err);
                showToast(currentLanguage.value === 'zh' ? '操作失败' : 'Operation failed', 'error');
            }
        };
        
        // Toggle portfolio expand/collapse
        const togglePortfolioExpand = async (portfolioId) => {
            const index = expandedPortfolios.value.indexOf(portfolioId);
            if (index > -1) {
                // Collapse
                expandedPortfolios.value.splice(index, 1);
            } else {
                // Expand and load transactions
                expandedPortfolios.value.push(portfolioId);
                await loadPortfolioTransactions(portfolioId);
            }
        };
        
        // Load transactions for a portfolio
        const loadPortfolioTransactions = async (portfolioId) => {
            if (!currentUser.value) return;
            
            // Find the portfolio object
            const portfolio = portfolios.value.find(p => p.id === portfolioId);
            if (!portfolio) {
                console.error('Portfolio not found:', portfolioId);
                return;
            }
            
            loadingTransactions.value[portfolioId] = true;
            try {
                // Build query parameters
                const params = new URLSearchParams({
                    asset_type: portfolio.asset_type || 'STOCK'
                });
                if (portfolio.currency) {
                    params.append('currency', portfolio.currency);
                }
                
                const res = await fetch(`/api/portfolios/${portfolio.symbol}/transactions?${params.toString()}`, {
                    headers: { 'X-Session-ID': sessionId.value }
                });
                if (res.ok) {
                    const data = await res.json();
                    portfolioTransactions.value[portfolioId] = data.transactions || [];
                }
            } catch (err) {
                console.error('Failed to load transactions:', err);
            } finally {
                loadingTransactions.value[portfolioId] = false;
            }
        };
        
        // Format number with commas
        const formatNumber = (num) => {
            if (num === null || num === undefined) return '0';
            const n = parseFloat(num);
            if (isNaN(n)) return '0';
            return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        };
        
        // Calculate allocation percentage
        const calculateAllocation = (value) => {
            const total = totalAssetsValue.value;
            if (total === 0) return '0.00';
            return ((value / total) * 100).toFixed(2);
        };
        
        // Trade Expansion State
        const expandedTrades = ref({});
const showToolCalls = ref(false);  // Toggle for agent tool call trace panel
const showRecommendToolCalls = ref(true);  // Toggle for recommend agent trace panel (default open)
        
        // All transaction records (AI signals + user transactions)
        const allTransactionRecords = ref([]);

        // --- Computed Properties ---

        const currentModelStatus = computed(() => {
            const m = models.value.find(m => m.id === selectedModel.value);
            return m ? m.status : 'normal';
        });

        const selectedModelName = computed(() => {
            const m = models.value.find(m => m.id === selectedModel.value);
            return m ? m.name : '';
        });

        // Filter models based on tab
        const availableModels = computed(() => {
            let filtered = models.value;
            
            if (currentTab.value === 'recommend') {
                // Disable local strategy for recommendation tab
                filtered = filtered.map(m => {
                    if (m.id === 'local-strategy') {
                        return { ...m, disabled: true };
                    }
                    return m;
                });
            }
            
            return filtered;
        });

        // Computed Stats
        const stats = computed(() => {
            if (!analysisResult.value) return {};
            const trades = analysisResult.value.analysis.trades || [];
            const totalTrades = trades.length;
            
            let winCount = 0;
            let totalReturnVal = 0.0;
            let unrealizedReturnVal = 0.0;
            let closedCount = 0;
            let isHolding = false;

            trades.forEach(t => {
                if (t.status === 'CLOSED') {
                    closedCount++;
                    const rateStr = t.return_rate.replace('%', '');
                    const rate = parseFloat(rateStr);
                    if (!isNaN(rate)) {
                        totalReturnVal += rate;
                        if (rate > 0) winCount++;
                    }
                } else if (t.status === 'HOLDING') {
                    isHolding = true;
                    const rateStr = t.return_rate.split('%')[0];
                    const rate = parseFloat(rateStr);
                    if (!isNaN(rate)) {
                        unrealizedReturnVal += rate;
                    }
                }
            });

            const winRate = closedCount > 0 ? Math.round((winCount / closedCount) * 100) : 0;
            
            return {
                totalTrades,
                winRate,
                totalReturn: totalReturnVal.toFixed(1),
                unrealizedReturn: unrealizedReturnVal.toFixed(1),
                currentStatus: isHolding ? (currentLanguage.value === 'zh' ? '持仓中' : 'HOLDING') : (currentLanguage.value === 'zh' ? '空仓' : 'EMPTY')
            };
        });

        // Computed: Current Portfolio for Analysis
        const currentPortfolio = computed(() => {
            if (!query.value) return null;
            return portfolios.value.find(p => p.symbol === query.value);
        });

        // --- Persistence & Watchers ---

        // 保存用户偏好设置到 localStorage（永久保存）
        watch(
            [currentTab, currentLanguage, selectedModel],
            () => {
                const preferences = {
                    currentTab: currentTab.value,
                    currentLanguage: currentLanguage.value,
                    selectedModel: selectedModel.value
                };
                localStorage.setItem('investPilotPreferences', JSON.stringify(preferences));
            },
            { deep: true }
        );
        
        // 保存会话数据到 sessionStorage（刷新保留，关闭标签页清除）
        watch(
            [recCriteria, recommendationResult, portfolio, portfolioResult, query, analysisResult],
            () => {
                const sessionData = {
                    recCriteria: recCriteria.value,
                    recommendationResult: recommendationResult.value,
                    portfolio: portfolio.value,
                    portfolioResult: portfolioResult.value,
                    query: query.value,
                    analysisResult: analysisResult.value
                };
                sessionStorage.setItem('investPilotSession', JSON.stringify(sessionData));
            },
            { deep: true }
        );

        // Auto-switch model if invalid for current tab
        watch(currentTab, (newTab) => {
            if (newTab === 'recommend' && selectedModel.value === 'local-strategy') {
                selectedModel.value = 'models/gemini-3-flash-preview';
            }
            if (newTab === 'portfolio' && currentUser.value) {
                loadPortfolios();
            }
            if (newTab === 'tracking') {
                loadTrackingData();
            }
        });

        // 监听 tab 切换，恢复 k 线图
        watch(currentTab, (newTab, oldTab) => {
            if (newTab === 'analysis' && analysisResult.value) {
                // 切换回分析页时，如果有数据，重新初始化图表
                nextTick(() => {
                    if (chartRef.value) {
                        initChart(analysisResult.value);
                        // 确保图表尺寸正确
                        if (chartInstance) {
                            setTimeout(() => {
                                chartInstance.resize();
                            }, 100);
                        }
                    }
                });
            }
            if (newTab === 'tracking' && trackingBenchmark.value) {
                nextTick(() => {
                    initTrackingChart();
                });
            }
        });

        // Draggable Task Button Functions
        const startDrag = (e) => {
            if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
                return; // Don't drag if clicking the toggle button
            }
            isDragging.value = true;
            dragStartPos.value = {
                x: e.clientX - taskButtonPosition.value.x,
                y: e.clientY - taskButtonPosition.value.y
            };
            document.addEventListener('mousemove', onDrag);
            document.addEventListener('mouseup', stopDrag);
            e.preventDefault();
        };
        
        const onDrag = (e) => {
            if (!isDragging.value) return;
            const newX = e.clientX - dragStartPos.value.x;
            const newY = e.clientY - dragStartPos.value.y;
            
            // Constrain to viewport
            const maxX = window.innerWidth - (taskButtonRef.value?.offsetWidth || 80);
            const maxY = window.innerHeight - (taskButtonRef.value?.offsetHeight || 80);
            
            taskButtonPosition.value = {
                x: Math.max(0, Math.min(newX, maxX)),
                y: Math.max(0, Math.min(newY, maxY))
            };
            
            // Save position to localStorage
            localStorage.setItem('taskButtonPosition', JSON.stringify(taskButtonPosition.value));
        };
        
        const stopDrag = () => {
            isDragging.value = false;
            document.removeEventListener('mousemove', onDrag);
            document.removeEventListener('mouseup', stopDrag);
        };
        
        // Load saved button position
        const loadButtonPosition = () => {
            try {
                const saved = localStorage.getItem('taskButtonPosition');
                if (saved) {
                    const pos = JSON.parse(saved);
                    // Validate position is still within viewport
                    const maxX = window.innerWidth - 80;
                    const maxY = window.innerHeight - 80;
                    taskButtonPosition.value = {
                        x: Math.max(0, Math.min(pos.x, maxX)),
                        y: Math.max(0, Math.min(pos.y, maxY))
                    };
                } else {
                    // Default position: bottom right
                    taskButtonPosition.value = {
                        x: window.innerWidth - 80,
                        y: window.innerHeight - 80
                    };
                }
            } catch {
                taskButtonPosition.value = {
                    x: window.innerWidth - 80,
                    y: window.innerHeight - 80
                };
            }
        };

        // 刷新页面后恢复图表（如果有 analysisResult）
        onMounted(async () => {
            // Load button position
            loadButtonPosition();
            
            // Update position on window resize
            window.addEventListener('resize', () => {
                const maxX = window.innerWidth - 80;
                const maxY = window.innerHeight - 80;
                taskButtonPosition.value = {
                    x: Math.min(taskButtonPosition.value.x, maxX),
                    y: Math.min(taskButtonPosition.value.y, maxY)
                };
            });
            
            // Close user menu when clicking outside
            document.addEventListener('click', (e) => {
                const userMenuContainer = document.getElementById('user-menu-container');
                if (showUserMenu.value && userMenuContainer && !userMenuContainer.contains(e.target)) {
                    showUserMenu.value = false;
                }
            });
            
            // Check authentication first
            await checkAuth();
            
            // Load available models, trending stocks, and market news
            loadModels();
            loadMarketIndices();
            loadTrendingStocks();
            loadMarketNews();
            
            if (analysisResult.value) {
                nextTick(() => {
                    initChart(analysisResult.value);
                });
            }
            
            // Load tasks if authenticated, only start polling if there are running tasks
            if (currentUser.value) {
                await loadTasks();
                const hasRunningTasks = tasks.value.some(t => t.status === 'running');
                if (hasRunningTasks) {
                    startTaskPolling();
                }
                loadPortfolios();
            }

            // Load data for the restored tab (fix: watch doesn't fire when initial value has no change)
            if (currentTab.value === 'tracking') {
                loadTrackingData();
            }
        });

        // --- Functions ---

        const debounce = (fn, delay) => {
            let timeout;
            return (...args) => {
                clearTimeout(timeout);
                timeout = setTimeout(() => fn(...args), delay);
            };
        };

        const handleSearch = debounce(async (e) => {
            const val = e.target.value;
            if (val.length < 1) {
                suggestions.value = [];
                klineSymbolSelected.value = false; // Reset selection state
                return;
            }
            klineSymbolSelected.value = false; // User is typing, not selected from suggestions
            try {
                // 根据选择的品类传递不同的 search_type
                let searchType = 'ALL';
                if (klineAssetType.value === 'FUND_CN') {
                    searchType = 'FUND_CN';
                }
                const res = await fetch(`/api/search?q=${val}&type=${searchType}`);
                suggestions.value = await res.json();
            } catch (err) {
                console.error(err);
            }
        }, 300);

        const selectStock = (item) => {
            query.value = item.symbol;
            selectedAssetType.value = item.type || 'STOCK';
            klineAssetType.value = item.type || 'STOCK'; // 同步更新 klineAssetType
            suggestions.value = [];
            klineSymbolSelected.value = true; // Mark as selected from suggestions
        };

        const clearKlineSelection = () => {
            query.value = '';
            klineSymbolSelected.value = false;
            suggestions.value = [];
            selectedAssetType.value = 'STOCK';
        };

        const getPlaceholderText = () => {
            const placeholders = {
                'STOCK': {
                    'zh': '输入股票代码 (如 AAPL, TSLA, 600519.SS)',
                    'en': 'Enter stock symbol (e.g., AAPL, TSLA, 600519.SS)'
                },
                'CRYPTO': {
                    'zh': '输入加密货币代码 (如 BTC-USD, ETH-USD)',
                    'en': 'Enter crypto symbol (e.g., BTC-USD, ETH-USD)'
                },
                'COMMODITY': {
                    'zh': '输入商品代码 (如 GC=F, CL=F)',
                    'en': 'Enter commodity symbol (e.g., GC=F, CL=F)'
                },
                'FUND_CN': {
                    'zh': '输入基金代码 (如 000001, 110022)',
                    'en': 'Enter fund code (e.g., 000001, 110022)'
                },
                'BOND': {
                    'zh': '输入债券代码 (如 ^TNX, ^TYX)',
                    'en': 'Enter bond symbol (e.g., ^TNX, ^TYX)'
                },
                'INDEX': {
                    'zh': '输入指数代码 (如 ^GSPC, ^DJI, 000001.SS)',
                    'en': 'Enter index symbol (e.g., ^GSPC, ^DJI, 000001.SS)'
                },
                'ETF': {
                    'zh': '输入ETF代码 (如 SPY, QQQ, VOO)',
                    'en': 'Enter ETF symbol (e.g., SPY, QQQ, VOO)'
                }
            };
            
            const assetType = klineAssetType.value || 'STOCK';
            const lang = currentLanguage.value === 'zh' ? 'zh' : 'en';
            return placeholders[assetType]?.[lang] || placeholders['STOCK'][lang];
        };

        const toggleTrade = (index) => {
            expandedTrades.value[index] = !expandedTrades.value[index];
        };

        const showToast = (message, type = 'info', duration = 3000) => {
            toastMessage.value = message;
            toastType.value = type;
            setTimeout(() => {
                toastMessage.value = '';
            }, duration);
        };

        const analyzeStock = async (symbol, assetType = null) => {
            if (!symbol) return;
            
            // Check authentication
            if (!currentUser.value) {
                showLoginModal.value = true;
                return;
            }
            
            // 使用传入的参数，如果没有则使用响应式变量的值
            const finalAssetType = assetType !== null ? assetType : klineAssetType.value;
            
            // 更新响应式变量（用于UI显示）
            if (assetType !== null) klineAssetType.value = assetType;
            
            // 判断是否为中国基金
            const isCnFund = finalAssetType === 'FUND_CN';
            
            suggestions.value = []; // Clear suggestions
            creatingTask.value = true;
            
            // Show initial toast
            showToast(
                currentLanguage.value === 'zh' ? '正在创建分析任务...' : 'Creating analysis task...',
                'info',
                2000
            );
            
            try {
                // Create async task
                const res = await fetch('/api/analyze_async', {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'X-Session-ID': sessionId.value
                    },
                    body: JSON.stringify({ 
                        symbol,
                        asset_type: finalAssetType,
                        is_cn_fund: isCnFund,
                        model: selectedModel.value,
                        language: currentLanguage.value
                    })
                });
                
                const data = await res.json();
                if (data.success) {
                    // Show success toast
                    showToast(
                        currentLanguage.value === 'zh' ? `任务已创建：${symbol}` : `Task created: ${symbol}`,
                        'success',
                        3000
                    );
                    
                    // Show task list with animation
                    taskListVisible.value = true;
                    
                    // Small delay to ensure task is saved to DB
                    await new Promise(resolve => setTimeout(resolve, 300));
                    await loadTasks();
                    startTaskPolling(); // Start polling while task is running
                    
                    // Highlight the new task
                    const newTask = tasks.value.find(t => t.task_id === data.task_id);
                    if (newTask) {
                        newTask._isNew = true;
                        setTimeout(() => {
                            if (newTask) delete newTask._isNew;
                        }, 2000);
                    }
                    
                    // Poll for completion
                    pollTaskUntilComplete(data.task_id, (result) => {
                        analysisResult.value = result;
                        expandedTrades.value = {};
                        if (result.analysis && result.analysis.analysis_summary && result.analysis.analysis_summary.includes('Quota Exceeded')) {
                    const m = models.value.find(m => m.id === selectedModel.value);
                    if (m) m.status = 'limit';
                }

                        // Show completion toast
                        showToast(
                            currentLanguage.value === 'zh' ? `🎉 分析完成：${symbol}` : `🎉 Analysis completed: ${symbol}`,
                            'success',
                            3000
                        );
                        
                        nextTick(() => {
                            if (chartRef.value) {
                                initChart(result);
                            }
                        });
                    });
                } else if (data.error === 'duplicate_task') {
                    // Handle duplicate task
                    duplicateTaskInfo.value = {
                        symbol: symbol,
                        task_id: data.existing_task_id,
                        created_at: data.existing_task_created_at
                    };
                    pendingAnalysisSymbol.value = symbol;
                    showDuplicateTaskDialog.value = true;
                } else {
                    throw new Error(data.error || data.message || 'Failed to create task');
                }
            } catch (err) {
                showToast(
                    currentLanguage.value === 'zh' ? `❌ 创建任务失败：${err.message}` : `❌ Failed to create task: ${err.message}`,
                    'error',
                    4000
                );
                console.error(err);
            } finally {
                creatingTask.value = false;
            }
        };

        const initChart = (data) => {
            if (!chartRef.value) return;
            if (chartInstance) {
                chartInstance.dispose();
            }
            chartInstance = echarts.init(chartRef.value);

            // Debug: Check asset_type
            console.log('🔍 initChart - data.asset_type:', data.asset_type);
            console.log('🔍 initChart - full data:', data);

            // Determine if this is a Chinese fund (use line chart instead of candlestick)
            const isFundCN = data.asset_type === 'FUND_CN';
            console.log('🔍 initChart - isFundCN:', isFundCN);
            
            const klineData = data.kline_data.map(item => [
                item.open, item.close, item.low, item.high
            ]);
            // For Chinese funds, use close price as line data (净值)
            const lineData = data.kline_data.map(item => item.close);
            const dates = data.kline_data.map(item => item.date);
            const volumes = data.kline_data.map((item, index) => [index, item.volume, item.open > item.close ? 1 : -1]);

            const trades = data.analysis.trades || [];
            const signals = data.analysis.signals || [];
            const userTransactions = data.analysis.user_transactions || [];
            
            // Debug: Check data
            console.log('🔍 Debug - signals:', signals);
            console.log('🔍 Debug - userTransactions:', userTransactions);
            
            // Separate AI signals into adopted and unadopted
            const aiSignalsUnadopted = [];
            const aiSignalsAdopted = [];
            const userTradeMarks = [];
            
            // Process AI signals
            signals.forEach(sig => {
                // Skip WAIT and HOLD - they are shown in summary only
                if (sig.type === 'WAIT' || sig.type === 'HOLD') {
                    return;
                }
                
                let tradeInfo = null;
                if (sig.type === 'BUY') {
                    tradeInfo = trades.find(t => t.buy_date === sig.date);
                } else if (sig.type === 'SELL') {
                    tradeInfo = trades.find(t => t.sell_date === sig.date);
                }
                
                // BUY/ADD shown as green, SELL/REDUCE shown as red on chart
                // Use position_action for precise label when available
                let displayValue, displayColor, displaySymbol;
                const posAction = sig.position_action || sig.type;
                if (sig.type === 'BUY') {
                    // BUY (new position) or ADD (increase existing)
                    if (posAction === 'ADD') {
                        displayValue = currentLanguage.value === 'zh' ? 'AI加仓' : 'AI-Add';
                        displayColor = '#2DD4BF';  // teal for ADD
                    } else {
                        displayValue = currentLanguage.value === 'zh' ? 'AI买' : 'AI-B';
                        displayColor = '#34D399';  // green for BUY
                    }
                    displaySymbol = 'pin';
                } else if (sig.type === 'SELL') {
                    // SELL (close all) or REDUCE (partial sell)
                    if (posAction === 'REDUCE') {
                        displayValue = currentLanguage.value === 'zh' ? 'AI减仓' : 'AI-Rd';
                        displayColor = '#FBBF24';  // amber for REDUCE
                    } else {
                        displayValue = currentLanguage.value === 'zh' ? 'AI平仓' : 'AI-S';
                        displayColor = '#F87171';  // red for SELL/CLOSE
                    }
                    displaySymbol = 'pin';
                } else {
                    // Unknown type, skip
                    return;
                }
                
                const markPoint = {
                    name: sig.type,
                    coord: [sig.date, sig.price],
                    value: displayValue,
                    symbol: displaySymbol,
                    symbolSize: sig.is_current ? 35 : 28,  // 更小巧的尺寸（原 60/50 → 35/28）
                    itemStyle: {
                        color: displayColor,
                        borderColor: sig.adopted ? '#374151' : (sig.is_current ? '#F59E0B' : '#475569'),  // 深色主题边框
                        borderWidth: sig.is_current ? 2 : (sig.adopted ? 1.5 : 1),  // 更细的边框
                        opacity: 0.85  // 添加透明度，不完全遮挡 K 线
                    },
                    tradeDetails: tradeInfo,
                    signalInfo: sig
                };
                
                if (sig.adopted) {
                    aiSignalsAdopted.push(markPoint);
                } else {
                    aiSignalsUnadopted.push(markPoint);
                }
            });
            
            // Process user's real transactions
            userTransactions.forEach(trans => {
                userTradeMarks.push({
                    name: trans.type,
                    coord: [trans.date, trans.price],
                    value: trans.type === 'BUY' ? (currentLanguage.value === 'zh' ? '真买' : 'R-B') : (currentLanguage.value === 'zh' ? '真卖' : 'R-S'),
                    symbol: 'diamond',  // Different symbol for real trades
                    symbolSize: 28,  // 更小巧的尺寸（原 50 → 28）
                    itemStyle: {
                        color: trans.type === 'BUY' ? '#60A5FA' : '#FBBF24',  // 更清新的颜色（浅蓝/浅黄）
                        borderColor: '#374151',  // 柔和的深灰边框
                        borderWidth: 1.5,  // 更细的边框
                        opacity: 0.85  // 添加透明度
                    },
                    transactionInfo: trans
                });
            });
            
            // Combine all mark points
            const allMarkPoints = [
                ...aiSignalsUnadopted,
                ...aiSignalsAdopted,
                ...userTradeMarks
            ];
            
            // Build complete transaction records list for display
            const transactionRecords = [];
            
            // Add AI signals (BUY/SELL only, skip HOLD/WAIT)
            signals.forEach(sig => {
                if (sig.type === 'BUY' || sig.type === 'SELL') {
                    transactionRecords.push({
                        date: sig.date,
                        type: sig.type,
                        price: sig.price,
                        reason: sig.reason || '',
                        source: 'ai',
                        adopted: sig.adopted || false,
                        is_current: sig.is_current || false,
                        position_action: sig.position_action || null
                    });
                }
            });
            
            // Add user real transactions
            userTransactions.forEach(trans => {
                transactionRecords.push({
                    date: trans.date,
                    type: trans.type,
                    price: trans.price,
                    reason: trans.notes || '',
                    source: 'user',
                    quantity: trans.quantity || null,
                    amount: trans.amount || null
                });
            });
            
            // Sort by date (newest first)
            transactionRecords.sort((a, b) => new Date(b.date) - new Date(a.date));
            
            // Debug: Check final transaction records
            console.log('🔍 Debug - transactionRecords:', transactionRecords);
            console.log('🔍 Debug - transactionRecords.length:', transactionRecords.length);
            
            // Store in reactive variable
            allTransactionRecords.value = transactionRecords;
            
            // Debug: Check reactive variable
            console.log('🔍 Debug - allTransactionRecords.value:', allTransactionRecords.value);

            const option = {
title: { text: `${data.symbol} ${currentLanguage.value === 'zh' ? (isFundCN ? '净值趋势分析' : 'K线趋势分析') : 'Trend'}`, left: 'center', textStyle: { color: '#E2E8F0', fontSize: 14 } },
                tooltip: {
                    trigger: 'axis',
                    axisPointer: { type: 'cross' },
                    backgroundColor: 'rgba(15,23,42,0.9)',
                    borderColor: '#334155',
                    textStyle: { color: '#E2E8F0' },
                    formatter: function (params) {
                        let result = params[0].name + '<br/>';
                        params.forEach(item => {
                            if (isFundCN && item.seriesName === '净值') {
                                result += `净值: ${item.value}<br/>`;
                            } else if (item.componentSubType === 'candlestick') {
                                const values = item.value;
                                result += `开盘: ${values[1]}<br/>`;
                                result += `收盘: ${values[2]}<br/>`;
                                result += `最低: ${values[3]}<br/>`;
                                result += `最高: ${values[4]}<br/>`;
                            } else if (item.seriesName === 'Volume') {
                                result += `成交量: ${item.value}<br/>`;
                            }
                        });
                        return result;
                    }
                },
                grid: [
                    { left: '8%', right: '5%', top: '12%', height: '58%' },
                    { left: '8%', right: '5%', top: '75%', height: '15%' }
                ],
xAxis: [
                    { 
                        type: 'category', 
                        data: dates, 
                        scale: true, 
                        boundaryGap: true,
                        axisLine: { onZero: false, lineStyle: { color: '#475569' } }, 
                        axisLabel: { color: '#94A3B8' },
                        splitLine: { show: false }, 
                        min: 'dataMin', 
                        max: 'dataMax'
                    },
                    { 
                        type: 'category', 
                        gridIndex: 1, 
                        data: dates, 
                        axisLine: { lineStyle: { color: '#475569' } },
                        axisLabel: { show: false } 
                    }
                ],
                yAxis: [
                    { 
                        scale: true, 
                        splitArea: { show: true, areaStyle: { color: ['rgba(30,41,59,0.5)', 'rgba(15,23,42,0.5)'] } },
                        splitNumber: 5,
                        splitLine: { lineStyle: { color: '#334155', type: 'dashed' } },
                        axisLine: { lineStyle: { color: '#475569' } },
                        axisLabel: {
                            color: '#94A3B8',
                            formatter: function (value) {
                                if (Math.abs(value) < 1 && value !== 0) {
                                    return value.toFixed(4);
                                }
                                return value.toFixed(2);
                            }
                        }
                    },
                    { 
                        scale: true, 
                        gridIndex: 1, 
                        splitNumber: 2, 
                        axisLabel: { show: false }, 
                        axisLine: { show: false },
                        axisTick: { show: false }, 
                        splitLine: { show: false } 
                    }
                ],
                dataZoom: [
                    { 
                        type: 'inside', 
                        xAxisIndex: [0, 1], 
                        start: 50, 
                        end: 100,
                        zoomOnMouseWheel: false, // Prevent page scroll hijack
                        moveOnMouseWheel: false,
                        moveOnMouseMove: true
                    },
{ show: true, xAxisIndex: [0, 1], type: 'slider', top: '92%', height: 20, start: 50, end: 100, borderColor: '#334155', backgroundColor: 'rgba(30,41,59,0.5)', fillerColor: 'rgba(99,102,241,0.2)', handleStyle: { color: '#6366F1' }, textStyle: { color: '#94A3B8' }, dataBackground: { lineStyle: { color: '#475569' }, areaStyle: { color: 'rgba(71,85,105,0.3)' } } }
                ],
                series: [
                    // Main chart: Line for FUND_CN, Candlestick for others
                    isFundCN ? {
                        name: '净值',
                        type: 'line',
                        data: lineData,
                        smooth: true,
                        lineStyle: {
                            color: '#3B82F6',
                            width: 2
                        },
                        itemStyle: {
                            color: '#3B82F6'
                        },
                        areaStyle: {
                            color: {
                                type: 'linear',
                                x: 0, y: 0, x2: 0, y2: 1,
                                colorStops: [
                                    { offset: 0, color: 'rgba(59, 130, 246, 0.3)' },
                                    { offset: 1, color: 'rgba(59, 130, 246, 0.05)' }
                                ]
                            }
                        },
                        markPoint: {
                            data: allMarkPoints,
                            symbol: 'pin',
                            symbolSize: 40,
                            label: { fontSize: 10 },
                            tooltip: {
                                trigger: 'item',
                                formatter: function(params) {
                                    const data = params.data;
                                    const type = data.name; 
                                    const details = data.tradeDetails;
                                    const signalInfo = data.signalInfo;
                                    const transInfo = data.transactionInfo;
                                    const isZh = currentLanguage.value === 'zh';
                                    
                                    let html = `<div style="font-family: sans-serif; padding: 4px;">`;
                                    
                                    // Determine mark type
                                    if (transInfo) {
                                        // Real user transaction
                                        html += `<div style="font-weight: bold; margin-bottom: 4px; color: ${type === 'BUY' ? '#3B82F6' : '#F59E0B'}">`;
                                        html += `${isZh ? '真实交易' : 'Real Trade'} - ${params.value} (${type})`;
                                        html += `</div>`;
                                        html += `<div>${isZh ? '日期' : 'Date'}: ${transInfo.date}</div>`;
                                        html += `<div>${isZh ? '价格' : 'Price'}: <b>${transInfo.price}</b></div>`;
                        html += `<div>${isZh ? '数量' : 'Quantity'}: ${transInfo.quantity}</div>`;
                                        if (transInfo.notes) {
                                            html += `<div style="margin-top: 4px; font-size: 10px; color: #94A3B8;">${transInfo.notes}</div>`;
                                        }
                                    } else if (signalInfo) {
                                        // AI signal (only BUY/SELL shown on chart)
                                        const adoptedText = signalInfo.adopted ? (isZh ? '已采纳' : 'Adopted') : (isZh ? '未采纳' : 'Not Adopted');
                                        const adoptedColor = signalInfo.adopted ? '#10B981' : '#6B7280';
                                        
                                        // Determine color based on signal type
                                        const signalColor = type === 'BUY' ? '#10B981' : '#EF4444';
                                        
                                        html += `<div style="font-weight: bold; margin-bottom: 4px; color: ${signalColor}">`;
                                        html += `${isZh ? 'AI建议' : 'AI Suggestion'} - ${params.value} (${type})`;
                                        html += `</div>`;
                                        
                                        // Show current recommendation badge
                                        if (signalInfo.is_current) {
                                            html += `<div style="display: inline-block; background: #FFD700; color: #000; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-bottom: 4px; font-weight: bold;">`;
                                            html += `${isZh ? '当前建议' : 'Current'}`;
                                            html += `</div>`;
                                        }
                                        
                                        html += `<div style="color: ${adoptedColor}; font-size: 11px; margin-bottom: 4px;">● ${adoptedText}</div>`;
                                        
                                        if (details) {
                                            if (type === 'BUY') {
                                                html += `<div>${isZh ? '日期' : 'Date'}: ${details.buy_date}</div>`;
                                                html += `<div>${isZh ? '价格' : 'Price'}: <b>${details.buy_price}</b></div>`;
                                            } else {
                                                html += `<div>${isZh ? '日期' : 'Date'}: ${details.sell_date}</div>`;
                                                html += `<div>${isZh ? '价格' : 'Price'}: <b>${details.sell_price}</b></div>`;
                                                html += `<div style="margin-top: 4px;">${isZh ? '收益' : 'Return'}: <span style="font-weight: bold; color: ${details.return_rate.includes('+') ? '#10B981' : '#EF4444'}">${details.return_rate}</span></div>`;
                                            }
                                            if (details.reason) {
                                                 const reason = details.reason.length > 60 ? details.reason.substring(0, 60) + '...' : details.reason;
                                                 html += `<div style="margin-top: 8px; font-size: 10px; color: #ccc; border-top: 1px solid #555; padding-top: 4px; max-width: 200px; white-space: normal;">${reason}</div>`;
                                            }
                                        } else {
                                            html += `<div>${isZh ? '日期' : 'Date'}: ${data.coord[0]}</div>`;
                                            html += `<div>${isZh ? '价格' : 'Price'}: ${data.coord[1]}</div>`;
                                            if (signalInfo.reason) {
                                                const reason = signalInfo.reason.length > 60 ? signalInfo.reason.substring(0, 60) + '...' : signalInfo.reason;
                                                html += `<div style="margin-top: 8px; font-size: 10px; color: #ccc; border-top: 1px solid #555; padding-top: 4px; max-width: 200px; white-space: normal;">${reason}</div>`;
                                            }
                                        }
                                    }
                                    html += `</div>`;
                                    return html;
                                }
                            }
                        }
                    } : {
                        name: 'K-Line',
                        type: 'candlestick',
                        data: klineData,
                        itemStyle: {
                            color: '#EF4444',
                            color0: '#10B981',
                            borderColor: '#EF4444',
                            borderColor0: '#10B981'
                        },
                        markPoint: {
                            data: allMarkPoints,
                            symbol: 'pin',
                            symbolSize: 40,
                            label: { fontSize: 10 },
                            tooltip: {
                                trigger: 'item',
                                formatter: function(params) {
                                    const data = params.data;
                                    const type = data.name; 
                                    const details = data.tradeDetails;
                                    const signalInfo = data.signalInfo;
                                    const transInfo = data.transactionInfo;
                                    const isZh = currentLanguage.value === 'zh';
                                    
                                    let html = `<div style="font-family: sans-serif; padding: 4px;">`;
                                    
                                    // Determine mark type
                                    if (transInfo) {
                                        // Real user transaction
                                        html += `<div style="font-weight: bold; margin-bottom: 4px; color: ${type === 'BUY' ? '#3B82F6' : '#F59E0B'}">`;
                                        html += `${isZh ? '真实交易' : 'Real Trade'} - ${params.value} (${type})`;
                                        html += `</div>`;
                                        html += `<div>${isZh ? '日期' : 'Date'}: ${transInfo.date}</div>`;
                                        html += `<div>${isZh ? '价格' : 'Price'}: <b>${transInfo.price}</b></div>`;
                                        html += `<div>${isZh ? '数量' : 'Quantity'}: ${transInfo.quantity}</div>`;
                                        if (transInfo.notes) {
                                            html += `<div style="margin-top: 4px; font-size: 10px; color: #94A3B8;">${transInfo.notes}</div>`;
                                        }
                                    } else if (signalInfo) {
                                        // AI signal (only BUY/SELL shown on chart)
                                        const adoptedText = signalInfo.adopted ? (isZh ? '已采纳' : 'Adopted') : (isZh ? '未采纳' : 'Not Adopted');
                                        const adoptedColor = signalInfo.adopted ? '#10B981' : '#6B7280';
                                        
                                        // Determine color based on signal type
                                        const signalColor = type === 'BUY' ? '#10B981' : '#EF4444';
                                        
                                        html += `<div style="font-weight: bold; margin-bottom: 4px; color: ${signalColor}">`;
                                        html += `${isZh ? 'AI建议' : 'AI Suggestion'} - ${params.value} (${type})`;
                                        html += `</div>`;
                                        
                                        // Show current recommendation badge
                                        if (signalInfo.is_current) {
                                            html += `<div style="display: inline-block; background: #FFD700; color: #000; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-bottom: 4px; font-weight: bold;">`;
                                            html += `${isZh ? '当前建议' : 'Current'}`;
                                            html += `</div>`;
                                        }
                                        
                                        html += `<div style="color: ${adoptedColor}; font-size: 11px; margin-bottom: 4px;">● ${adoptedText}</div>`;
                                        
                                        if (details) {
                                            if (type === 'BUY') {
                                                html += `<div>${isZh ? '日期' : 'Date'}: ${details.buy_date}</div>`;
                                                html += `<div>${isZh ? '价格' : 'Price'}: <b>${details.buy_price}</b></div>`;
                                            } else {
                                                html += `<div>${isZh ? '日期' : 'Date'}: ${details.sell_date}</div>`;
                                                html += `<div>${isZh ? '价格' : 'Price'}: <b>${details.sell_price}</b></div>`;
                                                html += `<div style="margin-top: 4px;">${isZh ? '收益' : 'Return'}: <span style="font-weight: bold; color: ${details.return_rate.includes('+') ? '#10B981' : '#EF4444'}">${details.return_rate}</span></div>`;
                                            }
                                            if (details.reason) {
                                                 const reason = details.reason.length > 60 ? details.reason.substring(0, 60) + '...' : details.reason;
                                                 html += `<div style="margin-top: 8px; font-size: 10px; color: #ccc; border-top: 1px solid #555; padding-top: 4px; max-width: 200px; white-space: normal;">${reason}</div>`;
                                            }
                                        } else {
                                            html += `<div>${isZh ? '日期' : 'Date'}: ${data.coord[0]}</div>`;
                                            html += `<div>${isZh ? '价格' : 'Price'}: ${data.coord[1]}</div>`;
                                            if (signalInfo.reason) {
                                                const reason = signalInfo.reason.length > 60 ? signalInfo.reason.substring(0, 60) + '...' : signalInfo.reason;
                                                html += `<div style="margin-top: 8px; font-size: 10px; color: #ccc; border-top: 1px solid #555; padding-top: 4px; max-width: 200px; white-space: normal;">${reason}</div>`;
                                            }
                                        }
                                    }
                                    html += `</div>`;
                                    return html;
                                }
                            }
                        }
                    },
                    {
                        name: 'Volume',
                        type: 'bar',
                        xAxisIndex: 1,
                        yAxisIndex: 1,
                        data: volumes.map(item => item[1]),
                        itemStyle: {
                            color: (params) => {
                                return klineData[params.dataIndex][0] < klineData[params.dataIndex][1] ? '#EF4444' : '#10B981';
                            }
                        }
                    }
                ]
            };

            chartInstance.setOption(option);
            window.addEventListener('resize', () => chartInstance.resize());
        };

        const getRecommendations = async () => {
            if (!currentUser.value) {
                showLoginModal.value = true;
                return;
            }
            
            loadingRecommend.value = true;
            recommendationResult.value = null;
            try {
                // Create async task
                const res = await fetch('/api/recommend_async', {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'X-Session-ID': sessionId.value
                    },
                    body: JSON.stringify({
                        ...recCriteria.value,
                        model: selectedModel.value,
                        language: currentLanguage.value
                    })
                });
                
                const data = await res.json();
                if (data.success) {
                    // Show task list and add animation
                    taskListVisible.value = true;
                    await loadTasks();
                    startTaskPolling(); // Start polling while task is running
                    // Poll for completion
                    pollTaskUntilComplete(data.task_id, (result) => {
                        // Ensure result has proper structure
                        if (result) {
                            console.log('[Recommend] Task result received:', Object.keys(result));
                            console.log('[Recommend] agent_trace:', result.agent_trace ? result.agent_trace.length + ' steps' : 'MISSING');
                            console.log('[Recommend] tool_calls:', result.tool_calls ? result.tool_calls.length + ' calls' : 'MISSING');
                            if (!result.recommendations) {
                                result.recommendations = [];
                            } else if (!Array.isArray(result.recommendations)) {
                                result.recommendations = [];
                            }
                            recommendationResult.value = result;
                            showRecommendToolCalls.value = true;  // Auto-expand trace panel
                        } else {
                            recommendationResult.value = null;
                        }
                        loadingRecommend.value = false;
                    });
                } else {
                    throw new Error(data.error || 'Failed to create task');
                }
            } catch (err) {
                alert('推荐请求失败: ' + err);
                console.error(err);
                loadingRecommend.value = false;
            }
        };

        const diagnosePortfolio = async () => {
            if (!currentUser.value) {
                showLoginModal.value = true;
                return;
            }
            
            // Check if there are any portfolios
            if (!portfolios.value || portfolios.value.length === 0) {
                showToast(
                    currentLanguage.value === 'zh' ? '暂无持仓数据' : 'No portfolio data',
                    'warning',
                    2000
                );
                return;
            }
            
            creatingTask.value = true;
            loadingPortfolio.value = true; 
            portfolioResult.value = null;
            
            showToast(
                currentLanguage.value === 'zh' ? '正在创建持仓分析任务...' : 'Creating portfolio analysis task...',
                'info',
                2000
            );
            
            try {
                // Create async task with all portfolios
                const res = await fetch('/api/portfolio_advice_async', {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'X-Session-ID': sessionId.value
                    },
                    body: JSON.stringify({
                        portfolios: portfolios.value,
                        model: selectedModel.value,
                        language: currentLanguage.value
                    })
                });
                const data = await res.json();
                if (data.success) {
                    showToast(
                        currentLanguage.value === 'zh' ? '持仓分析任务已创建' : 'Portfolio analysis task created',
                        'success',
                        3000
                    );
                    
                    // Show task list and add animation
                    taskListVisible.value = true;
                    await new Promise(resolve => setTimeout(resolve, 300));
                    await loadTasks();
                    startTaskPolling(); // Start polling while task is running
                    
                    // Poll for completion
                    pollTaskUntilComplete(data.task_id, (result) => {
                        portfolioResult.value = result;
                        loadingPortfolio.value = false;
                        showToast(
                            currentLanguage.value === 'zh' ? '🎉 持仓分析完成' : '🎉 Portfolio analysis completed',
                            'success',
                            3000
                        );
                    });
                } else {
                    throw new Error(data.error || 'Failed to create task');
                }
            } catch (err) {
                showToast(
                    currentLanguage.value === 'zh' ? `❌ 创建任务失败：${err.message}` : `❌ Failed to create task: ${err.message}`,
                    'error',
                    4000
                );
                console.error(err);
                loadingPortfolio.value = false;
            } finally {
                creatingTask.value = false;
            }
        };
        
        // ========== User Authentication Functions ==========
        
        const checkAuth = async () => {
            if (!sessionId.value) {
                showLoginModal.value = true;
                return;
            }
            
            try {
                const res = await fetch(`/api/auth/check?session_id=${sessionId.value}`);
                if (res.ok) {
                    const data = await res.json();
                    if (data.authenticated) {
                        currentUser.value = data.user;
                        return;
                    }
                }
            } catch (err) {
                console.error('Auth check failed:', err);
            }
            
            // Not authenticated, show login modal
            showLoginModal.value = true;
        };
        
        const openLoginModal = () => {
            isRegisterMode.value = false;
            authError.value = '';
            showLoginModal.value = true;
        };
        
        const closeLoginModal = () => {
            showLoginModal.value = false;
            authError.value = '';
            loginForm.value = { nickname: '', email: '', password: '' };
        };
        
        const toggleAuthMode = () => {
            isRegisterMode.value = !isRegisterMode.value;
            authError.value = '';
        };
        
        const handleAuthSubmit = async () => {
            if (isRegisterMode.value) {
                await handleRegister();
            } else {
                await handleLogin();
            }
        };
        
        const handleRegister = async (emailConfirmed = false) => {
            authError.value = '';
            authLoading.value = true;
            
            try {
                const res = await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        nickname: loginForm.value.nickname,
                        email: loginForm.value.email,
                        password: loginForm.value.password,
                        email_confirmed: emailConfirmed
                    })
                });
                
                const data = await res.json();
                
                // 检查是否需要邮箱确认
                if (data.need_confirmation) {
                    authLoading.value = false;
                    emailConfirmInfo.value = {
                        email: data.email,
                        typo_suggestion: data.typo_suggestion,
                        score: data.score
                    };
                    showEmailConfirmDialog.value = true;
                    return;
                }
                
                if (data.success) {
                    currentUser.value = data.user;
                    sessionId.value = data.user.session_id;
                    localStorage.setItem('investPilotSessionId', sessionId.value);
                    showLoginModal.value = false;
                    loginForm.value = { nickname: '', email: '', password: '' };
                    
                    showToast(
                        currentLanguage.value === 'zh' ? '注册成功！' : 'Registration successful!',
                        'success',
                        3000
                    );
                    
                    // Load tasks (new user won't have running tasks, no need to poll)
                    loadTasks();
                } else {
                    authError.value = data.error || (currentLanguage.value === 'zh' ? '注册失败' : 'Registration failed');
                }
            } catch (err) {
                authError.value = currentLanguage.value === 'zh' ? '注册失败: ' + err.message : 'Registration failed: ' + err.message;
                console.error(err);
            } finally {
                authLoading.value = false;
            }
        };
        
        const handleLogin = async () => {
            authError.value = '';
            authLoading.value = true;
            
            try {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        email: loginForm.value.email,
                        password: loginForm.value.password,
                        session_id: sessionId.value
                    })
                });
                
                const data = await res.json();
                if (data.success) {
                    currentUser.value = data.user;
                    sessionId.value = data.user.session_id;
                    localStorage.setItem('investPilotSessionId', sessionId.value);
                    showLoginModal.value = false;
                    loginForm.value = { nickname: '', email: '', password: '' };
                    
                    showToast(
                        currentLanguage.value === 'zh' ? '登录成功！' : 'Login successful!',
                        'success',
                        3000
                    );
                    
                    // Load tasks, only start polling if there are running tasks
                    await loadTasks();
                    const hasRunningTasks = tasks.value.some(t => t.status === 'running');
                    if (hasRunningTasks) {
                        startTaskPolling();
                    }
                } else {
                    authError.value = data.error || (currentLanguage.value === 'zh' ? '登录失败' : 'Login failed');
                }
            } catch (err) {
                authError.value = currentLanguage.value === 'zh' ? '登录失败: ' + err.message : 'Login failed: ' + err.message;
                console.error(err);
            } finally {
                authLoading.value = false;
            }
        };
        
        // Email confirmation handlers
        const confirmEmail = async () => {
            showEmailConfirmDialog.value = false;
            await handleRegister(true); // 用户确认使用当前邮箱
        };
        
        const useSuggestedEmail = () => {
            // 使用建议的邮箱
            loginForm.value.email = emailConfirmInfo.value.typo_suggestion;
            showEmailConfirmDialog.value = false;
            showToast(
                currentLanguage.value === 'zh' 
                    ? '已更新为建议的邮箱地址' 
                    : 'Email updated to suggested address',
                'info',
                2000
            );
        };
        
        const cancelEmailConfirm = () => {
            showEmailConfirmDialog.value = false;
            authError.value = '';
        };
        
        const handleLogout = async () => {
            showUserMenu.value = false;
            
            try {
                await fetch('/api/auth/logout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: sessionId.value })
                });
            } catch (err) {
                console.error('Logout error:', err);
            }
            
            // Clear local state
            currentUser.value = null;
            sessionId.value = null;
            localStorage.removeItem('investPilotSessionId');
            
            // Stop task polling
            if (taskPollInterval) {
                clearInterval(taskPollInterval);
                taskPollInterval = null;
            }
            
            // Clear tasks
            tasks.value = [];
            
            showToast(
                currentLanguage.value === 'zh' ? '已退出登录' : 'Logged out',
                'success',
                2000
            );
            
            // Show login modal
            setTimeout(() => {
                showLoginModal.value = true;
            }, 500);
        };
        
        // ========== Task Management Functions ==========
        
        const loadTasks = async () => {
            if (!currentUser.value) return;
            
            try {
                const res = await fetch('/api/tasks', {
                    headers: { 'X-Session-ID': sessionId.value }
                });
                if (res.ok) {
                    const data = await res.json();
                    tasks.value = (data && Array.isArray(data.tasks)) ? data.tasks : [];
                } else {
                    const errorData = await res.json().catch(() => ({}));
                    console.error('Failed to load tasks:', errorData.error || res.statusText);
                }
            } catch (err) {
                console.error('Failed to load tasks:', err);
            }
        };
        
        const startTaskPolling = () => {
            if (taskPollInterval) return;
            taskPollInterval = setInterval(async () => {
                if (currentUser.value) {
                    await loadTasks();
                    // Auto-stop polling if no running tasks
                    const hasRunningTasks = tasks.value.some(t => t.status === 'running');
                    if (!hasRunningTasks) {
                        stopTaskPolling();
                    }
                }
            }, 3000); // Poll every 3 seconds
        };
        
        const stopTaskPolling = () => {
            if (taskPollInterval) {
                clearInterval(taskPollInterval);
                taskPollInterval = null;
            }
        };
        
        const pollTaskUntilComplete = async (taskId, callback) => {
            const maxAttempts = 300; // 10 minutes max
            let attempts = 0;
            
            const poll = async () => {
                try {
                    const res = await fetch(`/api/tasks/${taskId}`, {
                        headers: { 'X-Session-ID': sessionId.value }
                    });
                    if (res.ok) {
                        const task = await res.json();
                        if (task.status === 'completed') {
                            callback(task.task_result);
                            loadTasks(); // Refresh task list
                            return;
                        } else if (task.status === 'failed' || task.status === 'terminated') {
                            loadTasks(); // Refresh task list
                            return;
                        }
                    }
                } catch (err) {
                    console.error('Task poll error:', err);
                }
                
                attempts++;
                if (attempts < maxAttempts) {
                    setTimeout(poll, 2000);
                }
            };
            
            poll();
        };
        
        const terminateTask = async (taskId) => {
            if (!confirm(currentLanguage.value === 'zh' ? '确定要终止此任务吗？' : 'Are you sure you want to terminate this task?')) {
                return;
            }
            
            try {
                const res = await fetch(`/api/tasks/${taskId}/terminate`, {
                    method: 'POST',
                    headers: { 'X-Session-ID': sessionId.value }
                });
                if (res.ok) {
                    await loadTasks();
                } else {
                    alert(currentLanguage.value === 'zh' ? '终止任务失败' : 'Failed to terminate task');
                }
            } catch (err) {
                alert('终止任务失败: ' + err);
                console.error(err);
            }
        };
        
        const showTaskResult = (task) => {
            console.log('showTaskResult called with task:', task);
            
            if (!task.task_result) {
                console.log('No task_result found');
                return;
            }
            
            const result = task.task_result;
            console.log('Task type:', task.task_type, 'Result:', result);
            
            // Determine task type and show appropriate result
            if (task.task_type === 'kline_analysis') {
                // Switch to analysis tab and show result
                currentTab.value = 'analysis';
                analysisResult.value = result;
                query.value = result.symbol || '';
                nextTick(() => {
                    if (chartRef.value) {
                        initChart(result);
                    }
                });
                taskListVisible.value = false; // Close task list
            } else if (task.task_type === 'portfolio_diagnosis') {
                // Switch to portfolio tab and show result
                console.log('Setting portfolioResult to:', result);
                currentTab.value = 'portfolio';
                portfolioResult.value = result;
                console.log('portfolioResult.value is now:', portfolioResult.value);
                if (task.task_params && task.task_params.symbol) {
                    portfolio.value.symbol = task.task_params.symbol;
                }
                taskListVisible.value = false; // Close task list
            } else if (task.task_type === 'stock_recommendation') {
                // Switch to recommend tab and show result
                currentTab.value = 'recommend';
                // Ensure result has proper structure
                if (result) {
                    console.log('[showTaskResult] Recommend result keys:', Object.keys(result));
                    console.log('[showTaskResult] agent_trace:', result.agent_trace ? result.agent_trace.length + ' steps' : 'MISSING');
                    if (!result.recommendations) {
                        result.recommendations = [];
                    } else if (!Array.isArray(result.recommendations)) {
                        result.recommendations = [];
                    }
                    recommendationResult.value = result;
                    showRecommendToolCalls.value = true;  // Auto-expand trace panel
                } else {
                    recommendationResult.value = null;
                }
                taskListVisible.value = false; // Close task list
            }
        };
        
        const getTaskStatusLabel = (status) => {
            const labels = {
                'running': currentLanguage.value === 'zh' ? '运行中' : 'Running',
                'completed': currentLanguage.value === 'zh' ? '已完成' : 'Completed',
                'terminated': currentLanguage.value === 'zh' ? '已终止' : 'Terminated',
                'failed': currentLanguage.value === 'zh' ? '失败' : 'Failed'
            };
            return labels[status] || status;
        };
        
        const getTaskTypeLabel = (type) => {
            const labels = {
                'kline_analysis': currentLanguage.value === 'zh' ? 'K线分析' : 'K-Line Analysis',
                'portfolio_diagnosis': currentLanguage.value === 'zh' ? '持仓诊断' : 'Portfolio Diagnosis',
        'stock_recommendation': currentLanguage.value === 'zh' ? '资产推荐' : 'Asset Recommendation'
            };
            return labels[type] || type;
        };
        
        const getTaskTitle = (task) => {
            if (task.task_params) {
                if (task.task_type === 'kline_analysis' && task.task_params.symbol) {
                    return task.task_params.symbol;
                } else if (task.task_type === 'portfolio_diagnosis' && task.task_params.symbol) {
                    return `${task.task_params.symbol} - ${currentLanguage.value === 'zh' ? '持仓诊断' : 'Portfolio Diagnosis'}`;
                } else if (task.task_type === 'stock_recommendation') {
        return currentLanguage.value === 'zh' ? '资产推荐' : 'Asset Recommendation';
                }
            }
            return getTaskTypeLabel(task.task_type);
        };
        
        const formatTime = (timeStr) => {
            if (!timeStr) return '';
            // 后端存储的是UTC时间，需要添加'Z'后缀确保正确解析为UTC
            const utcTimeStr = timeStr.endsWith('Z') ? timeStr : timeStr + 'Z';
            const date = new Date(utcTimeStr);
            const now = new Date();
            const diff = now - date;
            const minutes = Math.floor(diff / 60000);
            const hours = Math.floor(diff / 3600000);
            const days = Math.floor(diff / 86400000);
            
            if (minutes < 1) {
                return currentLanguage.value === 'zh' ? '刚刚' : 'Just now';
            } else if (minutes < 60) {
                return `${minutes}${currentLanguage.value === 'zh' ? '分钟前' : 'm ago'}`;
            } else if (hours < 24) {
                return `${hours}${currentLanguage.value === 'zh' ? '小时前' : 'h ago'}`;
            } else {
                return `${days}${currentLanguage.value === 'zh' ? '天前' : 'd ago'}`;
            }
        };
        
        const handleDuplicateTaskChoice = async (choice) => {
            showDuplicateTaskDialog.value = false;
            const symbol = pendingAnalysisSymbol.value;
            pendingAnalysisSymbol.value = null;
            
            if (choice === 'wait') {
                // 等待现有任务完成
                showToast(
                    currentLanguage.value === 'zh' ? '正在等待现有任务完成...' : 'Waiting for existing task to complete...',
                    'info',
                    2000
                );
                
                // 打开任务列表
                taskListVisible.value = true;
                await loadTasks();
                startTaskPolling(); // Start polling while task is running
                
                // 找到现有任务并轮询
                const existingTask = tasks.value.find(t => t.task_id === duplicateTaskInfo.value.task_id);
                if (existingTask) {
                    pollTaskUntilComplete(existingTask.task_id, (result) => {
                        analysisResult.value = result;
                        expandedTrades.value = {};
                        if (result.analysis && result.analysis.analysis_summary && result.analysis.analysis_summary.includes('Quota Exceeded')) {
                            const m = models.value.find(m => m.id === selectedModel.value);
                            if (m) m.status = 'limit';
                        }
                        
                        showToast(
                            currentLanguage.value === 'zh' ? `🎉 分析完成：${symbol}` : `🎉 Analysis completed: ${symbol}`,
                            'success',
                            3000
                        );
                        
                        nextTick(() => {
                            if (chartRef.value) {
                                initChart(result);
                            }
                        });
                    });
                }
            } else if (choice === 'cancel') {
                // 取消现有任务并创建新任务
                try {
                    // 先终止现有任务
                    const res = await fetch(`/api/tasks/${duplicateTaskInfo.value.task_id}/terminate`, {
                        method: 'POST',
                        headers: { 'X-Session-ID': sessionId.value }
                    });
                    
                    if (res.ok) {
                        showToast(
                            currentLanguage.value === 'zh' ? '已取消现有任务，正在创建新任务...' : 'Cancelled existing task, creating new...',
                            'info',
                            2000
                        );
                        
                        // 等待一小段时间确保任务已终止
                        await new Promise(resolve => setTimeout(resolve, 500));
                        
                        // 重新调用分析
                        await analyzeStock(symbol);
                    } else {
                        throw new Error('Failed to terminate existing task');
                    }
                } catch (err) {
                    showToast(
                        currentLanguage.value === 'zh' ? `❌ 取消任务失败：${err.message}` : `❌ Failed to cancel task: ${err.message}`,
                        'error',
                        4000
                    );
                }
            }
        };
        
        const closeDisclaimer = () => {
            showDisclaimer.value = false;
            localStorage.setItem('disclaimerDismissed', 'true');
        };
        
        // Watch for asset_type changes in recommendation criteria
        // Auto-reset market to 'Any' when switching to non-stock assets
        watch(() => recCriteria.value.asset_type, (newAssetType, oldAssetType) => {
            if (newAssetType !== 'STOCK' && recCriteria.value.market !== 'Any') {
                console.log(`Asset type changed from ${oldAssetType} to ${newAssetType}, resetting market to 'Any'`);
                recCriteria.value.market = 'Any';
            }
        });

        // 智能判断用户操作类型
        const getUserActionLabel = (record) => {
            if (!record || !record.type) return '';
            
            // 获取当前分析股票的符号
            const currentSymbol = analysisResult.value?.symbol || query.value;
            if (!currentSymbol) {
                // 如果没有当前股票信息，使用简单的标签
                return record.type === 'BUY' ? 
                    (currentLanguage.value === 'zh' ? '真买' : 'Real Buy') : 
                    (currentLanguage.value === 'zh' ? '真卖' : 'Real Sell');
            }
            
            // 获取当前股票的所有用户交易记录
            const userTransactions = allTransactionRecords.value.filter(r => 
                r.source === 'user'
            ).sort((a, b) => new Date(a.date) - new Date(b.date));
            
            if (record.type === 'BUY') {
                // 判断是否为首次买入
                const buyTransactions = userTransactions.filter(r => r.type === 'BUY');
                const recordIndex = buyTransactions.findIndex(r => 
                    r.date === record.date && Math.abs((r.price || 0) - (record.price || 0)) < 0.01
                );
                
                if (recordIndex === 0) {
                    return currentLanguage.value === 'zh' ? '真买' : 'Real Buy';
                } else {
                    return currentLanguage.value === 'zh' ? '真加仓' : 'Real Add';
                }
            } else if (record.type === 'SELL') {
                // 判断是否为清仓
                const recordDate = new Date(record.date);
                const transactionsBeforeThis = userTransactions.filter(r => 
                    new Date(r.date) <= recordDate
                );
                
                // 计算到此交易为止的持仓数量
                let totalQuantity = 0;
                for (const trans of transactionsBeforeThis) {
                    if (trans.type === 'BUY') {
                        totalQuantity += trans.quantity || 0;
                    } else if (trans.type === 'SELL') {
                        totalQuantity -= trans.quantity || 0;
                    }
                }
                
                // 如果卖出后持仓为0，则为清仓
                if (Math.abs(totalQuantity) < 0.001) {
                    return currentLanguage.value === 'zh' ? '真清仓' : 'Real Close';
                } else {
                    return currentLanguage.value === 'zh' ? '真减仓' : 'Real Reduce';
                }
            }
            
            return currentLanguage.value === 'zh' ? '真操作' : 'Real Trade';
        };

        // 智能判断AI操作类型
        const getAIActionLabel = (record) => {
            if (!record || !record.type) return '';
            
            // 如果有position_action字段，优先使用
            if (record.position_action) {
                const actionMap = {
                    'BUY': currentLanguage.value === 'zh' ? 'AI建仓' : 'AI Open',
                    'OPEN': currentLanguage.value === 'zh' ? 'AI建仓' : 'AI Open',
                    'ADD': currentLanguage.value === 'zh' ? 'AI加仓' : 'AI Add',
                    'REDUCE': currentLanguage.value === 'zh' ? 'AI减仓' : 'AI Reduce',
                    'SELL': currentLanguage.value === 'zh' ? 'AI平仓' : 'AI Close',
                    'CLOSE': currentLanguage.value === 'zh' ? 'AI平仓' : 'AI Close'
                };
                return actionMap[record.position_action] || (record.type === 'BUY' ? 
                    (currentLanguage.value === 'zh' ? 'AI买' : 'AI Buy') : 
                    (currentLanguage.value === 'zh' ? 'AI卖' : 'AI Sell'));
            }
            
            // 默认显示
            return record.type === 'BUY' ? 
                (currentLanguage.value === 'zh' ? 'AI买' : 'AI Buy') : 
                (currentLanguage.value === 'zh' ? 'AI卖' : 'AI Sell');
        };

        // ============================================================
        // Stock Tracking Functions
        // ============================================================

        const loadTrackingData = async () => {
            loadingTracking.value = true;
            try {
                // Load main data first (fast DB queries)
                const [summaryRes, holdingsRes, txnRes, decisionsRes] = await Promise.all([
                    fetch('/api/tracking/summary'),
                    fetch('/api/tracking/holdings'),
                    fetch('/api/tracking/transactions?limit=30'),
                    fetch('/api/tracking/decisions?limit=20')
                ]);
                if (summaryRes.ok) trackingSummary.value = await summaryRes.json();
                if (holdingsRes.ok) {
                    const hData = await holdingsRes.json();
                    trackingHoldings.value = hData.holdings || [];
                }
                if (txnRes.ok) {
                    const tData = await txnRes.json();
                    trackingTransactions.value = tData.transactions || [];
                }
                if (decisionsRes.ok) {
                    const dData = await decisionsRes.json();
                    trackingDecisions.value = dData.decisions || [];
                }
            } catch (e) {
                console.error('Failed to load tracking data:', e);
            } finally {
                loadingTracking.value = false;
            }

            // Load benchmark data asynchronously (may be slow due to yfinance network calls)
            try {
                const benchmarkRes = await fetch('/api/tracking/benchmark');
                if (benchmarkRes.ok) {
                    trackingBenchmark.value = await benchmarkRes.json();
                    nextTick(() => initTrackingChart());
                }
            } catch (e) {
                console.error('Failed to load benchmark data:', e);
            }
        };

        const refreshTrackingPrices = async () => {
            trackingRefreshing.value = true;
            try {
                const res = await fetch('/api/tracking/refresh-prices', { method: 'POST' });
                if (res.ok) {
                    toastMessage.value = currentLanguage.value === 'zh' ? '价格已刷新' : 'Prices refreshed';
                    toastType.value = 'success';
                    setTimeout(() => toastMessage.value = '', 3000);
                    await loadTrackingData();
                }
            } catch (e) {
                console.error('Failed to refresh prices:', e);
            } finally {
                trackingRefreshing.value = false;
            }
        };

        const runTrackingDecision = async () => {
            trackingRunning.value = true;
            toastMessage.value = currentLanguage.value === 'zh' ? 'AI 正在深度分析中，请稍候...' : 'AI is analyzing deeply, please wait...';
            toastType.value = 'info';
            try {
                const res = await fetch('/api/tracking/run-decision', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ model: selectedModel.value || 'gemini-3-flash-preview' })
                });
                if (res.ok) {
                    const result = await res.json();
                    toastMessage.value = result.has_changes
                        ? (currentLanguage.value === 'zh' ? 'AI 决策完成，组合已更新！' : 'AI decision complete, portfolio updated!')
                        : (currentLanguage.value === 'zh' ? 'AI 决策完成，暂无变更。' : 'AI decision complete, no changes.');
                    toastType.value = result.has_changes ? 'success' : 'info';
                    await loadTrackingData();
                } else {
                    const err = await res.json();
                    toastMessage.value = err.error || 'Failed';
                    toastType.value = 'error';
                }
            } catch (e) {
                toastMessage.value = 'Error: ' + e.message;
                toastType.value = 'error';
            } finally {
                trackingRunning.value = false;
                setTimeout(() => toastMessage.value = '', 5000);
            }
        };

        const initTrackingChart = () => {
            const chartDom = trackingChartRef.value;
            if (!chartDom || typeof echarts === 'undefined') return;
            const data = trackingBenchmark.value;
            if (!data || !data.dates || data.dates.length === 0) return;

            if (trackingChartInstance) {
                trackingChartInstance.dispose();
            }
            trackingChartInstance = echarts.init(chartDom);

            // Build portfolio series config with markPoint at start
            const portfolioStartIdx = data.portfolio_start_index;
            const hasPortfolio = portfolioStartIdx !== null && portfolioStartIdx !== undefined;
            const startDate = hasPortfolio ? data.dates[portfolioStartIdx] : null;
            const startValue = hasPortfolio ? data.portfolio[portfolioStartIdx] : null;

            const portfolioSeries = {
                name: currentLanguage.value === 'zh' ? '精选组合' : 'Curated Picks',
                type: 'line',
                data: data.portfolio,
                smooth: true,
                connectNulls: false,
                lineStyle: { width: 2.5, color: '#2563eb' },
                itemStyle: { color: '#2563eb' },
                showSymbol: false,
                areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(37,99,235,0.15)' }, { offset: 1, color: 'rgba(37,99,235,0)' }] } }
            };

            // Add a markPoint at the portfolio start date
            if (hasPortfolio) {
                portfolioSeries.markPoint = {
                    symbol: 'circle',
                    symbolSize: 10,
                    label: {
                        show: true,
                        formatter: currentLanguage.value === 'zh' ? '精选起点' : 'Start',
                        fontSize: 10,
                        color: '#2563eb',
                        position: 'top',
                        distance: 10
                    },
                    itemStyle: {
                        color: '#2563eb',
                        borderColor: '#1E293B',
                        borderWidth: 2,
                        shadowColor: 'rgba(37,99,235,0.4)',
                        shadowBlur: 6
                    },
                    data: [{
                        coord: [startDate, startValue]
                    }]
                };
                // Also add a vertical markLine at the start date
                portfolioSeries.markLine = {
                    silent: true,
                    symbol: 'none',
                    lineStyle: { type: 'dashed', color: '#2563eb', width: 1, opacity: 0.5 },
                    label: { show: false },
                    data: [{ xAxis: startDate }]
                };
            }

            const option = {
                tooltip: {
                    trigger: 'axis',
                    backgroundColor: 'rgba(15,23,42,0.9)',
                    borderColor: '#334155',
                    textStyle: { color: '#E2E8F0' },
                    formatter: function(params) {
                        let html = `<div style="font-size:12px;color:#E2E8F0"><strong>${params[0].axisValue}</strong>`;
                        params.forEach(p => {
                            if (p.value !== null && p.value !== undefined) {
                                const color = p.value >= 0 ? '#16a34a' : '#dc2626';
                                html += `<br/><span style="color:${p.color}">${p.seriesName}</span>: <span style="color:${color};font-weight:bold">${p.value >= 0 ? '+' : ''}${p.value}%</span>`;
                            }
                        });
                        html += '</div>';
                        return html;
                    }
                },
legend: {
                    show: true,
                    top: 0,
                    right: 0,
                    textStyle: { fontSize: 10, color: '#CBD5E1' },
                    itemWidth: 16,
                    itemHeight: 2
                },
                grid: { left: '3%', right: '4%', bottom: '3%', top: '14%', containLabel: true },
                xAxis: {
                    type: 'category',
                    data: data.dates,
                    axisLabel: { fontSize: 10, color: '#94A3B8', interval: Math.floor(data.dates.length / 6) },
                    axisLine: { lineStyle: { color: '#475569' } }
                },
                yAxis: {
                    type: 'value',
                    axisLabel: { fontSize: 10, color: '#94A3B8', formatter: '{value}%' },
                    splitLine: { lineStyle: { type: 'dashed', color: '#334155' } },
                    axisLine: { lineStyle: { color: '#475569' } }
                },
                series: [
                    portfolioSeries,
                    {
                        name: 'SPY (S&P 500)',
                        type: 'line',
                        data: data.sp500,
                        smooth: true,
                        lineStyle: { width: 1.5, color: '#f97316', type: 'dashed' },
                        itemStyle: { color: '#f97316' },
                        showSymbol: false
                    },
                    {
                        name: 'QQQ (NASDAQ 100)',
                        type: 'line',
                        data: data.nasdaq100,
                        smooth: true,
                        lineStyle: { width: 1.5, color: '#22c55e', type: 'dashed' },
                        itemStyle: { color: '#22c55e' },
                        showSymbol: false
                    }
                ]
            };

            trackingChartInstance.setOption(option);
            window.addEventListener('resize', () => {
                if (trackingChartInstance) trackingChartInstance.resize();
            });
        };

        return {
            currentTab,
            currentLanguage,
            recCriteria,
            recommendationResult,
            portfolio,
            portfolioResult,
            getRecommendations,
            diagnosePortfolio,
            query,
            suggestions,
            klineSymbolSelected,
            klineAssetType,
            getPlaceholderText,
            loadingAnalysis,
            loadingRecommend,
            loadingPortfolio,
            analysisResult,
            chartRef,
            handleSearch,
            selectStock,
            clearKlineSelection,
            analyzeStock,
            stats,
            models,
            availableModels,
            selectedModel,
            selectedModelName,
            currentModelStatus,
            expandedTrades,
            showToolCalls,
            showRecommendToolCalls,
            toggleTrade,
            allTransactionRecords,  // Transaction records for display
            getUserActionLabel,
            getAIActionLabel,
            hotStocks,
            loadingHotStocks,
            marketIndices,
            loadingMarketIndices,
            marketNews,
            loadingMarketNews,
            showTooltip,
            tooltipPosition,
            // User Auth
            currentUser,
            showLoginModal,
            openLoginModal,
            closeLoginModal,
            loginForm,
            handleLogin,
            handleLogout,
            showUserMenu,
            authError,
            authLoading,
            handleAuthSubmit,
            isRegisterMode,
            toggleAuthMode,
            showPassword,
            // Email Confirmation
            showEmailConfirmDialog,
            emailConfirmInfo,
            confirmEmail,
            useSuggestedEmail,
            cancelEmailConfirm,
            // Task Management
            tasks,
            taskListVisible,
            taskFilterStatus,
            taskStatusFilters,
            filteredTasks,
            runningTasksCount,
            terminateTask,
            showTaskResult,
            getTaskStatusLabel,
            getTaskTypeLabel,
            getTaskTitle,
            formatTime,
            // Draggable Button
            taskButtonRef,
            taskButtonPosition,
            isDragging,
            startDrag,
            // Toast
            toastMessage,
            toastType,
            // Duplicate Task Dialog
            showDuplicateTaskDialog,
            duplicateTaskInfo,
            handleDuplicateTaskChoice,
            // Loading States
            creatingTask,
            // Disclaimer
            showDisclaimer,
            closeDisclaimer,
            // Portfolio Management
            portfolios,
            loadingPortfolios,
            loadPortfolios,
            displayCurrency,
            toggleCurrency,
            hideAmounts,
            toggleAmountVisibility,
            maskAmount,
            lastRefreshTime,
            rates,
            displayedTotalAssets,
            displayedTotalProfitLoss,
            displayedTotalDailyChange,
            showAddTransactionModal,
            selectedPortfolio,
            searchType,
            transactionForm,
            transactionSymbolSuggestions,
            transactionSymbolSelected,
            addTransaction,
            calculateTotal,
            calculateQuantity,
            openAddTransactionModal,
            handleTransactionSymbolSearch,
            selectTransactionSymbol,
            clearTransactionSymbol,
            currentPortfolio,
            // Cash Management
            showCashModal,
            cashForm,
            openCashModal,
            addCashTransaction,
            // Portfolio Stats & Cash Flow (v2.0)
            portfolioStats,
            loadPortfolioStats,
            showCashFlowModal,
            cashFlowForm,
            cashFlows,
            openCashFlowModal,
            submitCashFlow,
            loadCashFlows,
            deleteCashFlow,
            // Portfolio Grouping & Expansion
            portfoliosByType,
            totalAssetsValue,
            totalCost,
            totalProfitLoss,
            totalProfitLossPercent,
            expandedPortfolios,
            portfolioTransactions,
            loadingTransactions,
            togglePortfolioExpand,
            formatNumber,
            calculateAllocation,
            // Edit Mode
            editMode,
            showEditTransactionModal,
            editingTransaction,
            editTransactionForm,
            openEditTransactionModal,
            updateTransaction,
            deleteTransaction,
            showEditCashModal,
            editingCash,
            editCashForm,
            openEditCashModal,
            updateCashBalance,
            // Stock Tracking
            loadingTracking,
            trackingRefreshing,
            trackingRunning,
            trackingSummary,
            trackingHoldings,
            trackingTransactions,
            trackingDecisions,
            trackingBenchmark,
            trackingChartRef,
            selectedDecision,
            expandedHoldingId,
            loadTrackingData,
            refreshTrackingPrices,
            runTrackingDecision
        };
    }
}).mount('#app');
