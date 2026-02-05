module.exports = [
"[externals]/next/dist/compiled/next-server/app-page-turbo.runtime.dev.js [external] (next/dist/compiled/next-server/app-page-turbo.runtime.dev.js, cjs)", ((__turbopack_context__, module, exports) => {

const mod = __turbopack_context__.x("next/dist/compiled/next-server/app-page-turbo.runtime.dev.js", () => require("next/dist/compiled/next-server/app-page-turbo.runtime.dev.js"));

module.exports = mod;
}),
"[project]/types/navigation.ts [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "CONFIG_STORAGE_KEY",
    ()=>CONFIG_STORAGE_KEY,
    "DEFAULT_NAV_CONFIG",
    ()=>DEFAULT_NAV_CONFIG,
    "LEVEL_NAMES",
    ()=>LEVEL_NAMES,
    "MINI_NODE_VALUES_KEY",
    ()=>MINI_NODE_VALUES_KEY,
    "STORAGE_KEY",
    ()=>STORAGE_KEY
]);
const LEVEL_NAMES = {
    1: 'COLLAPSED',
    2: 'MAIN_EXPANDED',
    3: 'SUB_EXPANDED',
    4: 'MINI_ACTIVE',
    5: 'CONFIRMED_ORBIT'
};
const DEFAULT_NAV_CONFIG = {
    entryStyle: 'radial-spin',
    exitStyle: 'symmetric',
    speedMultiplier: 1.0,
    staggerDelay: 100
};
const STORAGE_KEY = 'iris-nav-state';
const CONFIG_STORAGE_KEY = 'iris-nav-config';
const MINI_NODE_VALUES_KEY = 'iris-mini-node-values';
}),
"[project]/contexts/NavigationContext.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "NavigationProvider",
    ()=>NavigationProvider,
    "useIsTransitioning",
    ()=>useIsTransitioning,
    "useNavigation",
    ()=>useNavigation,
    "useNavigationLevel",
    ()=>useNavigationLevel,
    "useTransitionDirection",
    ()=>useTransitionDirection
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$types$2f$navigation$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/types/navigation.ts [app-ssr] (ecmascript)");
"use client";
;
;
;
const CONFIRMED_NODES_KEY = 'irisvoice_confirmed_nodes';
const initialState = {
    level: 1,
    history: [],
    selectedMain: null,
    selectedSub: null,
    selectedMini: null,
    isTransitioning: false,
    transitionDirection: null,
    // Mini node stack state (Level 4)
    miniNodeStack: [],
    activeMiniNodeIndex: 0,
    confirmedMiniNodes: [],
    miniNodeValues: {}
};
function navReducer(state, action) {
    console.log('[DEBUG] navReducer ENTRY:', {
        actionType: action.type,
        currentLevel: state.level,
        isTransitioning: state.isTransitioning,
        selectedMain: state.selectedMain
    });
    switch(action.type){
        case 'EXPAND_TO_MAIN':
            {
                if (state.level !== 1) return state;
                return {
                    ...state,
                    level: 2,
                    history: [
                        ...state.history,
                        {
                            level: 1,
                            nodeId: null
                        }
                    ],
                    transitionDirection: 'forward'
                };
            }
        case 'SELECT_MAIN':
            {
                console.log('[DEBUG] Reducer SELECT_MAIN:', {
                    currentLevel: state.level,
                    nodeId: action.payload.nodeId,
                    isTransitioning: state.isTransitioning
                });
                // Allow transition even if level changed due to React batching
                return {
                    ...state,
                    level: 3,
                    selectedMain: action.payload.nodeId,
                    history: [
                        ...state.history,
                        {
                            level: 2,
                            nodeId: null
                        }
                    ],
                    transitionDirection: 'forward'
                };
            }
        case 'SELECT_SUB':
            {
                console.log('[Nav System] Reducer SELECT_SUB:', {
                    currentLevel: state.level,
                    subnodeId: action.payload.subnodeId,
                    miniNodesCount: action.payload.miniNodes.length
                });
                // Allow transition even if level is transitioning (level 3 or 4)
                return {
                    ...state,
                    level: 4,
                    selectedSub: action.payload.subnodeId,
                    miniNodeStack: action.payload.miniNodes,
                    activeMiniNodeIndex: 0,
                    confirmedMiniNodes: [],
                    history: [
                        ...state.history,
                        {
                            level: 3,
                            nodeId: state.selectedMain
                        }
                    ],
                    transitionDirection: 'forward'
                };
            }
        case 'CONFIRM_MINI':
            {
                if (state.level !== 4) return state;
                return {
                    ...state,
                    level: 5,
                    selectedMini: action.payload.nodeId,
                    history: [
                        ...state.history,
                        {
                            level: 4,
                            nodeId: state.selectedSub
                        }
                    ],
                    transitionDirection: 'forward'
                };
            }
        case 'GO_BACK':
            {
                if (state.level === 1) return state;
                const newLevel = state.level - 1;
                const newHistory = state.history.slice(0, -1);
                let newSelectedMain = state.selectedMain;
                let newSelectedSub = state.selectedSub;
                let newSelectedMini = state.selectedMini;
                let newMiniNodeStack = state.miniNodeStack;
                let newActiveMiniNodeIndex = state.activeMiniNodeIndex;
                let newConfirmedMiniNodes = state.confirmedMiniNodes;
                if (newLevel === 1) {
                    newSelectedMain = null;
                    newSelectedSub = null;
                    newSelectedMini = null;
                    newMiniNodeStack = [];
                    newActiveMiniNodeIndex = 0;
                    newConfirmedMiniNodes = [];
                } else if (newLevel === 2) {
                    newSelectedMain = null;
                    newSelectedSub = null;
                    newSelectedMini = null;
                    newMiniNodeStack = [];
                    newActiveMiniNodeIndex = 0;
                    newConfirmedMiniNodes = [];
                } else if (newLevel === 3) {
                    newSelectedSub = null;
                    newSelectedMini = null;
                    newMiniNodeStack = [];
                    newActiveMiniNodeIndex = 0;
                    newConfirmedMiniNodes = [];
                } else if (newLevel === 4) {
                    newSelectedMini = null;
                }
                return {
                    ...state,
                    level: newLevel,
                    history: newHistory,
                    selectedMain: newSelectedMain,
                    selectedSub: newSelectedSub,
                    selectedMini: newSelectedMini,
                    miniNodeStack: newMiniNodeStack,
                    activeMiniNodeIndex: newActiveMiniNodeIndex,
                    confirmedMiniNodes: newConfirmedMiniNodes,
                    transitionDirection: 'backward'
                };
            }
        case 'COLLAPSE_TO_IDLE':
            {
                return {
                    ...initialState,
                    miniNodeValues: state.miniNodeValues,
                    transitionDirection: 'backward'
                };
            }
        case 'SET_TRANSITIONING':
            {
                return {
                    ...state,
                    isTransitioning: action.payload,
                    transitionDirection: action.payload ? state.transitionDirection : null
                };
            }
        case 'RESTORE_STATE':
            {
                // Validate and normalize restored state to prevent level 0 from old storage
                const restoredLevel = action.payload.level;
                const validLevel = restoredLevel >= 1 && restoredLevel <= 5 ? restoredLevel : 1;
                return {
                    ...action.payload,
                    level: validLevel,
                    isTransitioning: false,
                    transitionDirection: null
                };
            }
        // Mini node stack actions
        case 'ROTATE_STACK_FORWARD':
            {
                if (state.level !== 4 || state.miniNodeStack.length === 0) return state;
                const newIndex = (state.activeMiniNodeIndex + 1) % state.miniNodeStack.length;
                return {
                    ...state,
                    activeMiniNodeIndex: newIndex
                };
            }
        case 'ROTATE_STACK_BACKWARD':
            {
                if (state.level !== 4 || state.miniNodeStack.length === 0) return state;
                const newIndex = state.activeMiniNodeIndex === 0 ? state.miniNodeStack.length - 1 : state.activeMiniNodeIndex - 1;
                return {
                    ...state,
                    activeMiniNodeIndex: newIndex
                };
            }
        case 'JUMP_TO_MINI_NODE':
            {
                if (state.level !== 4) return state;
                const index = action.payload.index;
                if (index < 0 || index >= state.miniNodeStack.length) return state;
                return {
                    ...state,
                    activeMiniNodeIndex: index
                };
            }
        case 'CONFIRM_MINI_NODE':
            {
                if (state.level !== 4) return state;
                const { id, values } = action.payload;
                const miniNode = state.miniNodeStack.find((n)=>n.id === id);
                if (!miniNode) return state;
                // Check if already confirmed
                if (state.confirmedMiniNodes.some((n)=>n.id === id)) return state;
                // Limit to 8 confirmed nodes
                if (state.confirmedMiniNodes.length >= 8) return state;
                const confirmedNode = {
                    id,
                    label: miniNode.label,
                    icon: miniNode.icon,
                    values,
                    orbitAngle: (state.confirmedMiniNodes.length * 45 - 90) % 360,
                    timestamp: Date.now()
                };
                return {
                    ...state,
                    confirmedMiniNodes: [
                        ...state.confirmedMiniNodes,
                        confirmedNode
                    ],
                    miniNodeValues: {
                        ...state.miniNodeValues,
                        [id]: values
                    }
                };
            }
        case 'RECALL_CONFIRMED_NODE':
            {
                if (state.level !== 4) return state;
                const nodeId = action.payload.id;
                const nodeIndex = state.miniNodeStack.findIndex((n)=>n.id === nodeId);
                if (nodeIndex === -1) return state;
                return {
                    ...state,
                    activeMiniNodeIndex: nodeIndex
                };
            }
        case 'UPDATE_MINI_NODE_VALUE':
            {
                const { nodeId, fieldId, value } = action.payload;
                return {
                    ...state,
                    miniNodeValues: {
                        ...state.miniNodeValues,
                        [nodeId]: {
                            ...state.miniNodeValues[nodeId],
                            [fieldId]: value
                        }
                    }
                };
            }
        case 'CLEAR_MINI_NODE_STATE':
            {
                return {
                    ...state,
                    miniNodeStack: [],
                    activeMiniNodeIndex: 0,
                    confirmedMiniNodes: []
                };
            }
        default:
            return state;
    }
}
function getIrisOrbState(state, mainNodeLabels, subNodeLabels) {
    switch(state.level){
        case 1:
            return {
                label: 'IRIS',
                icon: 'home',
                showBackIndicator: false
            };
        case 2:
            return {
                label: 'CLOSE',
                icon: 'close',
                showBackIndicator: true
            };
        case 3:
            return {
                label: state.selectedMain ? mainNodeLabels[state.selectedMain] || state.selectedMain.toUpperCase() : 'BACK',
                icon: 'back',
                showBackIndicator: true
            };
        case 4:
            return {
                label: state.selectedSub ? subNodeLabels[state.selectedSub] || state.selectedSub.toUpperCase() : 'BACK',
                icon: 'back',
                showBackIndicator: true
            };
        case 5:
            return {
                label: state.selectedMini ? state.selectedMini.toUpperCase() : 'DONE',
                icon: 'back',
                showBackIndicator: true
            };
        default:
            return {
                label: 'IRIS',
                icon: 'home',
                showBackIndicator: false
            };
    }
}
const NavigationContext = /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["createContext"])(null);
function NavigationProvider({ children }) {
    const [state, dispatch] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useReducer"])(navReducer, initialState);
    const [config, setConfig] = __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["default"].useState(__TURBOPACK__imported__module__$5b$project$5d2f$types$2f$navigation$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["DEFAULT_NAV_CONFIG"]);
    const [mainNodeLabels, setMainNodeLabels] = __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["default"].useState({});
    const [subNodeLabels, setSubNodeLabels] = __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["default"].useState({});
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        // Clear any saved navigation state on startup - start fresh at level 1
        // Only restore configuration, not navigation position
        try {
            localStorage.removeItem(__TURBOPACK__imported__module__$5b$project$5d2f$types$2f$navigation$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["STORAGE_KEY"]);
        } catch (e) {
        // Ignore
        }
        try {
            const savedConfig = localStorage.getItem(__TURBOPACK__imported__module__$5b$project$5d2f$types$2f$navigation$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["CONFIG_STORAGE_KEY"]);
            if (savedConfig) {
                setConfig({
                    ...__TURBOPACK__imported__module__$5b$project$5d2f$types$2f$navigation$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["DEFAULT_NAV_CONFIG"],
                    ...JSON.parse(savedConfig)
                });
            }
        } catch (e) {
            console.warn('[NavigationContext] Failed to restore config:', e);
        }
        // Load mini node values from localStorage
        try {
            const savedMiniValues = localStorage.getItem(__TURBOPACK__imported__module__$5b$project$5d2f$types$2f$navigation$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["MINI_NODE_VALUES_KEY"]);
            if (savedMiniValues) {
                const parsed = JSON.parse(savedMiniValues);
                // Restore into initialState through a special action
                dispatch({
                    type: 'RESTORE_STATE',
                    payload: {
                        ...initialState,
                        miniNodeValues: parsed
                    }
                });
            }
        } catch (e) {
            console.warn('[NavigationContext] Failed to restore mini node values:', e);
        }
        // Load confirmed nodes from localStorage
        try {
            const savedConfirmedNodes = localStorage.getItem(CONFIRMED_NODES_KEY);
            if (savedConfirmedNodes) {
                const parsed = JSON.parse(savedConfirmedNodes);
                dispatch({
                    type: 'RESTORE_STATE',
                    payload: {
                        ...initialState,
                        confirmedMiniNodes: parsed
                    }
                });
            }
        } catch (e) {
            console.warn('[NavigationContext] Failed to restore confirmed nodes:', e);
        }
    }, []);
    // Navigation state is NOT persisted - always start fresh at level 1
    // Only configuration settings and mini node values are saved
    // Persist mini node values to localStorage
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        try {
            localStorage.setItem(__TURBOPACK__imported__module__$5b$project$5d2f$types$2f$navigation$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["MINI_NODE_VALUES_KEY"], JSON.stringify(state.miniNodeValues));
        } catch (e) {
            console.warn('[NavigationContext] Failed to save mini node values:', e);
        }
    }, [
        state.miniNodeValues
    ]);
    // Persist confirmed nodes to localStorage
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        try {
            localStorage.setItem(CONFIRMED_NODES_KEY, JSON.stringify(state.confirmedMiniNodes));
        } catch (e) {
            console.warn('[NavigationContext] Failed to save confirmed nodes:', e);
        }
    }, [
        state.confirmedMiniNodes
    ]);
    const goBack = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        if (state.isTransitioning) return;
        dispatch({
            type: 'GO_BACK'
        });
    }, [
        state.isTransitioning
    ]);
    const expandToMain = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        if (state.isTransitioning) return;
        dispatch({
            type: 'EXPAND_TO_MAIN'
        });
    }, [
        state.isTransitioning
    ]);
    const selectMain = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((nodeId)=>{
        console.log('[DEBUG] selectMain called:', {
            nodeId,
            level: state.level
        });
        dispatch({
            type: 'SELECT_MAIN',
            payload: {
                nodeId
            }
        });
    }, [
        state.level
    ]);
    const selectSub = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((subnodeId, miniNodes)=>{
        if (state.isTransitioning) return;
        dispatch({
            type: 'SELECT_SUB',
            payload: {
                subnodeId,
                miniNodes
            }
        });
    }, [
        state.isTransitioning
    ]);
    const confirmMini = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((nodeId)=>{
        if (state.isTransitioning) return;
        dispatch({
            type: 'CONFIRM_MINI',
            payload: {
                nodeId
            }
        });
    }, [
        state.isTransitioning
    ]);
    const collapseToIdle = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        if (state.isTransitioning) return;
        dispatch({
            type: 'COLLAPSE_TO_IDLE'
        });
    }, [
        state.isTransitioning
    ]);
    const setTransitioning = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((value)=>{
        dispatch({
            type: 'SET_TRANSITIONING',
            payload: value
        });
    }, []);
    const updateConfig = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((newConfig)=>{
        setConfig((prev)=>{
            const updated = {
                ...prev,
                ...newConfig
            };
            try {
                localStorage.setItem(__TURBOPACK__imported__module__$5b$project$5d2f$types$2f$navigation$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["CONFIG_STORAGE_KEY"], JSON.stringify(updated));
            } catch (e) {
                console.warn('[NavigationContext] Failed to save config:', e);
            }
            return updated;
        });
    }, []);
    const setNodeLabels = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((main, sub)=>{
        setMainNodeLabels(main);
        setSubNodeLabels(sub);
    }, []);
    // Mini node stack helper functions
    const rotateStackForward = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        if (state.isTransitioning) return;
        dispatch({
            type: 'ROTATE_STACK_FORWARD'
        });
    }, [
        state.isTransitioning
    ]);
    const rotateStackBackward = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        if (state.isTransitioning) return;
        dispatch({
            type: 'ROTATE_STACK_BACKWARD'
        });
    }, [
        state.isTransitioning
    ]);
    const jumpToMiniNode = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((index)=>{
        if (state.isTransitioning) return;
        dispatch({
            type: 'JUMP_TO_MINI_NODE',
            payload: {
                index
            }
        });
    }, [
        state.isTransitioning
    ]);
    const confirmMiniNode = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((id, values)=>{
        if (state.isTransitioning) return;
        dispatch({
            type: 'CONFIRM_MINI_NODE',
            payload: {
                id,
                values
            }
        });
    }, [
        state.isTransitioning
    ]);
    const updateMiniNodeValue = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((nodeId, fieldId, value)=>{
        dispatch({
            type: 'UPDATE_MINI_NODE_VALUE',
            payload: {
                nodeId,
                fieldId,
                value
            }
        });
    }, []);
    const recallConfirmedNode = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((id)=>{
        if (state.isTransitioning) return;
        dispatch({
            type: 'RECALL_CONFIRMED_NODE',
            payload: {
                id
            }
        });
    }, [
        state.isTransitioning
    ]);
    const orbState = getIrisOrbState(state, mainNodeLabels, subNodeLabels);
    const value = {
        state,
        config,
        orbState,
        dispatch,
        goBack,
        expandToMain,
        selectMain,
        selectSub,
        confirmMini,
        collapseToIdle,
        setTransitioning,
        updateConfig,
        setNodeLabels,
        // Mini node stack helpers
        rotateStackForward,
        rotateStackBackward,
        jumpToMiniNode,
        confirmMiniNode,
        updateMiniNodeValue,
        recallConfirmedNode
    };
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(NavigationContext.Provider, {
        value: value,
        children: children
    }, void 0, false, {
        fileName: "[project]/contexts/NavigationContext.tsx",
        lineNumber: 520,
        columnNumber: 5
    }, this);
}
function useNavigation() {
    const context = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useContext"])(NavigationContext);
    if (!context) {
        throw new Error('useNavigation must be used within a NavigationProvider');
    }
    return context;
}
function useNavigationLevel() {
    const { state } = useNavigation();
    return state.level;
}
function useIsTransitioning() {
    const { state } = useNavigation();
    return state.isTransitioning;
}
function useTransitionDirection() {
    const { state } = useNavigation();
    return state.transitionDirection;
}
}),
"[project]/contexts/BrandColorContext.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "BrandColorProvider",
    ()=>BrandColorProvider,
    "PRISM_THEMES",
    ()=>PRISM_THEMES,
    "useBrandColor",
    ()=>useBrandColor
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
'use client';
;
;
// === DEFAULT VALUES ===
const DEFAULT_THEME = 'aether';
// Basic HSL defaults (kept for backwards compatibility)
const THEME_DEFAULTS = {
    aether: {
        hue: 210,
        saturation: 40,
        lightness: 55
    },
    ember: {
        hue: 30,
        saturation: 70,
        lightness: 50
    },
    aurum: {
        hue: 45,
        saturation: 90,
        lightness: 55
    },
    verdant: {
        hue: 145,
        saturation: 80,
        lightness: 45
    }
};
const PRISM_THEMES = {
    aether: {
        name: 'Aether',
        description: 'Cool, ethereal blues/purples',
        mood: 'Calm, airy, futuristic',
        hue: 210,
        saturation: 40,
        lightness: 55,
        gradient: {
            from: 'hsl(220, 40%, 15%)',
            to: 'hsl(190, 40%, 55%)',
            angle: 135
        },
        shimmer: {
            primary: 'hsl(200, 40%, 70%)',
            secondary: 'hsl(260, 40%, 65%)',
            accent: 'hsl(180, 40%, 60%)'
        },
        orbs: [
            {
                color: 'hsl(200, 100%, 60%)',
                size: 80,
                blur: 40,
                x: -30,
                y: -20
            },
            {
                color: 'hsl(260, 80%, 65%)',
                size: 60,
                blur: 30,
                x: 40,
                y: 30
            },
            {
                color: 'hsl(180, 90%, 55%)',
                size: 50,
                blur: 25,
                x: -20,
                y: 40
            }
        ],
        text: {
            primary: 'rgba(255, 255, 255, 0.95)',
            secondary: 'rgba(255, 255, 255, 0.70)'
        },
        glass: {
            opacity: 0.18,
            blur: 24,
            borderOpacity: 0.15
        },
        glow: {
            color: '#00c8ff',
            opacity: 0.3,
            blur: 12
        }
    },
    ember: {
        name: 'Ember',
        description: 'Warm oranges/reds/pinks',
        mood: 'Energetic, sunset, passionate',
        hue: 30,
        saturation: 70,
        lightness: 50,
        gradient: {
            from: 'hsl(350, 70%, 20%)',
            to: 'hsl(25, 90%, 55%)',
            angle: 135
        },
        shimmer: {
            primary: 'hsl(25, 100%, 60%)',
            secondary: 'hsl(350, 80%, 55%)',
            accent: 'hsl(15, 100%, 65%)'
        },
        orbs: [
            {
                color: 'hsl(25, 100%, 55%)',
                size: 70,
                blur: 35,
                x: -25,
                y: -15
            },
            {
                color: 'hsl(350, 80%, 60%)',
                size: 55,
                blur: 28,
                x: 35,
                y: 25
            },
            {
                color: 'hsl(15, 100%, 60%)',
                size: 45,
                blur: 22,
                x: -15,
                y: 35
            }
        ],
        text: {
            primary: 'rgba(255, 255, 255, 0.95)',
            secondary: 'rgba(255, 255, 255, 0.70)'
        },
        glass: {
            opacity: 0.17,
            blur: 24,
            borderOpacity: 0.15
        },
        glow: {
            color: '#ff6432',
            opacity: 0.35,
            blur: 12
        }
    },
    aurum: {
        name: 'Aurum',
        description: 'Rich golds/ambers/yellows',
        mood: 'Luxurious, warm, premium',
        hue: 45,
        saturation: 90,
        lightness: 55,
        gradient: {
            from: '#523a15',
            to: '#d4a31c',
            angle: 135
        },
        shimmer: {
            primary: '#f5c842',
            secondary: '#f0e62e',
            accent: '#d9a31a' // Converted from hsl(35, 80%, 60%)
        },
        orbs: [
            {
                color: '#f0c020',
                size: 75,
                blur: 38,
                x: -20,
                y: -25
            },
            {
                color: '#ebe026',
                size: 58,
                blur: 32,
                x: 30,
                y: 20
            },
            {
                color: '#e6c228',
                size: 48,
                blur: 24,
                x: -25,
                y: 30
            } // Brighter amber
        ],
        text: {
            primary: 'rgba(255, 255, 255, 0.95)',
            secondary: 'rgba(255, 255, 255, 0.75)'
        },
        glass: {
            opacity: 0.20,
            blur: 24,
            borderOpacity: 0.18 // Increased from 0.12
        },
        glow: {
            color: '#ffc832',
            opacity: 0.40,
            blur: 12
        }
    },
    verdant: {
        name: 'Verdant',
        description: 'Vibrant emerald green with glass feel',
        mood: 'Natural, fresh, organic',
        hue: 145,
        saturation: 100,
        lightness: 55,
        gradient: {
            from: '#064d1a',
            to: '#0d8f2e',
            angle: 135
        },
        shimmer: {
            primary: '#00ff77',
            secondary: '#00dd55',
            accent: '#00ff99' // Light mint
        },
        orbs: null,
        text: {
            primary: 'rgba(255, 255, 255, 0.95)',
            secondary: 'rgba(255, 255, 255, 0.85)'
        },
        glass: {
            opacity: 0.25,
            blur: 24,
            borderOpacity: 0.30 // Stronger border
        },
        glow: {
            color: '#00ff77',
            opacity: 0.60,
            blur: 18
        }
    }
};
const STORAGE_KEY_BRAND = 'iris-brand-color';
const STORAGE_KEY_THEME = 'iris-preferred-theme';
// === CONTEXT ===
const BrandColorContext = /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["createContext"])(undefined);
function BrandColorProvider({ children }) {
    // Start with default values for SSR consistency
    const [brandColor, setBrandColor] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(THEME_DEFAULTS[DEFAULT_THEME]);
    const [theme, setThemeState] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(DEFAULT_THEME);
    const [isMounted, setIsMounted] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    // After mount, load from localStorage to avoid hydration mismatch
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        const storedBrand = localStorage.getItem(STORAGE_KEY_BRAND);
        const storedTheme = localStorage.getItem(STORAGE_KEY_THEME);
        console.log('[BrandColorContext] Mount - storedBrand:', storedBrand);
        console.log('[BrandColorContext] Mount - storedTheme:', storedTheme);
        console.log('[BrandColorContext] Mount - current default:', THEME_DEFAULTS[DEFAULT_THEME]);
        // Determine which theme to use
        const themeToUse = storedTheme && [
            'aether',
            'ember',
            'aurum',
            'verdant'
        ].includes(storedTheme) ? storedTheme : DEFAULT_THEME;
        // Get expected defaults for this theme
        const expectedDefaults = THEME_DEFAULTS[themeToUse];
        if (storedBrand) {
            try {
                const parsed = JSON.parse(storedBrand);
                console.log('[BrandColorContext] Mount - Loading brand from localStorage:', parsed);
                // Validate: Check if stored values match expected theme defaults (within tolerance)
                const hueDiff = Math.abs(parsed.hue - expectedDefaults.hue);
                const satDiff = Math.abs(parsed.saturation - expectedDefaults.saturation);
                const lightDiff = Math.abs(parsed.lightness - expectedDefaults.lightness);
                // If values are very different from expected, use defaults instead
                if (hueDiff > 30 || satDiff > 20 || lightDiff > 20) {
                    console.log('[BrandColorContext] Mount - Stored brand mismatch, using defaults:', expectedDefaults);
                    setBrandColor(expectedDefaults);
                } else {
                    setBrandColor(parsed);
                }
            } catch  {
                // Keep default if parsing fails
                console.log('[BrandColorContext] Mount - Failed to parse storedBrand, using default');
                setBrandColor(expectedDefaults);
            }
        }
        if (storedTheme && [
            'aether',
            'ember',
            'aurum',
            'verdant'
        ].includes(storedTheme)) {
            console.log('[BrandColorContext] Mount - Loading theme from localStorage:', storedTheme);
            setThemeState(storedTheme);
        }
        setIsMounted(true);
    }, []);
    // Persist brand color to localStorage
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        localStorage.setItem(STORAGE_KEY_BRAND, JSON.stringify(brandColor));
    }, [
        brandColor
    ]);
    // Persist theme to localStorage
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        localStorage.setItem(STORAGE_KEY_THEME, theme);
    }, [
        theme
    ]);
    // Apply CSS variables when brand color changes
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        const root = document.documentElement;
        root.style.setProperty('--brand-hue', brandColor.hue.toString());
        root.style.setProperty('--brand-saturation', `${brandColor.saturation}%`);
        root.style.setProperty('--brand-lightness', `${brandColor.lightness}%`);
        // Apply theme-specific adjustments
        applyThemeAdjustments(theme, brandColor);
    }, [
        brandColor,
        theme
    ]);
    // Apply theme data attribute
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        document.documentElement.setAttribute('data-theme', theme);
    }, [
        theme
    ]);
    const setHue = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((hue)=>{
        setBrandColor((prev)=>({
                ...prev,
                hue: Math.max(0, Math.min(360, hue))
            }));
    }, []);
    const setSaturation = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((saturation)=>{
        setBrandColor((prev)=>({
                ...prev,
                saturation: Math.max(0, Math.min(100, saturation))
            }));
    }, []);
    const setLightness = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((lightness)=>{
        setBrandColor((prev)=>({
                ...prev,
                lightness: Math.max(0, Math.min(100, lightness))
            }));
    }, []);
    const setTheme = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((newTheme)=>{
        console.log('[BrandColorContext] setTheme called:', newTheme);
        console.log('[BrandColorContext] Setting brandColor to defaults:', THEME_DEFAULTS[newTheme]);
        setThemeState(newTheme);
        // Update brand color to theme default so colors actually change
        setBrandColor(THEME_DEFAULTS[newTheme]);
        // Clear localStorage for brand color to prevent override
        localStorage.removeItem(STORAGE_KEY_BRAND);
    }, []);
    const resetToThemeDefault = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        console.log('[BrandColorContext] resetToThemeDefault called for theme:', theme);
        setBrandColor(THEME_DEFAULTS[theme]);
        localStorage.removeItem(STORAGE_KEY_BRAND);
    }, [
        theme
    ]);
    const getHSLString = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        return `hsl(${brandColor.hue}, ${brandColor.saturation}%, ${brandColor.lightness}%)`;
    }, [
        brandColor
    ]);
    const getThemeConfig = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        return PRISM_THEMES[theme];
    }, [
        theme
    ]);
    const getAccessibleLightness = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((backgroundLuminance)=>{
        // WCAG AA requires 4.5:1 for normal text, 3:1 for large text
        // Simplified calculation - ensure sufficient contrast
        const targetContrast = 4.5;
        const currentLightness = brandColor.lightness;
        // If background is dark (low luminance), we need lighter text
        // If background is light (high luminance), we need darker text
        if (backgroundLuminance < 0.5) {
            // Dark background - ensure lightness is high enough
            return Math.max(currentLightness, 60);
        } else {
            // Light background - ensure lightness is low enough
            return Math.min(currentLightness, 40);
        }
    }, [
        brandColor.lightness
    ]);
    const value = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useMemo"])(()=>({
            brandColor,
            theme,
            isMounted,
            setHue,
            setSaturation,
            setLightness,
            setTheme,
            resetToThemeDefault,
            getHSLString,
            getAccessibleLightness,
            getThemeConfig
        }), [
        brandColor,
        theme,
        isMounted,
        setHue,
        setSaturation,
        setLightness,
        setTheme,
        resetToThemeDefault,
        getHSLString,
        getAccessibleLightness,
        getThemeConfig
    ]);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(BrandColorContext.Provider, {
        value: value,
        children: children
    }, void 0, false, {
        fileName: "[project]/contexts/BrandColorContext.tsx",
        lineNumber: 393,
        columnNumber: 5
    }, this);
}
// === THEME-SPECIFIC ADJUSTMENTS ===
function applyThemeAdjustments(theme, brandColor) {
    const root = document.documentElement;
    switch(theme){
        case 'aether':
            // Aether: Full vibrancy allowed
            root.style.setProperty('--aether-shimmer-start', `hsl(${brandColor.hue}, 90%, 60%)`);
            root.style.setProperty('--aether-shimmer-mid', `hsl(${(brandColor.hue + 30) % 360}, 80%, 65%)`);
            root.style.setProperty('--aether-shimmer-end', `hsl(${(brandColor.hue + 60) % 360}, 70%, 55%)`);
            break;
        case 'ember':
            // Ember: Cap saturation at 70%, add warmth shift (+10°)
            const emberSat = Math.min(brandColor.saturation, 70);
            const emberHue = (brandColor.hue + 10) % 360;
            root.style.setProperty('--ember-edge-glow', `hsl(${emberHue}, ${emberSat * 0.6}%, 45%)`);
            root.style.setProperty('--ember-edge-soft', `hsl(${emberHue}, ${emberSat * 0.5}%, 50%, 0.3)`);
            break;
        case 'aurum':
            // Aurum: Heavy desaturation (40% of base) for metallic effect
            const aurumSat = brandColor.saturation * 0.4;
            root.style.setProperty('--aurum-metal-primary', `hsl(${brandColor.hue}, ${aurumSat}%, 55%)`);
            root.style.setProperty('--aurum-metal-secondary', `hsl(${(brandColor.hue - 20 + 360) % 360}, ${aurumSat * 1.25}%, 45%)`);
            root.style.setProperty('--aurum-metal-highlight', `hsl(${brandColor.hue}, ${aurumSat * 1.5}%, 70%)`);
            break;
    }
}
function useBrandColor() {
    const context = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useContext"])(BrandColorContext);
    if (context === undefined) {
        throw new Error('useBrandColor must be used within a BrandColorProvider');
    }
    return context;
}
}),
"[project]/contexts/TransitionContext.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "TransitionProvider",
    ()=>TransitionProvider,
    "getTransitionByIndex",
    ()=>getTransitionByIndex,
    "getTransitionIndex",
    ()=>getTransitionIndex,
    "useTransition",
    ()=>useTransition
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
'use client';
;
;
// === DEFAULT VALUES ===
const DEFAULT_TRANSITION = 'radial-spin';
const TRANSITION_ORDER = [
    'radial-spin',
    'pure-fade',
    'pop-out',
    'clockwork',
    'holographic'
];
const STORAGE_KEY = 'iris-transition-type';
// === CONTEXT ===
const TransitionContext = /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["createContext"])(undefined);
function TransitionProvider({ children }) {
    // Always start with default for SSR consistency
    const [currentTransition, setCurrentTransition] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(DEFAULT_TRANSITION);
    const [isHydrated, setIsHydrated] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    // Load from localStorage after hydration
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored && TRANSITION_ORDER.includes(stored)) {
            setCurrentTransition(stored);
        }
        setIsHydrated(true);
    }, []);
    // Persist transition preference to localStorage
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        if (isHydrated) {
            localStorage.setItem(STORAGE_KEY, currentTransition);
            console.log('[TransitionContext] Transition changed to:', currentTransition);
        }
    }, [
        currentTransition,
        isHydrated
    ]);
    const cycleTransition = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        setCurrentTransition((prev)=>{
            const currentIndex = TRANSITION_ORDER.indexOf(prev);
            const nextIndex = (currentIndex + 1) % TRANSITION_ORDER.length;
            const nextTransition = TRANSITION_ORDER[nextIndex];
            console.log('[TransitionContext] Cycling:', prev, '→', nextTransition);
            return nextTransition;
        });
    }, []);
    const setTransition = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((transition)=>{
        if (TRANSITION_ORDER.includes(transition)) {
            console.log('[TransitionContext] Setting transition:', transition);
            setCurrentTransition(transition);
        } else {
            console.warn('[TransitionContext] Invalid transition type:', transition);
        }
    }, []);
    const resetToDefault = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        console.log('[TransitionContext] Resetting to default:', DEFAULT_TRANSITION);
        setCurrentTransition(DEFAULT_TRANSITION);
    }, []);
    // Keyboard shortcuts
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        const handleKeyDown = (e)=>{
            // Ctrl+Shift+T: Cycle to next transition
            if (e.ctrlKey && e.shiftKey && e.key === 'T') {
                e.preventDefault();
                cycleTransition();
            }
            // Ctrl+Shift+R: Reset to default
            if (e.ctrlKey && e.shiftKey && e.key === 'R') {
                e.preventDefault();
                resetToDefault();
            }
            // Ctrl+Shift+1-5: Jump to specific transition
            if (e.ctrlKey && e.shiftKey && [
                '1',
                '2',
                '3',
                '4',
                '5'
            ].includes(e.key)) {
                e.preventDefault();
                const index = parseInt(e.key) - 1;
                if (index >= 0 && index < TRANSITION_ORDER.length) {
                    setTransition(TRANSITION_ORDER[index]);
                }
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        console.log('[TransitionContext] Keyboard shortcuts registered');
        return ()=>{
            window.removeEventListener('keydown', handleKeyDown);
            console.log('[TransitionContext] Keyboard shortcuts unregistered');
        };
    }, [
        cycleTransition,
        resetToDefault,
        setTransition
    ]);
    const value = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useMemo"])(()=>({
            currentTransition,
            cycleTransition,
            setTransition,
            resetToDefault,
            isHydrated
        }), [
        currentTransition,
        cycleTransition,
        setTransition,
        resetToDefault,
        isHydrated
    ]);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(TransitionContext.Provider, {
        value: value,
        children: children
    }, void 0, false, {
        fileName: "[project]/contexts/TransitionContext.tsx",
        lineNumber: 125,
        columnNumber: 5
    }, this);
}
function useTransition() {
    const context = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useContext"])(TransitionContext);
    if (context === undefined) {
        throw new Error('useTransition must be used within a TransitionProvider');
    }
    return context;
}
function getTransitionIndex(transition) {
    return TRANSITION_ORDER.indexOf(transition);
}
function getTransitionByIndex(index) {
    return TRANSITION_ORDER[index];
}
}),
"[project]/components/ui/transition-indicator.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "TransitionIndicator",
    ()=>TransitionIndicator
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$TransitionContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/TransitionContext.tsx [app-ssr] (ecmascript)");
'use client';
;
;
const TRANSITION_LABELS = {
    'radial-spin': 'Radial Spin',
    'pure-fade': 'Pure Fade',
    'pop-out': 'Pop Out',
    'clockwork': 'Clockwork',
    'holographic': 'Holographic'
};
function TransitionIndicator() {
    const { currentTransition, cycleTransition, resetToDefault, isHydrated } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$TransitionContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useTransition"])();
    // Only show in development and after hydration to avoid SSR mismatch
    if (("TURBOPACK compile-time value", "development") === 'production' || !isHydrated) {
        return null;
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "fixed bottom-4 right-4 z-50 flex items-center gap-2 px-3 py-2 rounded-lg backdrop-blur-md border border-white/10 bg-black/60 text-xs font-mono transition-all duration-200 hover:bg-black/80",
        style: {
            pointerEvents: 'auto'
        },
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "flex flex-col gap-1",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "flex items-center gap-2",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                className: "text-white/60",
                                children: "Transition:"
                            }, void 0, false, {
                                fileName: "[project]/components/ui/transition-indicator.tsx",
                                lineNumber: 29,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                className: "text-cyan-400 font-medium",
                                children: TRANSITION_LABELS[currentTransition]
                            }, void 0, false, {
                                fileName: "[project]/components/ui/transition-indicator.tsx",
                                lineNumber: 30,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/components/ui/transition-indicator.tsx",
                        lineNumber: 28,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "flex items-center gap-1 text-white/40 text-[10px]",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("kbd", {
                                className: "px-1 py-0.5 rounded bg-white/10",
                                children: "Ctrl"
                            }, void 0, false, {
                                fileName: "[project]/components/ui/transition-indicator.tsx",
                                lineNumber: 35,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "+"
                            }, void 0, false, {
                                fileName: "[project]/components/ui/transition-indicator.tsx",
                                lineNumber: 36,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("kbd", {
                                className: "px-1 py-0.5 rounded bg-white/10",
                                children: "Shift"
                            }, void 0, false, {
                                fileName: "[project]/components/ui/transition-indicator.tsx",
                                lineNumber: 37,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "+"
                            }, void 0, false, {
                                fileName: "[project]/components/ui/transition-indicator.tsx",
                                lineNumber: 38,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("kbd", {
                                className: "px-1 py-0.5 rounded bg-white/10",
                                children: "T"
                            }, void 0, false, {
                                fileName: "[project]/components/ui/transition-indicator.tsx",
                                lineNumber: 39,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: "to cycle"
                            }, void 0, false, {
                                fileName: "[project]/components/ui/transition-indicator.tsx",
                                lineNumber: 40,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/components/ui/transition-indicator.tsx",
                        lineNumber: 34,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/ui/transition-indicator.tsx",
                lineNumber: 27,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "flex flex-col gap-1 ml-2",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        onClick: cycleTransition,
                        className: "px-2 py-1 rounded bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 transition-colors",
                        children: "Next"
                    }, void 0, false, {
                        fileName: "[project]/components/ui/transition-indicator.tsx",
                        lineNumber: 44,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        onClick: resetToDefault,
                        className: "px-2 py-1 rounded bg-white/10 hover:bg-white/20 text-white/60 transition-colors",
                        children: "Reset"
                    }, void 0, false, {
                        fileName: "[project]/components/ui/transition-indicator.tsx",
                        lineNumber: 50,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/ui/transition-indicator.tsx",
                lineNumber: 43,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/components/ui/transition-indicator.tsx",
        lineNumber: 23,
        columnNumber: 5
    }, this);
}
}),
"[project]/lib/transitions.ts [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "getStaggerDelay",
    ()=>getStaggerDelay,
    "getTransitionName",
    ()=>getTransitionName,
    "getVariantsForTransition",
    ()=>getVariantsForTransition
]);
// === EASING FUNCTIONS ===
const easings = {
    pop: [
        0.34,
        1.56,
        0.64,
        1
    ],
    smooth: [
        0.4,
        0,
        0.2,
        1
    ],
    mechanical: [
        1,
        0,
        0,
        1
    ],
    gentle: [
        0.25,
        0.46,
        0.45,
        0.94
    ]
};
// === PURE FADE ===
// Just fade in place at final position - no movement, no scale change
const pureFadeVariants = {
    hidden: {
        opacity: 0
    },
    visible: {
        opacity: 1,
        transition: {
            duration: 0.3,
            ease: 'linear'
        }
    },
    exit: {
        opacity: 0,
        transition: {
            duration: 0.3,
            ease: 'linear'
        }
    }
};
// === POP OUT ===
// Scale and rotate on own axis at final position - no movement from center
// Duration matches navigation timeout (1.5s) with very gradual scale animation
const popOutVariants = {
    hidden: {
        scale: 1,
        rotate: 0,
        opacity: 1
    },
    visible: {
        scale: [
            1,
            0.9,
            0.7,
            0.4,
            0.2,
            0.1,
            0.3,
            0.6,
            0.9,
            1.3,
            1.1,
            1.0
        ],
        rotate: [
            0,
            30,
            60,
            120,
            240,
            360,
            480,
            540,
            600,
            660,
            700,
            720
        ],
        opacity: [
            1,
            0.95,
            0.85,
            0.6,
            0.4,
            0.2,
            0.5,
            0.7,
            0.9,
            1,
            1,
            1
        ],
        transition: {
            duration: 1.5,
            times: [
                0,
                0.08,
                0.15,
                0.25,
                0.35,
                0.45,
                0.55,
                0.65,
                0.75,
                0.85,
                0.92,
                1.0
            ],
            ease: easings.pop
        }
    },
    exit: {
        scale: [
            1.0,
            1.1,
            1.3,
            0.9,
            0.6,
            0.3,
            0.15,
            0.05,
            0
        ],
        rotate: [
            720,
            700,
            660,
            600,
            480,
            360,
            240,
            120,
            0
        ],
        opacity: [
            1,
            1,
            0.9,
            0.7,
            0.5,
            0.3,
            0.15,
            0.05,
            0
        ],
        transition: {
            duration: 1.5,
            times: [
                0,
                0.08,
                0.15,
                0.3,
                0.45,
                0.6,
                0.75,
                0.9,
                1.0
            ],
            ease: easings.pop
        }
    }
};
// === CLOCKWORK ===
// Dial-turning motion: nodes move in circular path
// Duration matches navigation timeout (1.5s) for smooth sync
const clockworkVariants = {
    hidden: {
        scale: 0,
        rotate: 0,
        opacity: 1
    },
    visible: {
        scale: [
            0,
            0.2,
            0.4,
            0.6,
            0.8,
            0.95,
            1.02,
            1
        ],
        opacity: [
            0.4,
            0.6,
            0.8,
            0.9,
            1,
            1,
            1,
            1
        ],
        transition: {
            duration: 1.5,
            times: [
                0,
                0.15,
                0.3,
                0.45,
                0.6,
                0.75,
                0.9,
                1
            ],
            ease: easings.mechanical
        }
    },
    exit: {
        scale: [
            1,
            1.02,
            0.95,
            0.8,
            0.6,
            0.4,
            0.2,
            0
        ],
        opacity: [
            1,
            1,
            1,
            0.9,
            0.8,
            0.6,
            0.4,
            0
        ],
        transition: {
            duration: 1.5,
            times: [
                0,
                0.1,
                0.25,
                0.4,
                0.55,
                0.7,
                0.85,
                1
            ],
            ease: easings.mechanical
        }
    }
};
// === HOLOGRAPHIC ===
// Glitch interference effects
// Duration matches navigation timeout (1.5s) for smooth sync
const holographicVariants = {
    hidden: {
        opacity: 0,
        rotateX: 90,
        filter: 'hue-rotate(180deg) brightness(1)'
    },
    visible: {
        opacity: [
            0,
            0.2,
            0.5,
            0.3,
            0.7,
            0.4,
            0.8,
            0.5,
            0.9,
            0.7,
            1,
            1
        ],
        rotateX: [
            90,
            70,
            45,
            30,
            15,
            10,
            5,
            3,
            1,
            0,
            0,
            0
        ],
        rotateY: [
            0,
            20,
            -15,
            10,
            -8,
            5,
            -3,
            2,
            -1,
            0,
            0,
            0
        ],
        filter: [
            'hue-rotate(180deg) brightness(1)',
            'hue-rotate(150deg) brightness(1.2)',
            'hue-rotate(90deg) brightness(1.3)',
            'hue-rotate(120deg) brightness(1.1)',
            'hue-rotate(45deg) brightness(1.2)',
            'hue-rotate(90deg) brightness(1)',
            'hue-rotate(0deg) brightness(1.1)',
            'hue-rotate(45deg) brightness(1)',
            'hue-rotate(0deg) brightness(1.05)',
            'blur(1px)',
            'blur(0px) saturate(1.1)',
            'blur(0px) saturate(1)'
        ],
        transition: {
            duration: 1.5,
            times: [
                0,
                0.08,
                0.15,
                0.23,
                0.31,
                0.4,
                0.5,
                0.6,
                0.72,
                0.85,
                0.93,
                1
            ],
            ease: 'linear'
        }
    },
    exit: {
        opacity: [
            1,
            0.7,
            0.9,
            0.5,
            0.8,
            0.4,
            0.7,
            0.3,
            0.5,
            0.2,
            0
        ],
        rotateX: [
            0,
            0,
            1,
            3,
            5,
            10,
            15,
            30,
            45,
            70,
            90
        ],
        rotateY: [
            0,
            0,
            1,
            -2,
            3,
            -5,
            8,
            -10,
            15,
            -20,
            0
        ],
        filter: [
            'blur(0px) saturate(1)',
            'blur(0px) saturate(1.1)',
            'blur(1px)',
            'hue-rotate(0deg) brightness(1.05)',
            'hue-rotate(45deg) brightness(1)',
            'hue-rotate(0deg) brightness(1.1)',
            'hue-rotate(90deg) brightness(1)',
            'hue-rotate(45deg) brightness(1.2)',
            'hue-rotate(120deg) brightness(1.1)',
            'hue-rotate(90deg) brightness(1.3)',
            'hue-rotate(180deg) brightness(1)'
        ],
        transition: {
            duration: 1.5,
            times: [
                0,
                0.1,
                0.18,
                0.27,
                0.37,
                0.48,
                0.58,
                0.68,
                0.78,
                0.9,
                1
            ],
            ease: 'linear'
        }
    }
};
// === RADIAL SPIN (Default) ===
// Spiral emergence with rotation
const radialSpinVariants = {
    hidden: {
        opacity: 0,
        scale: 0.5
    },
    visible: {
        opacity: 1,
        scale: 1,
        transition: {
            duration: 1.5,
            ease: easings.smooth
        }
    },
    exit: {
        opacity: 0,
        scale: 0.5,
        transition: {
            duration: 1.5,
            ease: easings.smooth
        }
    }
};
// === TRANSITION MAP ===
const transitionMap = {
    'radial-spin': radialSpinVariants,
    'pure-fade': pureFadeVariants,
    'pop-out': popOutVariants,
    'clockwork': clockworkVariants,
    'holographic': holographicVariants
};
function getVariantsForTransition(type) {
    return transitionMap[type] || radialSpinVariants;
}
function getStaggerDelay(type) {
    switch(type){
        case 'pure-fade':
            return 0.02;
        case 'pop-out':
            return 0.08;
        case 'clockwork':
            return 0.1;
        case 'holographic':
            return 0.06;
        default:
            return 0.1;
    }
}
function getTransitionName(type) {
    const names = {
        'radial-spin': 'Radial Spin',
        'pure-fade': 'Pure Fade',
        'pop-out': 'Pop Out',
        'clockwork': 'Clockwork',
        'holographic': 'Holographic'
    };
    return names[type] || type;
}
}),
"[project]/components/ui/transition-switch.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "TransitionSwitch",
    ()=>TransitionSwitch
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$TransitionContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/TransitionContext.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$lib$2f$transitions$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/lib/transitions.ts [app-ssr] (ecmascript)");
'use client';
;
;
;
const TRANSITIONS = [
    'radial-spin',
    'pure-fade',
    'pop-out',
    'clockwork',
    'holographic'
];
function TransitionSwitch() {
    const { currentTransition, setTransition, cycleTransition } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$TransitionContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useTransition"])();
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "fixed top-4 right-4 z-50 flex flex-col gap-2 p-3 rounded-xl backdrop-blur-md border border-white/10 bg-black/70",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "flex items-center justify-between mb-2",
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        className: "text-xs font-medium text-white/80",
                        children: "Transition Style"
                    }, void 0, false, {
                        fileName: "[project]/components/ui/transition-switch.tsx",
                        lineNumber: 21,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        onClick: cycleTransition,
                        className: "text-[10px] px-2 py-1 rounded bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 transition-colors",
                        children: "Cycle"
                    }, void 0, false, {
                        fileName: "[project]/components/ui/transition-switch.tsx",
                        lineNumber: 22,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/ui/transition-switch.tsx",
                lineNumber: 20,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "flex gap-1",
                children: TRANSITIONS.map((t, i)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        onClick: ()=>setTransition(t),
                        className: `w-8 h-8 rounded-lg text-[10px] font-medium transition-all ${currentTransition === t ? 'bg-cyan-500 text-white shadow-lg shadow-cyan-500/30' : 'bg-white/5 text-white/40 hover:bg-white/10 hover:text-white/60'}`,
                        title: (0, __TURBOPACK__imported__module__$5b$project$5d2f$lib$2f$transitions$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["getTransitionName"])(t),
                        children: i + 1
                    }, t, false, {
                        fileName: "[project]/components/ui/transition-switch.tsx",
                        lineNumber: 32,
                        columnNumber: 11
                    }, this))
            }, void 0, false, {
                fileName: "[project]/components/ui/transition-switch.tsx",
                lineNumber: 30,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "text-center",
                children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                    className: "text-xs text-cyan-400 font-medium",
                    children: (0, __TURBOPACK__imported__module__$5b$project$5d2f$lib$2f$transitions$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["getTransitionName"])(currentTransition)
                }, void 0, false, {
                    fileName: "[project]/components/ui/transition-switch.tsx",
                    lineNumber: 48,
                    columnNumber: 9
                }, this)
            }, void 0, false, {
                fileName: "[project]/components/ui/transition-switch.tsx",
                lineNumber: 47,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/components/ui/transition-switch.tsx",
        lineNumber: 19,
        columnNumber: 5
    }, this);
}
}),
"[project]/components/testing/ThemeTestSwitcher.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "ThemeTestSwitcher",
    ()=>ThemeTestSwitcher
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/framer-motion/dist/es/render/components/motion/proxy.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/framer-motion/dist/es/components/AnimatePresence/index.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/BrandColorContext.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$palette$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Palette$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/palette.js [app-ssr] (ecmascript) <export default as Palette>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chevron$2d$up$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__ChevronUp$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/chevron-up.js [app-ssr] (ecmascript) <export default as ChevronUp>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chevron$2d$down$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__ChevronDown$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/chevron-down.js [app-ssr] (ecmascript) <export default as ChevronDown>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$copy$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Copy$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/copy.js [app-ssr] (ecmascript) <export default as Copy>");
"use client";
;
;
;
;
;
const INTENSITY_CONFIG = {
    subtle: {
        multiplier: 0.7,
        label: "Subtle"
    },
    medium: {
        multiplier: 1.0,
        label: "Medium"
    },
    strong: {
        multiplier: 1.3,
        label: "Strong"
    }
};
function ThemeTestSwitcher() {
    const { theme, setTheme, getThemeConfig, brandColor, setHue, setSaturation, setLightness } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useBrandColor"])();
    const [isExpanded, setIsExpanded] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(true);
    const [intensity, setIntensity] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])("medium");
    const [isMounted, setIsMounted] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    // Color adjustment state
    const [customHue, setCustomHue] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(brandColor.hue);
    const [customSat, setCustomSat] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(brandColor.saturation);
    const [customLight, setCustomLight] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(brandColor.lightness);
    const [showColorAdjust, setShowColorAdjust] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        setIsMounted(true);
    }, []);
    // Sync with brandColor changes
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        setCustomHue(brandColor.hue);
        setCustomSat(brandColor.saturation);
        setCustomLight(brandColor.lightness);
    }, [
        brandColor
    ]);
    const currentTheme = getThemeConfig();
    const themes = [
        'aether',
        'ember',
        'aurum',
        'verdant'
    ];
    const handleThemeSelect = (t)=>{
        setTheme(t);
        if (t === "ember") setIntensity("strong");
        if (t === "aurum") setIntensity("subtle");
        if (t === "aether") setIntensity("medium");
        if (t === "verdant") setIntensity("medium");
    };
    const applyCustomColors = ()=>{
        setHue(customHue);
        setSaturation(customSat);
        setLightness(customLight);
    };
    const copyColorSpecs = ()=>{
        const specs = `hue: ${Math.round(customHue)}, saturation: ${Math.round(customSat)}, lightness: ${Math.round(customLight)}`;
        // Try clipboard API first, fallback to console if blocked
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(specs).then(()=>alert(`Copied: ${specs}`)).catch(()=>{
                    console.log('[Theme Color Specs]', specs);
                    alert(`Color Specs (check console): ${specs}`);
                });
            } else {
                // Fallback for non-secure contexts
                console.log('[Theme Color Specs]', specs);
                alert(`Color Specs: ${specs}\n\n(Check browser console for copy button)`);
            }
        } catch  {
            console.log('[Theme Color Specs]', specs);
            alert(`Color Specs: ${specs}`);
        }
    };
    if (!isMounted) return null;
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
        className: "fixed z-[9999] pointer-events-auto",
        style: {
            top: 24,
            left: 24
        },
        initial: {
            opacity: 0,
            y: 20
        },
        animate: {
            opacity: 1,
            y: 0
        },
        onClick: (e)=>{
            e.stopPropagation();
            e.preventDefault();
        },
        onMouseDown: (e)=>{
            e.stopPropagation();
            e.preventDefault();
        },
        onPointerDown: (e)=>{
            e.stopPropagation();
            e.preventDefault();
        },
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
            mode: "wait",
            children: !isExpanded ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].button, {
                onClick: (e)=>{
                    e.stopPropagation();
                    setIsExpanded(true);
                },
                className: "flex items-center gap-2 px-4 py-2 rounded-full backdrop-blur-xl border border-white/10 shadow-2xl",
                style: {
                    background: `linear-gradient(135deg, ${currentTheme.gradient.from}30, ${currentTheme.gradient.to}20)`,
                    borderColor: `${currentTheme.shimmer.primary}40`
                },
                whileHover: {
                    scale: 1.05
                },
                whileTap: {
                    scale: 0.95
                },
                exit: {
                    opacity: 0,
                    scale: 0.9
                },
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "w-3 h-3 rounded-full",
                        style: {
                            background: currentTheme.shimmer.primary,
                            boxShadow: `0 0 8px ${currentTheme.shimmer.primary}`
                        }
                    }, void 0, false, {
                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                        lineNumber: 123,
                        columnNumber: 13
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        className: "text-xs font-medium text-white/90 uppercase tracking-wider",
                        children: currentTheme.name
                    }, void 0, false, {
                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                        lineNumber: 130,
                        columnNumber: 13
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chevron$2d$up$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__ChevronUp$3e$__["ChevronUp"], {
                        className: "w-3 h-3 text-white/60"
                    }, void 0, false, {
                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                        lineNumber: 133,
                        columnNumber: 13
                    }, this)
                ]
            }, "collapsed", true, {
                fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                lineNumber: 108,
                columnNumber: 11
            }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                className: "w-72 rounded-2xl backdrop-blur-xl border border-white/10 shadow-2xl overflow-hidden",
                style: {
                    background: `linear-gradient(180deg, rgba(10,10,15,0.95) 0%, rgba(5,5,10,0.98) 100%)`,
                    borderColor: `${currentTheme.shimmer.primary}30`
                },
                initial: {
                    opacity: 0,
                    scale: 0.95
                },
                animate: {
                    opacity: 1,
                    scale: 1
                },
                exit: {
                    opacity: 0,
                    scale: 0.95
                },
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "flex items-center justify-between px-4 py-3 border-b",
                        style: {
                            borderColor: `${currentTheme.shimmer.primary}20`
                        },
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "flex items-center gap-2",
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$palette$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Palette$3e$__["Palette"], {
                                        className: "w-4 h-4",
                                        style: {
                                            color: currentTheme.shimmer.primary
                                        }
                                    }, void 0, false, {
                                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                        lineNumber: 153,
                                        columnNumber: 17
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                className: "text-sm font-semibold text-white/90",
                                                children: currentTheme.name
                                            }, void 0, false, {
                                                fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                                lineNumber: 155,
                                                columnNumber: 19
                                            }, this),
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                                                className: "text-[10px] text-white/50",
                                                children: currentTheme.description
                                            }, void 0, false, {
                                                fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                                lineNumber: 156,
                                                columnNumber: 19
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                        lineNumber: 154,
                                        columnNumber: 17
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                lineNumber: 152,
                                columnNumber: 15
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                onClick: (e)=>{
                                    e.stopPropagation();
                                    setIsExpanded(false);
                                },
                                className: "p-1.5 rounded-lg hover:bg-white/10 transition-colors",
                                children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chevron$2d$down$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__ChevronDown$3e$__["ChevronDown"], {
                                    className: "w-4 h-4 text-white/60"
                                }, void 0, false, {
                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                    lineNumber: 166,
                                    columnNumber: 17
                                }, this)
                            }, void 0, false, {
                                fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                lineNumber: 159,
                                columnNumber: 15
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                        lineNumber: 148,
                        columnNumber: 13
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "p-3 grid grid-cols-2 gap-2",
                        children: themes.map((t)=>{
                            const themeConfig = __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["PRISM_THEMES"][t];
                            const isSelected = theme === t;
                            return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].button, {
                                onClick: (e)=>{
                                    e.stopPropagation();
                                    handleThemeSelect(t);
                                },
                                className: `relative p-3 rounded-xl border transition-all text-left ${isSelected ? 'border-white/30 bg-white/10' : 'border-white/5 hover:border-white/20 hover:bg-white/5'}`,
                                whileHover: {
                                    scale: 1.02
                                },
                                whileTap: {
                                    scale: 0.98
                                },
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        className: "w-full h-14 rounded-lg mb-2 relative overflow-hidden",
                                        style: {
                                            background: `linear-gradient(${themeConfig.gradient.angle}deg, ${themeConfig.gradient.from}, ${themeConfig.gradient.to})`,
                                            opacity: 0.4
                                        },
                                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                                            className: "absolute inset-0 rounded-lg",
                                            style: {
                                                background: `conic-gradient(from 0deg, transparent 0deg, ${themeConfig.shimmer.secondary}20 60deg, ${themeConfig.shimmer.primary}60 180deg, ${themeConfig.shimmer.secondary}20 300deg, transparent 360deg)`
                                            },
                                            animate: {
                                                rotate: 360
                                            },
                                            transition: {
                                                duration: 8,
                                                repeat: Infinity,
                                                ease: "linear"
                                            }
                                        }, void 0, false, {
                                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                            lineNumber: 198,
                                            columnNumber: 23
                                        }, this)
                                    }, void 0, false, {
                                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                        lineNumber: 190,
                                        columnNumber: 21
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        className: "text-xs font-medium text-white/90 mb-0.5",
                                        children: themeConfig.name
                                    }, void 0, false, {
                                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                        lineNumber: 209,
                                        columnNumber: 21
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        className: "text-[9px] text-white/50 leading-tight",
                                        children: themeConfig.mood
                                    }, void 0, false, {
                                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                        lineNumber: 214,
                                        columnNumber: 21
                                    }, this),
                                    isSelected && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                                        layoutId: "selectedTheme",
                                        className: "absolute top-2 right-2 w-2 h-2 rounded-full",
                                        style: {
                                            background: themeConfig.shimmer.primary
                                        }
                                    }, void 0, false, {
                                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                        lineNumber: 220,
                                        columnNumber: 23
                                    }, this)
                                ]
                            }, t, true, {
                                fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                lineNumber: 177,
                                columnNumber: 19
                            }, this);
                        })
                    }, void 0, false, {
                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                        lineNumber: 171,
                        columnNumber: 13
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "px-3 pb-2",
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "flex gap-1 bg-white/5 rounded-lg p-1",
                            children: [
                                'subtle',
                                'medium',
                                'strong'
                            ].map((i)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                    onClick: (e)=>{
                                        e.stopPropagation();
                                        setIntensity(i);
                                    },
                                    className: `flex-1 py-1.5 text-[10px] rounded-md transition-all ${intensity === i ? 'bg-white/20 text-white font-medium' : 'text-white/50 hover:text-white/70'}`,
                                    children: INTENSITY_CONFIG[i].label
                                }, i, false, {
                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                    lineNumber: 235,
                                    columnNumber: 19
                                }, this))
                        }, void 0, false, {
                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                            lineNumber: 233,
                            columnNumber: 15
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                        lineNumber: 232,
                        columnNumber: 13
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "px-3 pb-2",
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                            onClick: (e)=>{
                                e.stopPropagation();
                                setShowColorAdjust(!showColorAdjust);
                            },
                            className: "w-full py-2 text-[10px] text-white/70 hover:text-white bg-white/5 rounded-lg transition-colors",
                            children: showColorAdjust ? 'Hide Color Adjust' : 'Adjust Colors'
                        }, void 0, false, {
                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                            lineNumber: 253,
                            columnNumber: 15
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                        lineNumber: 252,
                        columnNumber: 13
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                        children: showColorAdjust && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                            initial: {
                                height: 0,
                                opacity: 0
                            },
                            animate: {
                                height: 'auto',
                                opacity: 1
                            },
                            exit: {
                                height: 0,
                                opacity: 0
                            },
                            className: "px-3 pb-3 space-y-2 overflow-hidden",
                            onClick: (e)=>e.stopPropagation(),
                            children: [
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                    className: "space-y-1",
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            className: "flex justify-between text-[10px] text-white/60",
                                            children: [
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                    children: "Hue"
                                                }, void 0, false, {
                                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                                    lineNumber: 274,
                                                    columnNumber: 23
                                                }, this),
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                    children: [
                                                        Math.round(customHue),
                                                        "°"
                                                    ]
                                                }, void 0, true, {
                                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                                    lineNumber: 275,
                                                    columnNumber: 23
                                                }, this)
                                            ]
                                        }, void 0, true, {
                                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                            lineNumber: 273,
                                            columnNumber: 21
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                            type: "range",
                                            min: "0",
                                            max: "360",
                                            value: customHue,
                                            onChange: (e)=>{
                                                e.stopPropagation();
                                                const val = Number(e.target.value);
                                                setCustomHue(val);
                                                setHue(val);
                                                console.log('[ThemeAdjust] Hue:', val);
                                            },
                                            onMouseUp: (e)=>{
                                                e.stopPropagation();
                                                applyCustomColors();
                                            },
                                            onPointerUp: (e)=>{
                                                e.stopPropagation();
                                                applyCustomColors();
                                            },
                                            onMouseDown: (e)=>e.stopPropagation(),
                                            onPointerDown: (e)=>e.stopPropagation(),
                                            onClick: (e)=>e.stopPropagation(),
                                            className: "w-full h-1 bg-white/20 rounded-full appearance-none cursor-pointer",
                                            style: {
                                                background: `linear-gradient(to right, hsl(0,100%,50%), hsl(60,100%,50%), hsl(120,100%,50%), hsl(180,100%,50%), hsl(240,100%,50%), hsl(300,100%,50%), hsl(360,100%,50%))`
                                            }
                                        }, void 0, false, {
                                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                            lineNumber: 277,
                                            columnNumber: 21
                                        }, this)
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                    lineNumber: 272,
                                    columnNumber: 19
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                    className: "space-y-1",
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            className: "flex justify-between text-[10px] text-white/60",
                                            children: [
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                    children: "Saturation"
                                                }, void 0, false, {
                                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                                    lineNumber: 302,
                                                    columnNumber: 23
                                                }, this),
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                    children: [
                                                        Math.round(customSat),
                                                        "%"
                                                    ]
                                                }, void 0, true, {
                                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                                    lineNumber: 303,
                                                    columnNumber: 23
                                                }, this)
                                            ]
                                        }, void 0, true, {
                                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                            lineNumber: 301,
                                            columnNumber: 21
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                            type: "range",
                                            min: "0",
                                            max: "100",
                                            value: customSat,
                                            onChange: (e)=>{
                                                e.stopPropagation();
                                                const val = Number(e.target.value);
                                                setCustomSat(val);
                                                setSaturation(val);
                                                console.log('[ThemeAdjust] Saturation:', val);
                                            },
                                            onMouseUp: (e)=>{
                                                e.stopPropagation();
                                                applyCustomColors();
                                            },
                                            onPointerUp: (e)=>{
                                                e.stopPropagation();
                                                applyCustomColors();
                                            },
                                            onMouseDown: (e)=>e.stopPropagation(),
                                            onPointerDown: (e)=>e.stopPropagation(),
                                            onClick: (e)=>e.stopPropagation(),
                                            className: "w-full h-1 bg-white/20 rounded-full appearance-none cursor-pointer"
                                        }, void 0, false, {
                                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                            lineNumber: 305,
                                            columnNumber: 21
                                        }, this)
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                    lineNumber: 300,
                                    columnNumber: 19
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                    className: "space-y-1",
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            className: "flex justify-between text-[10px] text-white/60",
                                            children: [
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                    children: "Lightness"
                                                }, void 0, false, {
                                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                                    lineNumber: 329,
                                                    columnNumber: 23
                                                }, this),
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                    children: [
                                                        Math.round(customLight),
                                                        "%"
                                                    ]
                                                }, void 0, true, {
                                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                                    lineNumber: 330,
                                                    columnNumber: 23
                                                }, this)
                                            ]
                                        }, void 0, true, {
                                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                            lineNumber: 328,
                                            columnNumber: 21
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                            type: "range",
                                            min: "0",
                                            max: "100",
                                            value: customLight,
                                            onChange: (e)=>{
                                                e.stopPropagation();
                                                const val = Number(e.target.value);
                                                setCustomLight(val);
                                                setLightness(val);
                                                console.log('[ThemeAdjust] Lightness:', val);
                                            },
                                            onMouseUp: (e)=>{
                                                e.stopPropagation();
                                                applyCustomColors();
                                            },
                                            onPointerUp: (e)=>{
                                                e.stopPropagation();
                                                applyCustomColors();
                                            },
                                            onMouseDown: (e)=>e.stopPropagation(),
                                            onPointerDown: (e)=>e.stopPropagation(),
                                            onClick: (e)=>e.stopPropagation(),
                                            className: "w-full h-1 bg-white/20 rounded-full appearance-none cursor-pointer"
                                        }, void 0, false, {
                                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                            lineNumber: 332,
                                            columnNumber: 21
                                        }, this)
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                    lineNumber: 327,
                                    columnNumber: 19
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                    onClick: (e)=>{
                                        e.stopPropagation();
                                        copyColorSpecs();
                                    },
                                    className: "w-full mt-2 py-2 flex items-center justify-center gap-2 text-[10px] bg-white/10 hover:bg-white/20 rounded-lg transition-colors text-white/80",
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$copy$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Copy$3e$__["Copy"], {
                                            className: "w-3 h-3"
                                        }, void 0, false, {
                                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                            lineNumber: 358,
                                            columnNumber: 21
                                        }, this),
                                        "Copy Color Specs"
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                    lineNumber: 354,
                                    columnNumber: 19
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                    className: "text-[9px] text-white/40 font-mono text-center pt-1",
                                    children: [
                                        "hue: ",
                                        Math.round(customHue),
                                        ", sat: ",
                                        Math.round(customSat),
                                        ", light: ",
                                        Math.round(customLight)
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                                    lineNumber: 363,
                                    columnNumber: 19
                                }, this)
                            ]
                        }, void 0, true, {
                            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                            lineNumber: 264,
                            columnNumber: 17
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                        lineNumber: 262,
                        columnNumber: 13
                    }, this)
                ]
            }, "expanded", true, {
                fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
                lineNumber: 136,
                columnNumber: 11
            }, this)
        }, void 0, false, {
            fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
            lineNumber: 106,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/components/testing/ThemeTestSwitcher.tsx",
        lineNumber: 88,
        columnNumber: 5
    }, this);
}
}),
];

//# sourceMappingURL=%5Broot-of-the-server%5D__48337218._.js.map