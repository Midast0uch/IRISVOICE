module.exports = [
"[project]/hooks/useIRISWebSocket.ts [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "useIRISWebSocket",
    ()=>useIRISWebSocket
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
;
// Default theme matching backend defaults
const DEFAULT_THEME = {
    primary: "#00ff88",
    glow: "#00ff88",
    font: "#ffffff"
};
function useIRISWebSocket(url = "ws://localhost:8000/ws/iris", autoConnect = true) {
    // Connection state
    const [connectionState, setConnectionState] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])("disconnected");
    const [lastError, setLastError] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    // IRIS state from backend
    const [theme, setTheme] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(DEFAULT_THEME);
    const [fieldValues, setFieldValues] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])({});
    const [confirmedNodes, setConfirmedNodes] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])([]);
    const [currentCategory, setCurrentCategory] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    const [currentSubnode, setCurrentSubnode] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    // WebSocket ref
    const wsRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(null);
    const reconnectTimeoutRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(null);
    const reconnectAttemptsRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(0);
    const isConnected = connectionState === "connected";
    // Cleanup function
    const cleanup = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = null;
        }
        if (wsRef.current) {
            wsRef.current.close();
            wsRef.current = null;
        }
    }, []);
    // Connect to WebSocket
    const connect = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            return; // Already connected
        }
        setConnectionState("connecting");
        setLastError(null);
        try {
            const ws = new WebSocket(url);
            ws.onopen = ()=>{
                console.log("[IRIS WebSocket] Connected");
                setConnectionState("connected");
                reconnectAttemptsRef.current = 0;
                // Request initial state
                ws.send(JSON.stringify({
                    type: "request_state",
                    payload: {}
                }));
            };
            ws.onmessage = (event)=>{
                try {
                    const message = JSON.parse(event.data);
                    handleMessage(message);
                } catch (err) {
                    console.error("[IRIS WebSocket] Failed to parse message:", err);
                }
            };
            ws.onerror = (error)=>{
                // WebSocket errors don't contain detailed info - just log connection failed
                console.warn("[IRIS WebSocket] Connection failed - backend may be offline");
                setConnectionState("error");
                setLastError("Backend offline - running in standalone mode");
            };
            ws.onclose = (event)=>{
                console.log(`[IRIS WebSocket] Closed (code: ${event.code})`);
                setConnectionState("disconnected");
                wsRef.current = null;
                // Auto-reconnect with exponential backoff - longer initial delay for browser mode
                if (autoConnect && reconnectAttemptsRef.current < 3) {
                    const delay = Math.min(5000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
                    reconnectAttemptsRef.current++;
                    console.log(`[IRIS WebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current}/3)`);
                    reconnectTimeoutRef.current = setTimeout(()=>{
                        connect();
                    }, delay);
                }
            };
            wsRef.current = ws;
        } catch (err) {
            console.error("[IRIS WebSocket] Failed to create connection:", err);
            setConnectionState("error");
            setLastError("Failed to create connection");
        }
    }, [
        url,
        autoConnect
    ]);
    // Handle incoming messages
    const handleMessage = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((message)=>{
        const { type, ...payload } = message;
        switch(type){
            case "initial_state":
            case "state_sync":
                {
                    const state = payload.state;
                    if (state.active_theme) setTheme(state.active_theme);
                    if (state.field_values) setFieldValues(state.field_values);
                    if (state.confirmed_nodes) setConfirmedNodes(state.confirmed_nodes);
                    if (state.current_category !== undefined) setCurrentCategory(state.current_category);
                    if (state.current_subnode !== undefined) setCurrentSubnode(state.current_subnode);
                    break;
                }
            case "category_changed":
                {
                    if (payload.category) setCurrentCategory(payload.category);
                    setCurrentSubnode(null);
                    break;
                }
            case "subnode_changed":
                {
                    if (payload.subnode_id !== undefined) setCurrentSubnode(payload.subnode_id);
                    break;
                }
            case "field_updated":
                {
                    // Optimistic update confirmed by server
                    const { subnode_id, field_id, value } = payload;
                    if (subnode_id && field_id !== undefined) {
                        setFieldValues((prev)=>({
                                ...prev,
                                [subnode_id]: {
                                    ...prev[subnode_id],
                                    [field_id]: value
                                }
                            }));
                    }
                    break;
                }
            case "validation_error":
                {
                    console.error("[IRIS WebSocket] Validation error:", payload.error, payload.field_id);
                    setLastError(payload.error);
                    break;
                }
            case "mini_node_confirmed":
                {
                    break;
                }
            case "theme_updated":
                {
                    if (payload.glow || payload.font || payload.state_colors_enabled !== undefined) {
                        setTheme((prev)=>({
                                ...prev,
                                ...payload.glow && {
                                    glow: payload.glow,
                                    primary: payload.glow
                                },
                                ...payload.font && {
                                    font: payload.font
                                },
                                ...payload.state_colors_enabled !== undefined && {
                                    state_colors_enabled: payload.state_colors_enabled
                                },
                                ...payload.idle_color && {
                                    idle_color: payload.idle_color
                                },
                                ...payload.listening_color && {
                                    listening_color: payload.listening_color
                                },
                                ...payload.processing_color && {
                                    processing_color: payload.processing_color
                                },
                                ...payload.error_color && {
                                    error_color: payload.error_color
                                }
                            }));
                    }
                    break;
                }
            case "pong":
                {
                    break;
                }
            default:
                console.log("[IRIS WebSocket] Unknown message type:", type, payload);
        }
    }, []);
    // Send message helper
    const sendMessage = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((type, payload = {})=>{
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({
                type,
                payload
            }));
            return true;
        }
        console.warn("[IRIS WebSocket] Not connected, message dropped:", type);
        return false;
    }, []);
    // Action methods
    const selectCategory = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((category)=>{
        sendMessage("select_category", {
            category
        });
    }, [
        sendMessage
    ]);
    const selectSubnode = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((subnodeId)=>{
        if (subnodeId) {
            sendMessage("select_subnode", {
                subnode_id: subnodeId
            });
        } else {
            // Deselect - just update local state for now
            setCurrentSubnode(null);
        }
    }, [
        sendMessage
    ]);
    const updateField = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((subnodeId, fieldId, value)=>{
        // Optimistic local update
        setFieldValues((prev)=>({
                ...prev,
                [subnodeId]: {
                    ...prev[subnodeId],
                    [fieldId]: value
                }
            }));
        // Send to server
        sendMessage("field_update", {
            subnode_id: subnodeId,
            field_id: fieldId,
            value
        });
    }, [
        sendMessage
    ]);
    const confirmMiniNode = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((subnodeId, values)=>{
        sendMessage("confirm_mini_node", {
            subnode_id: subnodeId,
            values
        });
    }, [
        sendMessage
    ]);
    const updateTheme = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((glowColor, fontColor, stateColors)=>{
        // Optimistic local update
        setTheme((prev)=>({
                ...prev,
                ...glowColor && {
                    glow: glowColor,
                    primary: glowColor
                },
                ...fontColor && {
                    font: fontColor
                },
                ...stateColors?.enabled !== undefined && {
                    state_colors_enabled: stateColors.enabled
                },
                ...stateColors?.idle && {
                    idle_color: stateColors.idle
                },
                ...stateColors?.listening && {
                    listening_color: stateColors.listening
                },
                ...stateColors?.processing && {
                    processing_color: stateColors.processing
                },
                ...stateColors?.error && {
                    error_color: stateColors.error
                }
            }));
        // Send to server
        sendMessage("update_theme", {
            glow_color: glowColor,
            font_color: fontColor,
            state_colors: stateColors
        });
    }, [
        sendMessage
    ]);
    const requestState = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        sendMessage("request_state", {});
    }, [
        sendMessage
    ]);
    // Initialize connection
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        if (autoConnect) {
            connect();
        }
        return cleanup;
    }, [
        autoConnect,
        connect,
        cleanup
    ]);
    // Keep-alive ping
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        if (!isConnected) return;
        const interval = setInterval(()=>{
            sendMessage("ping", {});
        }, 30000) // Ping every 30 seconds
        ;
        return ()=>clearInterval(interval);
    }, [
        isConnected,
        sendMessage
    ]);
    return {
        isConnected,
        connectionState,
        theme,
        fieldValues,
        confirmedNodes,
        currentCategory,
        currentSubnode,
        selectCategory,
        selectSubnode,
        updateField,
        confirmMiniNode,
        updateTheme,
        requestState,
        lastError
    };
}
}),
"[project]/components/fields/FieldWrapper.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "FieldWrapper",
    ()=>FieldWrapper
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
"use client";
;
function FieldWrapper({ label, description, error, children, compact = false }) {
    if (compact) {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            className: "flex items-center justify-between gap-3",
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    className: "flex-1 min-w-0",
                    children: [
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                            className: "text-[11px] font-medium uppercase tracking-wider text-white/60",
                            children: label
                        }, void 0, false, {
                            fileName: "[project]/components/fields/FieldWrapper.tsx",
                            lineNumber: 24,
                            columnNumber: 11
                        }, this),
                        description && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                            className: "text-[10px] text-white/40 truncate",
                            children: description
                        }, void 0, false, {
                            fileName: "[project]/components/fields/FieldWrapper.tsx",
                            lineNumber: 28,
                            columnNumber: 13
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/components/fields/FieldWrapper.tsx",
                    lineNumber: 23,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    className: "flex-shrink-0",
                    children: children
                }, void 0, false, {
                    fileName: "[project]/components/fields/FieldWrapper.tsx",
                    lineNumber: 31,
                    columnNumber: 9
                }, this),
                error && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                    className: "text-[10px] text-red-400 absolute -bottom-4 right-0",
                    children: error
                }, void 0, false, {
                    fileName: "[project]/components/fields/FieldWrapper.tsx",
                    lineNumber: 33,
                    columnNumber: 11
                }, this)
            ]
        }, void 0, true, {
            fileName: "[project]/components/fields/FieldWrapper.tsx",
            lineNumber: 22,
            columnNumber: 7
        }, this);
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "space-y-2 relative",
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                className: "text-[11px] font-medium uppercase tracking-wider text-white/60",
                children: label
            }, void 0, false, {
                fileName: "[project]/components/fields/FieldWrapper.tsx",
                lineNumber: 43,
                columnNumber: 7
            }, this),
            description && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                className: "text-[10px] text-white/40 -mt-1",
                children: description
            }, void 0, false, {
                fileName: "[project]/components/fields/FieldWrapper.tsx",
                lineNumber: 47,
                columnNumber: 9
            }, this),
            children,
            error && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                className: "text-[10px] text-red-400",
                children: error
            }, void 0, false, {
                fileName: "[project]/components/fields/FieldWrapper.tsx",
                lineNumber: 51,
                columnNumber: 9
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/components/fields/FieldWrapper.tsx",
        lineNumber: 42,
        columnNumber: 5
    }, this);
}
}),
"[project]/components/fields/TextField.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "TextField",
    ()=>TextField
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$FieldWrapper$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/fields/FieldWrapper.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/BrandColorContext.tsx [app-ssr] (ecmascript)");
"use client";
;
;
;
function TextField({ label, value, placeholder, onChange, description, error }) {
    const { getHSLString } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useBrandColor"])();
    const glowColor = getHSLString();
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$FieldWrapper$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["FieldWrapper"], {
        label: label,
        description: description,
        error: error,
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
            type: "text",
            value: value || "",
            placeholder: placeholder,
            onChange: (e)=>onChange(e.target.value),
            className: "w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white/90 placeholder:text-white/30 focus:outline-none transition-colors",
            style: {
                borderColor: value ? `${glowColor}50` : undefined
            }
        }, void 0, false, {
            fileName: "[project]/components/fields/TextField.tsx",
            lineNumber: 28,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/components/fields/TextField.tsx",
        lineNumber: 27,
        columnNumber: 5
    }, this);
}
}),
"[project]/components/fields/SliderField.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "SliderField",
    ()=>SliderField
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$FieldWrapper$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/fields/FieldWrapper.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/BrandColorContext.tsx [app-ssr] (ecmascript)");
"use client";
;
;
;
;
function SliderField({ label, value, min, max, step = 1, unit = "", onChange, description, showValue = "beside" }) {
    const [isDragging, setIsDragging] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    const [showTooltip, setShowTooltip] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    const trackRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(null);
    const { getHSLString } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useBrandColor"])();
    const glowColor = getHSLString();
    const currentValue = value ?? min;
    const percentage = (currentValue - min) / (max - min) * 100;
    const handleInteraction = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((clientX, isFineControl)=>{
        if (!trackRef.current) return;
        const rect = trackRef.current.getBoundingClientRect();
        const rawPercentage = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        const rawValue = min + rawPercentage * (max - min);
        // Apply step and fine control
        const actualStep = isFineControl ? step / 10 : step;
        const steppedValue = Math.round(rawValue / actualStep) * actualStep;
        const clampedValue = Math.max(min, Math.min(max, steppedValue));
        onChange(Number(clampedValue.toFixed(2)));
    }, [
        min,
        max,
        step,
        onChange
    ]);
    const handleMouseDown = (e)=>{
        e.stopPropagation();
        setIsDragging(true);
        handleInteraction(e.clientX, e.shiftKey);
    };
    const handleMouseMove = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((e)=>{
        if (isDragging) {
            handleInteraction(e.clientX, e.shiftKey);
        }
    }, [
        isDragging,
        handleInteraction
    ]);
    const handleMouseUp = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        setIsDragging(false);
    }, []);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        if (isDragging) {
            window.addEventListener("mousemove", handleMouseMove);
            window.addEventListener("mouseup", handleMouseUp);
            return ()=>{
                window.removeEventListener("mousemove", handleMouseMove);
                window.removeEventListener("mouseup", handleMouseUp);
            };
        }
    }, [
        isDragging,
        handleMouseMove,
        handleMouseUp
    ]);
    const formattedValue = `${Math.round(currentValue)}${unit}`;
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$FieldWrapper$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["FieldWrapper"], {
        label: label,
        description: description,
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            className: "flex items-center gap-3",
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    ref: trackRef,
                    className: "relative flex-1 h-1 bg-white/10 rounded-full cursor-pointer",
                    onMouseDown: handleMouseDown,
                    onMouseEnter: ()=>setShowTooltip(true),
                    onMouseLeave: ()=>!isDragging && setShowTooltip(false),
                    children: [
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "absolute left-0 top-0 h-full rounded-full transition-all duration-75",
                            style: {
                                width: `${percentage}%`,
                                background: glowColor,
                                boxShadow: `0 0 8px ${glowColor}`
                            }
                        }, void 0, false, {
                            fileName: "[project]/components/fields/SliderField.tsx",
                            lineNumber: 100,
                            columnNumber: 11
                        }, this),
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "absolute top-1/2 w-4 h-4 bg-white rounded-full shadow-lg transform -translate-y-1/2 -translate-x-1/2 transition-transform hover:scale-110",
                            style: {
                                left: `${percentage}%`
                            }
                        }, void 0, false, {
                            fileName: "[project]/components/fields/SliderField.tsx",
                            lineNumber: 110,
                            columnNumber: 11
                        }, this),
                        showTooltip && showValue === "tooltip" && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "absolute -top-8 px-2 py-1 bg-white/10 rounded text-xs text-white transform -translate-x-1/2",
                            style: {
                                left: `${percentage}%`
                            },
                            children: formattedValue
                        }, void 0, false, {
                            fileName: "[project]/components/fields/SliderField.tsx",
                            lineNumber: 117,
                            columnNumber: 13
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/components/fields/SliderField.tsx",
                    lineNumber: 92,
                    columnNumber: 9
                }, this),
                showValue === "beside" && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                    className: "text-xs text-white/60 w-12 text-right tabular-nums",
                    children: formattedValue
                }, void 0, false, {
                    fileName: "[project]/components/fields/SliderField.tsx",
                    lineNumber: 127,
                    columnNumber: 11
                }, this)
            ]
        }, void 0, true, {
            fileName: "[project]/components/fields/SliderField.tsx",
            lineNumber: 91,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/components/fields/SliderField.tsx",
        lineNumber: 90,
        columnNumber: 5
    }, this);
}
}),
"[project]/components/fields/DropdownField.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "DropdownField",
    ()=>DropdownField
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chevron$2d$down$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__ChevronDown$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/chevron-down.js [app-ssr] (ecmascript) <export default as ChevronDown>");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$FieldWrapper$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/fields/FieldWrapper.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/BrandColorContext.tsx [app-ssr] (ecmascript)");
"use client";
;
;
;
;
;
function DropdownField({ label, value, options, loadOptions, onChange, placeholder = "Select...", description, searchable = false }) {
    const [isOpen, setIsOpen] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    const [loadedOptions, setLoadedOptions] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    const [isLoading, setIsLoading] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    const [searchQuery, setSearchQuery] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])("");
    const containerRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(null);
    const { getHSLString } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useBrandColor"])();
    const glowColor = getHSLString();
    // Load async options on first open
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        if (isOpen && loadOptions && !loadedOptions && !isLoading) {
            setIsLoading(true);
            loadOptions().then((opts)=>{
                setLoadedOptions(opts);
                setIsLoading(false);
            }).catch(()=>setIsLoading(false));
        }
    }, [
        isOpen,
        loadOptions,
        loadedOptions,
        isLoading
    ]);
    // Close on outside click
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        const handleClickOutside = (e)=>{
            if (containerRef.current && !containerRef.current.contains(e.target)) {
                setIsOpen(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        return ()=>document.removeEventListener("mousedown", handleClickOutside);
    }, []);
    const allOptions = loadedOptions || (options ? options.map((opt)=>typeof opt === "string" ? {
            label: opt,
            value: opt
        } : opt) : []);
    const filteredOptions = searchable && searchQuery ? allOptions.filter((opt)=>opt.label.toLowerCase().includes(searchQuery.toLowerCase())) : allOptions;
    const selectedOption = allOptions.find((opt)=>opt.value === value);
    const displayValue = selectedOption?.label || value || placeholder;
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$FieldWrapper$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["FieldWrapper"], {
        label: label,
        description: description,
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            ref: containerRef,
            className: "relative",
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                    type: "button",
                    onClick: (e)=>{
                        e.stopPropagation();
                        setIsOpen(!isOpen);
                    },
                    className: "w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white/90 hover:border-white/20 focus:outline-none focus:border-white/30 transition-colors",
                    children: [
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                            className: "truncate",
                            children: displayValue
                        }, void 0, false, {
                            fileName: "[project]/components/fields/DropdownField.tsx",
                            lineNumber: 95,
                            columnNumber: 11
                        }, this),
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chevron$2d$down$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__ChevronDown$3e$__["ChevronDown"], {
                            className: `w-4 h-4 text-white/40 transition-transform ${isOpen ? "rotate-180" : ""}`
                        }, void 0, false, {
                            fileName: "[project]/components/fields/DropdownField.tsx",
                            lineNumber: 96,
                            columnNumber: 11
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/components/fields/DropdownField.tsx",
                    lineNumber: 87,
                    columnNumber: 9
                }, this),
                isOpen && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    className: "absolute z-50 mt-1 w-full max-h-48 overflow-auto rounded-lg bg-[#1c1f24] border border-white/10 shadow-xl",
                    children: [
                        searchable && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "sticky top-0 p-2 bg-[#1c1f24] border-b border-white/10",
                            children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                                type: "text",
                                value: searchQuery,
                                onChange: (e)=>setSearchQuery(e.target.value),
                                placeholder: "Search...",
                                className: "w-full px-2 py-1 text-xs bg-white/5 rounded border border-white/10 text-white/90 placeholder:text-white/30 focus:outline-none focus:border-white/30",
                                onClick: (e)=>e.stopPropagation()
                            }, void 0, false, {
                                fileName: "[project]/components/fields/DropdownField.tsx",
                                lineNumber: 107,
                                columnNumber: 17
                            }, this)
                        }, void 0, false, {
                            fileName: "[project]/components/fields/DropdownField.tsx",
                            lineNumber: 106,
                            columnNumber: 15
                        }, this),
                        isLoading ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "px-3 py-2 text-sm text-white/40",
                            children: "Loading..."
                        }, void 0, false, {
                            fileName: "[project]/components/fields/DropdownField.tsx",
                            lineNumber: 119,
                            columnNumber: 15
                        }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "py-1",
                            children: filteredOptions.map((option)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                                    type: "button",
                                    onClick: (e)=>{
                                        e.stopPropagation();
                                        onChange(option.value);
                                        setIsOpen(false);
                                    },
                                    className: `w-full px-3 py-2 text-left text-sm transition-colors ${option.value === value ? "text-white" : "text-white/70 hover:bg-white/5"}`,
                                    style: {
                                        backgroundColor: option.value === value ? `${glowColor}30` : 'transparent'
                                    },
                                    children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                        className: "flex items-center justify-between",
                                        children: [
                                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                children: option.label
                                            }, void 0, false, {
                                                fileName: "[project]/components/fields/DropdownField.tsx",
                                                lineNumber: 139,
                                                columnNumber: 23
                                            }, this),
                                            option.downloaded !== undefined && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                className: `text-xs ${option.downloaded ? "text-green-400" : "text-amber-400"}`,
                                                children: option.downloaded ? "Downloaded" : "Download"
                                            }, void 0, false, {
                                                fileName: "[project]/components/fields/DropdownField.tsx",
                                                lineNumber: 141,
                                                columnNumber: 25
                                            }, this)
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/components/fields/DropdownField.tsx",
                                        lineNumber: 138,
                                        columnNumber: 21
                                    }, this)
                                }, option.value, false, {
                                    fileName: "[project]/components/fields/DropdownField.tsx",
                                    lineNumber: 123,
                                    columnNumber: 19
                                }, this))
                        }, void 0, false, {
                            fileName: "[project]/components/fields/DropdownField.tsx",
                            lineNumber: 121,
                            columnNumber: 15
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/components/fields/DropdownField.tsx",
                    lineNumber: 103,
                    columnNumber: 11
                }, this)
            ]
        }, void 0, true, {
            fileName: "[project]/components/fields/DropdownField.tsx",
            lineNumber: 85,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/components/fields/DropdownField.tsx",
        lineNumber: 84,
        columnNumber: 5
    }, this);
}
}),
"[project]/components/fields/ToggleField.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "ToggleField",
    ()=>ToggleField
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$FieldWrapper$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/fields/FieldWrapper.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/BrandColorContext.tsx [app-ssr] (ecmascript)");
"use client";
;
;
;
function ToggleField({ label, value, onChange, description }) {
    const { getHSLString } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useBrandColor"])();
    const glowColor = getHSLString();
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$FieldWrapper$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["FieldWrapper"], {
        label: label,
        description: description,
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
            type: "button",
            role: "switch",
            "aria-checked": value,
            onClick: (e)=>{
                e.stopPropagation();
                onChange(!value);
            },
            className: "relative w-12 h-6 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-white/20",
            style: {
                backgroundColor: value ? glowColor : 'rgba(255, 255, 255, 0.1)'
            },
            children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                className: `absolute top-0.5 w-5 h-5 rounded-full bg-white shadow-md transition-all duration-200 ${value ? "left-6 translate-x-0" : "left-0.5"}`
            }, void 0, false, {
                fileName: "[project]/components/fields/ToggleField.tsx",
                lineNumber: 34,
                columnNumber: 9
            }, this)
        }, void 0, false, {
            fileName: "[project]/components/fields/ToggleField.tsx",
            lineNumber: 23,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/components/fields/ToggleField.tsx",
        lineNumber: 22,
        columnNumber: 5
    }, this);
}
}),
"[project]/components/fields/ColorField.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "ColorField",
    ()=>ColorField
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$FieldWrapper$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/fields/FieldWrapper.tsx [app-ssr] (ecmascript)");
"use client";
;
;
function ColorField({ label, value, onChange, description }) {
    const currentValue = value || "#00ff88";
    const isValidHex = (hex)=>/^#[0-9A-Fa-f]{6}$/.test(hex);
    const handleTextChange = (input)=>{
        let hex = input.trim();
        if (!hex.startsWith("#")) {
            hex = "#" + hex;
        }
        if (isValidHex(hex)) {
            onChange(hex.toLowerCase());
        }
    };
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$FieldWrapper$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["FieldWrapper"], {
        label: label,
        description: description,
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            className: "flex items-center gap-3",
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    className: "relative",
                    children: [
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                            type: "color",
                            value: currentValue,
                            onChange: (e)=>onChange(e.target.value),
                            onClick: (e)=>e.stopPropagation(),
                            className: "w-10 h-8 rounded bg-transparent border border-white/20 cursor-pointer",
                            style: {
                                padding: 0
                            }
                        }, void 0, false, {
                            fileName: "[project]/components/fields/ColorField.tsx",
                            lineNumber: 36,
                            columnNumber: 11
                        }, this),
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            className: "absolute inset-0 rounded pointer-events-none border border-white/10",
                            style: {
                                background: currentValue
                            }
                        }, void 0, false, {
                            fileName: "[project]/components/fields/ColorField.tsx",
                            lineNumber: 44,
                            columnNumber: 11
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/components/fields/ColorField.tsx",
                    lineNumber: 35,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                    type: "text",
                    value: currentValue,
                    onChange: (e)=>handleTextChange(e.target.value),
                    onClick: (e)=>e.stopPropagation(),
                    className: "flex-1 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white/90 font-mono uppercase focus:outline-none focus:border-white/30 transition-colors",
                    maxLength: 7
                }, void 0, false, {
                    fileName: "[project]/components/fields/ColorField.tsx",
                    lineNumber: 49,
                    columnNumber: 9
                }, this)
            ]
        }, void 0, true, {
            fileName: "[project]/components/fields/ColorField.tsx",
            lineNumber: 34,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/components/fields/ColorField.tsx",
        lineNumber: 33,
        columnNumber: 5
    }, this);
}
}),
"[project]/components/mini-node-card.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "MiniNodeCard",
    ()=>MiniNodeCard
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/framer-motion/dist/es/render/components/motion/proxy.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/framer-motion/dist/es/components/AnimatePresence/index.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$lucide$2d$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/lucide-react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$TextField$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/fields/TextField.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$SliderField$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/fields/SliderField.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$DropdownField$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/fields/DropdownField.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$ToggleField$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/fields/ToggleField.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$ColorField$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/fields/ColorField.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/BrandColorContext.tsx [app-ssr] (ecmascript)");
"use client";
;
;
;
;
;
;
;
;
;
;
// Dynamically get Lucide icon
function getIcon(iconName) {
    const icons = __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$lucide$2d$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__;
    return icons[iconName] || __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$lucide$2d$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__.Circle;
}
function renderField(field, value, onChange, glowColor, theme, isCleanTheme) {
    // Helper for themed backgrounds using hex opacity
    const themedBg = `${theme.shimmer.primary}25`;
    const themedBorder = `${theme.shimmer.primary}66`;
    const labelColor = '#ffffff';
    // Stop propagation wrapper for all field interactions
    const stopProp = (e)=>e.stopPropagation();
    switch(field.type){
        case 'text':
            return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "p-2 rounded-lg space-y-1",
                style: {
                    background: themedBg,
                    border: `1px solid ${themedBorder}`
                },
                onClick: stopProp,
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        className: "text-[10px] uppercase tracking-wider",
                        style: {
                            color: labelColor,
                            fontWeight: 500
                        },
                        children: field.label
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 53,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$TextField$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["TextField"], {
                        label: "",
                        value: value ?? field.defaultValue ?? "",
                        placeholder: field.placeholder,
                        onChange: onChange
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 56,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/mini-node-card.tsx",
                lineNumber: 48,
                columnNumber: 9
            }, this);
        case 'slider':
            return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "p-2 rounded-lg space-y-1",
                style: {
                    background: themedBg,
                    border: `1px solid ${themedBorder}`
                },
                onClick: stopProp,
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        className: "text-[10px] uppercase tracking-wider",
                        style: {
                            color: labelColor,
                            fontWeight: 500
                        },
                        children: field.label
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 71,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$SliderField$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["SliderField"], {
                        label: "",
                        value: value ?? field.defaultValue ?? field.min ?? 0,
                        min: field.min ?? 0,
                        max: field.max ?? 100,
                        unit: field.unit,
                        onChange: onChange
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 74,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/mini-node-card.tsx",
                lineNumber: 66,
                columnNumber: 9
            }, this);
        case 'dropdown':
            return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "p-2 rounded-lg space-y-1",
                style: {
                    background: themedBg,
                    border: `1px solid ${themedBorder}`
                },
                onClick: stopProp,
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        className: "text-[10px] uppercase tracking-wider",
                        style: {
                            color: labelColor,
                            fontWeight: 500
                        },
                        children: field.label
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 91,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$DropdownField$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["DropdownField"], {
                        label: "",
                        value: value ?? field.defaultValue ?? field.options?.[0] ?? "",
                        options: field.options || [],
                        onChange: onChange
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 94,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/mini-node-card.tsx",
                lineNumber: 86,
                columnNumber: 9
            }, this);
        case 'toggle':
            return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "p-2 rounded-lg flex items-center justify-between",
                style: {
                    background: themedBg,
                    border: `1px solid ${themedBorder}`
                },
                onClick: stopProp,
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        className: "text-[10px] uppercase tracking-wider",
                        style: {
                            color: labelColor,
                            fontWeight: 500
                        },
                        children: field.label
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 109,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$ToggleField$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["ToggleField"], {
                        label: "",
                        value: value ?? field.defaultValue ?? false,
                        onChange: onChange
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 112,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/mini-node-card.tsx",
                lineNumber: 104,
                columnNumber: 9
            }, this);
        case 'color':
            return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "p-2 rounded-lg space-y-1",
                style: {
                    background: themedBg,
                    border: `1px solid ${themedBorder}`
                },
                onClick: stopProp,
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("label", {
                        className: "text-[10px] uppercase tracking-wider",
                        style: {
                            color: labelColor,
                            fontWeight: 500
                        },
                        children: field.label
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 126,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$fields$2f$ColorField$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["ColorField"], {
                        label: "",
                        value: value ?? field.defaultValue ?? "#00D4FF",
                        onChange: onChange
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 129,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/mini-node-card.tsx",
                lineNumber: 121,
                columnNumber: 9
            }, this);
        default:
            return null;
    }
}
function MiniNodeCard({ miniNode, isActive, values, onChange, onSave, index }) {
    const [isConfirming, setIsConfirming] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    const IconComponent = getIcon(miniNode.icon);
    const { getThemeConfig } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useBrandColor"])();
    const theme = getThemeConfig();
    const glowColor = theme.glow.color;
    const isCleanTheme = theme.name === 'Verdant' || theme.name === 'Aurum';
    // Intensity multipliers (same as PrismNode)
    const intensityMultipliers = {
        glowOpacity: isCleanTheme ? 1.5 : 1.0,
        glassOpacity: isCleanTheme ? 1.2 : 1.0,
        shimmerOpacity: 1.0
    };
    // Calculate dynamic opacities
    const glassOpacity = Math.min(theme.glass.opacity * intensityMultipliers.glassOpacity, 0.35);
    const glowOpacity = Math.min(theme.glow.opacity * intensityMultipliers.glowOpacity, 0.5);
    const shimmerOpacity = Math.min(1 * intensityMultipliers.shimmerOpacity, 1);
    // 2x size of regular nodes (90px → 180px)
    const CARD_SIZE = 180;
    const handleSave = ()=>{
        setIsConfirming(true);
        onSave();
        setTimeout(()=>setIsConfirming(false), 400);
    };
    // Cards stack vertically with small offset (handled by parent)
    // Active card lifts up slightly
    const verticalLift = isActive ? -20 : 0;
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
        layout: true,
        initial: {
            scale: 0.8,
            opacity: 0,
            y: 20
        },
        animate: {
            scale: isActive ? 1.05 : 1,
            opacity: 1,
            y: verticalLift,
            zIndex: isActive ? 30 : 20 - index
        },
        exit: {
            scale: 0.8,
            opacity: 0,
            y: 20
        },
        transition: {
            type: "spring",
            stiffness: 300,
            damping: 30,
            duration: 0.3
        },
        className: "relative",
        style: {
            width: CARD_SIZE,
            transformOrigin: "center center"
        },
        onClick: (e)=>e.stopPropagation(),
        onMouseDown: (e)=>e.stopPropagation(),
        onPointerDown: (e)=>e.stopPropagation(),
        children: [
            !isCleanTheme && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                className: "absolute -inset-0.5 pointer-events-none rounded-3xl",
                style: {
                    padding: "2px",
                    background: `conic-gradient(from 0deg, 
              transparent 0deg, 
              ${theme.shimmer.secondary}${Math.round(30 * shimmerOpacity).toString(16).padStart(2, '0')} 60deg, 
              ${theme.shimmer.primary}${Math.round(isActive ? 255 : 230 * shimmerOpacity).toString(16).padStart(2, '0')} 180deg, 
              ${theme.shimmer.secondary}${Math.round(30 * shimmerOpacity).toString(16).padStart(2, '0')} 300deg, 
              transparent 360deg)`,
                    WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
                    WebkitMaskComposite: "xor"
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
                fileName: "[project]/components/mini-node-card.tsx",
                lineNumber: 209,
                columnNumber: 9
            }, this),
            isActive && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                className: "absolute -inset-2 pointer-events-none rounded-3xl",
                style: {
                    background: `radial-gradient(circle, ${theme.glow.color}${Math.round(glowOpacity * 255).toString(16).padStart(2, '0')} 0%, transparent 70%)`,
                    filter: `blur(${theme.glow.blur}px)`
                },
                initial: {
                    opacity: 0
                },
                animate: {
                    opacity: 1
                }
            }, void 0, false, {
                fileName: "[project]/components/mini-node-card.tsx",
                lineNumber: 229,
                columnNumber: 9
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "relative w-full flex flex-col rounded-3xl overflow-hidden pointer-events-auto",
                style: {
                    background: `linear-gradient(${theme.gradient.angle}deg, ${theme.gradient.from}${Math.round(glassOpacity * 255).toString(16).padStart(2, '0')}, ${theme.gradient.to}${Math.round(glassOpacity * 255).toString(16).padStart(2, '0')})`,
                    backdropFilter: `blur(${theme.glass.blur}px)`,
                    WebkitBackdropFilter: `blur(${theme.glass.blur}px)`,
                    border: `1px solid ${theme.shimmer.primary}${Math.round(theme.glass.borderOpacity * 255).toString(16).padStart(2, '0')}`,
                    boxShadow: `inset 0 1px 1px rgba(255,255,255,0.1), 0 4px 24px rgba(0,0,0,0.2)`,
                    minHeight: CARD_SIZE
                },
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "absolute top-0 left-0 right-0 h-[52px] pointer-events-none",
                        style: {
                            background: `linear-gradient(180deg, ${theme.shimmer.primary}40 0%, transparent 100%)`
                        }
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 253,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "relative flex items-center justify-center gap-2 px-3 py-3 border-b",
                        style: {
                            borderColor: `${theme.shimmer.primary}${Math.round(0.35 * 255).toString(16).padStart(2, '0')}`
                        },
                        children: [
                            /*#__PURE__*/ __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["default"].createElement(IconComponent, {
                                className: "w-5 h-5",
                                style: {
                                    color: '#ffffff',
                                    filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.7))'
                                },
                                strokeWidth: 1.5
                            }),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                className: "text-xs font-semibold tracking-wider uppercase",
                                style: {
                                    color: '#ffffff',
                                    textShadow: '0 1px 2px rgba(0,0,0,0.7), 0 0 2px rgba(0,0,0,0.5)',
                                    letterSpacing: '0.1em'
                                },
                                children: miniNode.label
                            }, void 0, false, {
                                fileName: "[project]/components/mini-node-card.tsx",
                                lineNumber: 273,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 261,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "p-3 space-y-2 flex-1",
                        style: {
                            background: `radial-gradient(circle at top, ${theme.shimmer.primary}20 0%, transparent 70%)`
                        },
                        children: miniNode.fields?.map((field)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "text-xs",
                                children: renderField(field, values[field.id], (value)=>onChange(field.id, value), glowColor, theme, isCleanTheme)
                            }, field.id, false, {
                                fileName: "[project]/components/mini-node-card.tsx",
                                lineNumber: 285,
                                columnNumber: 13
                            }, this))
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 283,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                        children: isActive && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                            initial: {
                                opacity: 0,
                                height: 0
                            },
                            animate: {
                                opacity: 1,
                                height: "auto"
                            },
                            exit: {
                                opacity: 0,
                                height: 0
                            },
                            className: "px-3 pb-3",
                            children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].button, {
                                onClick: (e)=>{
                                    e.stopPropagation();
                                    handleSave();
                                },
                                disabled: isConfirming,
                                whileHover: {
                                    scale: 1.02
                                },
                                whileTap: {
                                    scale: 0.98
                                },
                                animate: isConfirming ? {
                                    scale: [
                                        1,
                                        1.1,
                                        1
                                    ]
                                } : {},
                                transition: {
                                    duration: 0.3
                                },
                                className: "w-full py-2 rounded-xl text-xs font-medium transition-all duration-200",
                                style: {
                                    background: isConfirming ? "rgba(34, 197, 94, 0.8)" : `linear-gradient(135deg, ${theme.shimmer.primary}cc, ${theme.shimmer.primary}66)`,
                                    color: "white",
                                    boxShadow: isConfirming ? "0 0 20px rgba(34, 197, 94, 0.4)" : `0 0 15px ${theme.glow.color}4d`
                                },
                                children: isConfirming ? "✓ Saved" : "Save"
                            }, void 0, false, {
                                fileName: "[project]/components/mini-node-card.tsx",
                                lineNumber: 300,
                                columnNumber: 15
                            }, this)
                        }, void 0, false, {
                            fileName: "[project]/components/mini-node-card.tsx",
                            lineNumber: 294,
                            columnNumber: 13
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-card.tsx",
                        lineNumber: 292,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/mini-node-card.tsx",
                lineNumber: 241,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/components/mini-node-card.tsx",
        lineNumber: 182,
        columnNumber: 5
    }, this);
}
}),
"[project]/components/mini-node-stack.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "MiniNodeStack",
    ()=>MiniNodeStack
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/framer-motion/dist/es/render/components/motion/proxy.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/framer-motion/dist/es/components/AnimatePresence/index.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$lucide$2d$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/lucide-react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$mini$2d$node$2d$card$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/mini-node-card.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$NavigationContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/NavigationContext.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/BrandColorContext.tsx [app-ssr] (ecmascript)");
"use client";
;
;
;
;
;
;
;
// Dynamically get Lucide icon
function getIcon(iconName) {
    const icons = __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$lucide$2d$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__;
    return icons[iconName] || __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$lucide$2d$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__.Circle;
}
function MiniNodeStack({ miniNodes }) {
    const { getThemeConfig } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useBrandColor"])();
    const theme = getThemeConfig();
    const glowColor = theme.glow.color;
    const isVerdant = theme.orbs === null;
    const { state, updateMiniNodeValue, confirmMiniNode, jumpToMiniNode, rotateStackForward, rotateStackBackward } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$NavigationContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useNavigation"])();
    const { activeMiniNodeIndex, miniNodeValues } = state;
    // Only show up to 4 cards
    const visibleNodes = miniNodes.slice(0, 4);
    const handleValueChange = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((nodeId, fieldId, value)=>{
        updateMiniNodeValue(nodeId, fieldId, value);
    }, [
        updateMiniNodeValue
    ]);
    const handleSave = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((nodeId)=>{
        const values = miniNodeValues[nodeId] || {};
        confirmMiniNode(nodeId, values);
    }, [
        confirmMiniNode,
        miniNodeValues
    ]);
    const handleCardClick = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((index)=>{
        jumpToMiniNode(index);
    }, [
        jumpToMiniNode
    ]);
    if (miniNodes.length === 0) {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
            initial: {
                opacity: 0
            },
            animate: {
                opacity: 1
            },
            className: "flex items-center justify-center h-64 text-white/40",
            children: "No settings available"
        }, void 0, false, {
            fileName: "[project]/components/mini-node-stack.tsx",
            lineNumber: 65,
            columnNumber: 7
        }, this);
    }
    // Cards stacked on top of each other with small vertical offset (like a deck)
    const containerWidth = 220;
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "relative",
        style: {
            width: containerWidth
        },
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "relative flex items-center justify-center",
                style: {
                    height: 320,
                    width: containerWidth
                },
                onClick: (e)=>e.stopPropagation(),
                onMouseDown: (e)=>e.stopPropagation(),
                onPointerDown: (e)=>e.stopPropagation(),
                children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                    mode: "popLayout",
                    children: visibleNodes.map((miniNode, index)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                            onClick: (e)=>{
                                e.stopPropagation();
                                handleCardClick(index);
                            },
                            onMouseDown: (e)=>e.stopPropagation(),
                            onPointerDown: (e)=>e.stopPropagation(),
                            className: "cursor-pointer absolute",
                            style: {
                                left: 20,
                                top: index * 8,
                                zIndex: index === activeMiniNodeIndex ? 30 : 20 - index
                            },
                            initial: {
                                opacity: 0,
                                scale: 0.5,
                                x: -100,
                                y: 50
                            },
                            animate: {
                                opacity: 1,
                                scale: index === activeMiniNodeIndex ? 1.05 : 1,
                                x: 0,
                                y: 0
                            },
                            exit: {
                                opacity: 0,
                                scale: 0.8,
                                x: -50,
                                y: 30,
                                transition: {
                                    duration: 0.4
                                } // 400ms exit
                            },
                            transition: {
                                duration: 0.6,
                                delay: index * 0.1,
                                ease: [
                                    0.25,
                                    0.46,
                                    0.45,
                                    0.94
                                ] // Smooth easing
                            },
                            children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$mini$2d$node$2d$card$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["MiniNodeCard"], {
                                miniNode: miniNode,
                                isActive: index === activeMiniNodeIndex,
                                values: miniNodeValues[miniNode.id] || {},
                                onChange: (fieldId, value)=>handleValueChange(miniNode.id, fieldId, value),
                                onSave: ()=>handleSave(miniNode.id),
                                index: index
                            }, void 0, false, {
                                fileName: "[project]/components/mini-node-stack.tsx",
                                lineNumber: 131,
                                columnNumber: 15
                            }, this)
                        }, miniNode.id, false, {
                            fileName: "[project]/components/mini-node-stack.tsx",
                            lineNumber: 92,
                            columnNumber: 13
                        }, this))
                }, void 0, false, {
                    fileName: "[project]/components/mini-node-stack.tsx",
                    lineNumber: 90,
                    columnNumber: 9
                }, this)
            }, void 0, false, {
                fileName: "[project]/components/mini-node-stack.tsx",
                lineNumber: 80,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "absolute -bottom-20 left-1/2 -translate-x-1/2 z-50",
                onClick: (e)=>e.stopPropagation(),
                onMouseDown: (e)=>e.stopPropagation(),
                onPointerDown: (e)=>e.stopPropagation(),
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "flex items-center gap-1 px-3 py-2 rounded-2xl",
                        style: {
                            background: `linear-gradient(135deg, ${glowColor.replace(')', ', 0.15)')}, ${glowColor.replace(')', ', 0.05)')})`,
                            backdropFilter: 'blur(12px)',
                            border: `1px solid ${glowColor.replace(')', ', 0.2)')}`,
                            boxShadow: `0 4px 24px ${glowColor.replace(')', ', 0.15)')}`
                        },
                        children: visibleNodes.map((miniNode, index)=>{
                            const IconComponent = getIcon(miniNode.icon);
                            const isActive = index === activeMiniNodeIndex;
                            return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].button, {
                                onClick: (e)=>{
                                    e.stopPropagation();
                                    handleCardClick(index);
                                },
                                onMouseDown: (e)=>e.stopPropagation(),
                                onPointerDown: (e)=>e.stopPropagation(),
                                whileHover: {
                                    scale: 1.05
                                },
                                whileTap: {
                                    scale: 0.95
                                },
                                className: "relative flex flex-col items-center gap-1 px-3 py-2 rounded-xl transition-all duration-200",
                                style: {
                                    background: isActive ? `linear-gradient(135deg, ${glowColor.replace(')', ', 0.3)')}, ${glowColor.replace(')', ', 0.1)')})` : 'transparent',
                                    border: isActive ? `1px solid ${glowColor.replace(')', ', 0.5)')}` : '1px solid transparent'
                                },
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(IconComponent, {
                                        className: "w-4 h-4",
                                        style: {
                                            color: isActive ? '#ffffff' : `${glowColor.replace(')', ', 0.6)')}`,
                                            filter: isActive ? 'drop-shadow(0 0 4px ' + glowColor + ')' : 'none'
                                        }
                                    }, void 0, false, {
                                        fileName: "[project]/components/mini-node-stack.tsx",
                                        lineNumber: 187,
                                        columnNumber: 17
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        className: "text-[9px] font-medium uppercase tracking-wider",
                                        style: {
                                            color: isActive ? '#ffffff' : `${glowColor.replace(')', ', 0.5)')}`
                                        },
                                        children: miniNode.label.slice(0, 6)
                                    }, void 0, false, {
                                        fileName: "[project]/components/mini-node-stack.tsx",
                                        lineNumber: 194,
                                        columnNumber: 17
                                    }, this),
                                    isActive && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                                        layoutId: "activeIndicator",
                                        className: "absolute -bottom-1 w-8 h-0.5 rounded-full",
                                        style: {
                                            background: glowColor
                                        },
                                        transition: {
                                            type: "spring",
                                            stiffness: 300,
                                            damping: 30
                                        }
                                    }, void 0, false, {
                                        fileName: "[project]/components/mini-node-stack.tsx",
                                        lineNumber: 205,
                                        columnNumber: 19
                                    }, this)
                                ]
                            }, miniNode.id, true, {
                                fileName: "[project]/components/mini-node-stack.tsx",
                                lineNumber: 167,
                                columnNumber: 15
                            }, this);
                        })
                    }, void 0, false, {
                        fileName: "[project]/components/mini-node-stack.tsx",
                        lineNumber: 153,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "text-center mt-2 text-[10px] font-medium tracking-wider",
                        style: {
                            color: `${glowColor.replace(')', ', 0.6)')}`
                        },
                        children: [
                            activeMiniNodeIndex + 1,
                            " / ",
                            miniNodes.length
                        ]
                    }, void 0, true, {
                        fileName: "[project]/components/mini-node-stack.tsx",
                        lineNumber: 218,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/mini-node-stack.tsx",
                lineNumber: 147,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/components/mini-node-stack.tsx",
        lineNumber: 79,
        columnNumber: 5
    }, this);
}
}),
"[project]/hooks/useTransitionVariants.ts [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "useTransitionVariants",
    ()=>useTransitionVariants
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$TransitionContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/TransitionContext.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$lib$2f$transitions$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/lib/transitions.ts [app-ssr] (ecmascript)");
'use client';
;
;
function useTransitionVariants() {
    const { currentTransition } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$TransitionContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useTransition"])();
    const variants = (0, __TURBOPACK__imported__module__$5b$project$5d2f$lib$2f$transitions$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["getVariantsForTransition"])(currentTransition);
    const staggerDelay = (0, __TURBOPACK__imported__module__$5b$project$5d2f$lib$2f$transitions$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["getStaggerDelay"])(currentTransition);
    // Convert transition type to display name
    const transitionName = currentTransition.split('-').map((word)=>word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
    console.log('[useTransitionVariants] Current:', currentTransition, 'Stagger:', staggerDelay);
    return {
        variants,
        staggerDelay,
        transitionName
    };
}
}),
"[project]/components/iris/prism-node.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "HexagonalNode",
    ()=>HexagonalNode,
    "PrismNode",
    ()=>PrismNode
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/framer-motion/dist/es/render/components/motion/proxy.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/BrandColorContext.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$hooks$2f$useTransitionVariants$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/hooks/useTransitionVariants.ts [app-ssr] (ecmascript)");
"use client";
;
;
;
;
function getSpiralPosition(baseAngle, radius, spinRotations) {
    const finalAngleRad = baseAngle * Math.PI / 180;
    return {
        x: Math.cos(finalAngleRad) * radius,
        y: Math.sin(finalAngleRad) * radius,
        rotation: spinRotations * 360
    };
}
function PrismNode({ node, angle, radius, nodeSize, onClick, spinRotations, spinDuration, staggerIndex, isCollapsing, isActive, spinConfig, themeIntensity = 'medium' }) {
    const Icon = node.icon;
    const pos = getSpiralPosition(angle, radius, spinRotations);
    const counterRotation = -pos.rotation;
    const { getThemeConfig } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useBrandColor"])();
    const { variants } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$hooks$2f$useTransitionVariants$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useTransitionVariants"])();
    // Get complete theme configuration
    const theme = getThemeConfig();
    // DEBUG: Log theme config
    console.log('[Nav System] PrismNode theme:', {
        name: theme.name,
        gradient: theme.gradient,
        shimmer: theme.shimmer,
        glass: theme.glass,
        glow: theme.glow
    });
    // Check if theme should have clean look (no rotating effects)
    const isCleanTheme = theme.name === 'Verdant' || theme.name === 'Aurum';
    // Icon color: always white for maximum contrast across all themes
    const iconColor = 'rgba(255, 255, 255, 0.95)';
    // Intensity adjustments for glass effect
    const intensityMultipliers = {
        subtle: {
            glassOpacity: 0.7,
            glowOpacity: 0.6,
            shimmerOpacity: 0.5
        },
        medium: {
            glassOpacity: 1.0,
            glowOpacity: 1.0,
            shimmerOpacity: 1.0
        },
        strong: {
            glassOpacity: 1.3,
            glowOpacity: 1.4,
            shimmerOpacity: 1.2
        }
    }[themeIntensity];
    // Merge transition variants with position/rotation animations
    const baseTransition = {
        duration: spinDuration / 1000,
        delay: staggerIndex * (spinConfig.staggerDelay / 1000),
        ease: spinConfig.ease
    };
    const spiralVariants = {
        collapsed: {
            ...variants.hidden,
            x: 0,
            y: 0
        },
        expanded: {
            ...variants.visible,
            x: pos.x,
            y: pos.y,
            rotate: pos.rotation,
            transition: {
                ...baseTransition,
                ...variants.visible?.transition
            }
        },
        exit: {
            ...variants.exit,
            x: 0,
            y: 0,
            transition: {
                ...baseTransition,
                ...variants.exit?.transition
            }
        }
    };
    const contentVariants = {
        collapsed: {
            rotate: 0
        },
        expanded: {
            rotate: counterRotation,
            transition: baseTransition
        },
        exit: {
            rotate: 360,
            transition: baseTransition
        }
    };
    // Calculate adjusted values based on intensity
    const glassOpacity = Math.min(theme.glass.opacity * intensityMultipliers.glassOpacity, 0.35);
    const glowOpacity = Math.min(theme.glow.opacity * intensityMultipliers.glowOpacity, 0.5);
    const shimmerOpacity = Math.min(1 * intensityMultipliers.shimmerOpacity, 1);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].button, {
        className: "absolute flex flex-col items-center justify-center cursor-pointer z-10 pointer-events-auto",
        style: {
            left: "50%",
            top: "50%",
            marginLeft: -nodeSize / 2,
            marginTop: -nodeSize / 2,
            width: nodeSize,
            height: nodeSize
        },
        variants: spiralVariants,
        initial: "collapsed",
        animate: isCollapsing ? "exit" : "expanded",
        exit: "exit",
        onClick: (e)=>{
            e.stopPropagation();
            onClick(e);
        },
        onMouseDown: (e)=>e.stopPropagation(),
        onPointerDown: (e)=>e.stopPropagation(),
        whileHover: {
            scale: 1.05
        },
        whileTap: {
            scale: 0.95
        },
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "absolute -inset-4 rounded-[2.5rem] pointer-events-none",
                style: {
                    background: `radial-gradient(circle, ${theme.glow.color}${Math.round(glowOpacity * 255).toString(16).padStart(2, '0')} 0%, transparent 70%)`,
                    filter: `blur(${theme.glow.blur}px)`,
                    opacity: isActive ? 1 : 0.6
                }
            }, void 0, false, {
                fileName: "[project]/components/iris/prism-node.tsx",
                lineNumber: 154,
                columnNumber: 7
            }, this),
            isActive && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                className: "absolute -inset-3 rounded-[2.5rem] pointer-events-none",
                style: {
                    background: `radial-gradient(circle, ${theme.shimmer.primary}50 0%, transparent 60%)`,
                    filter: "blur(16px)"
                },
                animate: {
                    opacity: [
                        0.4,
                        0.8,
                        0.4
                    ]
                },
                transition: {
                    duration: 2,
                    repeat: Infinity
                }
            }, void 0, false, {
                fileName: "[project]/components/iris/prism-node.tsx",
                lineNumber: 165,
                columnNumber: 9
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "relative w-full h-full flex flex-col items-center justify-center overflow-hidden",
                style: {
                    borderRadius: "2.5rem",
                    background: `linear-gradient(${theme.gradient.angle}deg, ${theme.gradient.from}${Math.round(glassOpacity * 255).toString(16).padStart(2, '0')}, ${theme.gradient.to}${Math.round(glassOpacity * 255).toString(16).padStart(2, '0')})`,
                    backdropFilter: `blur(${theme.glass.blur}px)`,
                    border: `1px solid rgba(255,255,255,${theme.glass.borderOpacity})`,
                    boxShadow: `inset 0 1px 1px rgba(255,255,255,0.1), 0 4px 24px rgba(0,0,0,0.2)`
                },
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "absolute inset-0 rounded-[2.5rem] pointer-events-none",
                        style: {
                            background: `linear-gradient(135deg, ${theme.gradient.from}30 0%, transparent 50%, ${theme.gradient.to}15 100%)`
                        }
                    }, void 0, false, {
                        fileName: "[project]/components/iris/prism-node.tsx",
                        lineNumber: 188,
                        columnNumber: 9
                    }, this),
                    theme.orbs && theme.orbs.map((orb, i)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                            className: "absolute rounded-full pointer-events-none",
                            style: {
                                width: orb.size * (isActive ? 1.2 : 1),
                                height: orb.size * (isActive ? 1.2 : 1),
                                left: `calc(50% + ${orb.x}px)`,
                                top: `calc(50% + ${orb.y}px)`,
                                marginLeft: -orb.size / 2,
                                marginTop: -orb.size / 2,
                                background: orb.color,
                                filter: `blur(${orb.blur}px)`,
                                opacity: 0.5 * intensityMultipliers.glowOpacity
                            },
                            animate: {
                                x: [
                                    0,
                                    15,
                                    -10,
                                    0
                                ],
                                y: [
                                    0,
                                    -12,
                                    8,
                                    0
                                ],
                                scale: [
                                    1,
                                    1.15,
                                    0.95,
                                    1
                                ]
                            },
                            transition: {
                                duration: 8 + i * 2,
                                repeat: Infinity,
                                ease: "easeInOut",
                                delay: i * 0.5
                            }
                        }, i, false, {
                            fileName: "[project]/components/iris/prism-node.tsx",
                            lineNumber: 197,
                            columnNumber: 11
                        }, this)),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                        className: "relative z-10 flex flex-col items-center justify-center gap-2 pointer-events-none",
                        variants: contentVariants,
                        initial: "collapsed",
                        animate: isCollapsing ? "exit" : "expanded",
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(Icon, {
                                className: "w-6 h-6",
                                style: {
                                    color: '#ffffff',
                                    filter: 'drop-shadow(0 1px 2px rgba(0,0,0,0.7))'
                                },
                                strokeWidth: 1.5
                            }, void 0, false, {
                                fileName: "[project]/components/iris/prism-node.tsx",
                                lineNumber: 250,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                className: "text-[10px] font-semibold tracking-wider uppercase",
                                style: {
                                    color: '#ffffff',
                                    textShadow: '0 1px 2px rgba(0,0,0,0.7), 0 0 2px rgba(0,0,0,0.5)',
                                    letterSpacing: '0.1em'
                                },
                                children: node.label
                            }, void 0, false, {
                                fileName: "[project]/components/iris/prism-node.tsx",
                                lineNumber: 258,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/components/iris/prism-node.tsx",
                        lineNumber: 244,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/iris/prism-node.tsx",
                lineNumber: 177,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/components/iris/prism-node.tsx",
        lineNumber: 130,
        columnNumber: 5
    }, this);
}
const HexagonalNode = PrismNode;
}),
"[project]/components/hexagonal-control-center.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "HexagonalControlCenter",
    ()=>HexagonalControlCenter
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/framer-motion/dist/es/render/components/motion/proxy.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/framer-motion/dist/es/components/AnimatePresence/index.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$mic$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Mic$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/mic.js [app-ssr] (ecmascript) <export default as Mic>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$brain$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Brain$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/brain.js [app-ssr] (ecmascript) <export default as Brain>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$bot$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Bot$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/bot.js [app-ssr] (ecmascript) <export default as Bot>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$settings$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Settings$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/settings.js [app-ssr] (ecmascript) <export default as Settings>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$database$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Database$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/database.js [app-ssr] (ecmascript) <export default as Database>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$activity$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Activity$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/activity.js [app-ssr] (ecmascript) <export default as Activity>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$volume$2d$2$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Volume2$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/volume-2.js [app-ssr] (ecmascript) <export default as Volume2>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$headphones$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Headphones$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/headphones.js [app-ssr] (ecmascript) <export default as Headphones>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$audio$2d$waveform$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__AudioWaveform$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/audio-waveform.js [app-ssr] (ecmascript) <export default as AudioWaveform>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$link$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Link$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/link.js [app-ssr] (ecmascript) <export default as Link>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$cpu$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Cpu$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/cpu.js [app-ssr] (ecmascript) <export default as Cpu>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sparkles$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Sparkles$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/sparkles.js [app-ssr] (ecmascript) <export default as Sparkles>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$message$2d$square$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__MessageSquare$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/message-square.js [app-ssr] (ecmascript) <export default as MessageSquare>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$palette$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Palette$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/palette.js [app-ssr] (ecmascript) <export default as Palette>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$power$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Power$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/power.js [app-ssr] (ecmascript) <export default as Power>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$keyboard$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Keyboard$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/keyboard.js [app-ssr] (ecmascript) <export default as Keyboard>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$minimize$2d$2$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Minimize2$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/minimize-2.js [app-ssr] (ecmascript) <export default as Minimize2>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$refresh$2d$cw$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__RefreshCw$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/refresh-cw.js [app-ssr] (ecmascript) <export default as RefreshCw>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$history$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__History$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/history.js [app-ssr] (ecmascript) <export default as History>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$file$2d$stack$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__FileStack$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/file-stack.js [app-ssr] (ecmascript) <export default as FileStack>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$trash$2d$2$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Trash2$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/trash-2.js [app-ssr] (ecmascript) <export default as Trash2>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$timer$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Timer$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/timer.js [app-ssr] (ecmascript) <export default as Timer>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$clock$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Clock$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/clock.js [app-ssr] (ecmascript) <export default as Clock>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chart$2d$column$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__BarChart3$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/chart-column.js [app-ssr] (ecmascript) <export default as BarChart3>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$dollar$2d$sign$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__DollarSign$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/dollar-sign.js [app-ssr] (ecmascript) <export default as DollarSign>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$trending$2d$up$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__TrendingUp$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/trending-up.js [app-ssr] (ecmascript) <export default as TrendingUp>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$wrench$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Wrench$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/wrench.js [app-ssr] (ecmascript) <export default as Wrench>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$layers$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Layers$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/layers.js [app-ssr] (ecmascript) <export default as Layers>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$star$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Star$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/star.js [app-ssr] (ecmascript) <export default as Star>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$monitor$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Monitor$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/monitor.js [app-ssr] (ecmascript) <export default as Monitor>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$hard$2d$drive$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__HardDrive$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/hard-drive.js [app-ssr] (ecmascript) <export default as HardDrive>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$wifi$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Wifi$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/wifi.js [app-ssr] (ecmascript) <export default as Wifi>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$bell$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Bell$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/bell.js [app-ssr] (ecmascript) <export default as Bell>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sliders$2d$vertical$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Sliders$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/sliders-vertical.js [app-ssr] (ecmascript) <export default as Sliders>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$file$2d$text$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__FileText$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/file-text.js [app-ssr] (ecmascript) <export default as FileText>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$stethoscope$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Stethoscope$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/stethoscope.js [app-ssr] (ecmascript) <export default as Stethoscope>");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$smile$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Smile$3e$__ = __turbopack_context__.i("[project]/node_modules/lucide-react/dist/esm/icons/smile.js [app-ssr] (ecmascript) <export default as Smile>");
var __TURBOPACK__imported__module__$5b$project$5d2f$hooks$2f$useIRISWebSocket$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/hooks/useIRISWebSocket.ts [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$NavigationContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/NavigationContext.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/contexts/BrandColorContext.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$mini$2d$node$2d$stack$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/mini-node-stack.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$components$2f$iris$2f$prism$2d$node$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/components/iris/prism-node.tsx [app-ssr] (ecmascript)");
"use client";
;
;
;
// Tauri imports - only work in Tauri app, not browser
let getCurrentWindow = null;
let PhysicalPosition = null;
if ("TURBOPACK compile-time falsy", 0) //TURBOPACK unreachable
;
;
;
;
;
;
;
const SPIN_CONFIG = {
    radiusCollapsed: 0,
    radiusExpanded: 180,
    spinDuration: 1500,
    staggerDelay: 100,
    rotations: 2,
    ease: [
        0.4,
        0,
        0.2,
        1
    ]
};
const SUBMENU_CONFIG = {
    radius: 140,
    spinDuration: 1500,
    rotations: 2
};
const MINI_NODE_STACK_CONFIG = {
    size: 90,
    sizeConfirmed: 90,
    borderRadius: 16,
    stackDepth: 50,
    maxVisible: 4,
    offsetX: 0,
    offsetY: 0,
    distanceFromCenter: 260,
    scaleReduction: 0.08,
    padding: 16,
    fieldHeight: 36,
    fieldGap: 12
};
const ORBIT_CONFIG = {
    radius: 200,
    duration: 800,
    ease: [
        0.34,
        1.56,
        0.64,
        1
    ]
};
const NODE_POSITIONS = [
    {
        index: 0,
        angle: -90,
        id: "voice",
        label: "VOICE",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$mic$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Mic$3e$__["Mic"],
        hasSubnodes: true
    },
    {
        index: 1,
        angle: -30,
        id: "agent",
        label: "AGENT",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$bot$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Bot$3e$__["Bot"],
        hasSubnodes: true
    },
    {
        index: 2,
        angle: 30,
        id: "automate",
        label: "AUTOMATE",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$cpu$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Cpu$3e$__["Cpu"],
        hasSubnodes: true
    },
    {
        index: 3,
        angle: 90,
        id: "system",
        label: "SYSTEM",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$settings$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Settings$3e$__["Settings"],
        hasSubnodes: true
    },
    {
        index: 4,
        angle: 150,
        id: "customize",
        label: "CUSTOMIZE",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$palette$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Palette$3e$__["Palette"],
        hasSubnodes: true
    },
    {
        index: 5,
        angle: 210,
        id: "monitor",
        label: "MONITOR",
        icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$activity$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Activity$3e$__["Activity"],
        hasSubnodes: true
    }
];
const SUB_NODES = {
    voice: [
        {
            id: "input",
            label: "INPUT",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$mic$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Mic$3e$__["Mic"],
            fields: [
                {
                    id: "input_device",
                    label: "Input Device",
                    type: "dropdown",
                    options: [
                        "Default",
                        "USB Microphone",
                        "Headset",
                        "Webcam"
                    ],
                    defaultValue: "Default"
                },
                {
                    id: "input_sensitivity",
                    label: "Input Sensitivity",
                    type: "slider",
                    min: 0,
                    max: 100,
                    unit: "%",
                    defaultValue: 50
                },
                {
                    id: "noise_gate",
                    label: "Noise Gate",
                    type: "toggle",
                    defaultValue: false
                },
                {
                    id: "vad",
                    label: "VAD",
                    type: "toggle",
                    defaultValue: true
                }
            ]
        },
        {
            id: "output",
            label: "OUTPUT",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$volume$2d$2$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Volume2$3e$__["Volume2"],
            fields: [
                {
                    id: "output_device",
                    label: "Output Device",
                    type: "dropdown",
                    options: [
                        "Default",
                        "Headphones",
                        "Speakers",
                        "HDMI"
                    ],
                    defaultValue: "Default"
                },
                {
                    id: "master_volume",
                    label: "Master Volume",
                    type: "slider",
                    min: 0,
                    max: 100,
                    unit: "%",
                    defaultValue: 70
                }
            ]
        },
        {
            id: "processing",
            label: "PROCESSING",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$audio$2d$waveform$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__AudioWaveform$3e$__["AudioWaveform"],
            fields: [
                {
                    id: "noise_reduction",
                    label: "Noise Reduction",
                    type: "toggle",
                    defaultValue: true
                },
                {
                    id: "echo_cancellation",
                    label: "Echo Cancellation",
                    type: "toggle",
                    defaultValue: true
                },
                {
                    id: "voice_enhancement",
                    label: "Voice Enhancement",
                    type: "toggle",
                    defaultValue: false
                },
                {
                    id: "automatic_gain",
                    label: "Automatic Gain",
                    type: "toggle",
                    defaultValue: true
                }
            ]
        },
        {
            id: "model",
            label: "MODEL",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$brain$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Brain$3e$__["Brain"],
            fields: [
                {
                    id: "endpoint",
                    label: "LFM Endpoint",
                    type: "text",
                    placeholder: "http://localhost:1234",
                    defaultValue: "http://localhost:1234"
                },
                {
                    id: "temperature",
                    label: "Temperature",
                    type: "slider",
                    min: 0,
                    max: 2,
                    step: 0.1,
                    defaultValue: 0.7
                },
                {
                    id: "max_tokens",
                    label: "Max Tokens",
                    type: "slider",
                    min: 256,
                    max: 8192,
                    step: 256,
                    defaultValue: 2048
                },
                {
                    id: "context_window",
                    label: "Context Window",
                    type: "slider",
                    min: 1024,
                    max: 32768,
                    step: 1024,
                    defaultValue: 8192
                }
            ]
        }
    ],
    agent: [
        {
            id: "identity",
            label: "IDENTITY",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$smile$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Smile$3e$__["Smile"],
            fields: [
                {
                    id: "assistant_name",
                    label: "Assistant Name",
                    type: "text",
                    placeholder: "IRIS",
                    defaultValue: "IRIS"
                },
                {
                    id: "personality",
                    label: "Personality",
                    type: "dropdown",
                    options: [
                        "Professional",
                        "Friendly",
                        "Concise",
                        "Creative",
                        "Technical"
                    ],
                    defaultValue: "Friendly"
                },
                {
                    id: "knowledge",
                    label: "Knowledge Focus",
                    type: "dropdown",
                    options: [
                        "General",
                        "Coding",
                        "Writing",
                        "Research",
                        "Conversation"
                    ],
                    defaultValue: "General"
                },
                {
                    id: "response_length",
                    label: "Response Length",
                    type: "dropdown",
                    options: [
                        "Brief",
                        "Balanced",
                        "Detailed",
                        "Comprehensive"
                    ],
                    defaultValue: "Balanced"
                }
            ]
        },
        {
            id: "wake",
            label: "WAKE",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sparkles$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Sparkles$3e$__["Sparkles"],
            fields: [
                {
                    id: "wake_phrase",
                    label: "Wake Phrase",
                    type: "text",
                    placeholder: "Hey IRIS",
                    defaultValue: "Hey IRIS"
                },
                {
                    id: "detection_sensitivity",
                    label: "Detection Sensitivity",
                    type: "slider",
                    min: 0,
                    max: 100,
                    defaultValue: 70,
                    unit: "%"
                },
                {
                    id: "activation_sound",
                    label: "Activation Sound",
                    type: "toggle",
                    defaultValue: true
                },
                {
                    id: "sleep_timeout",
                    label: "Sleep Timeout",
                    type: "slider",
                    min: 5,
                    max: 300,
                    defaultValue: 60,
                    unit: "s"
                }
            ]
        },
        {
            id: "speech",
            label: "SPEECH",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$message$2d$square$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__MessageSquare$3e$__["MessageSquare"],
            fields: [
                {
                    id: "tts_voice",
                    label: "TTS Voice",
                    type: "dropdown",
                    options: [
                        "Nova",
                        "Alloy",
                        "Echo",
                        "Fable",
                        "Onyx",
                        "Shimmer"
                    ],
                    defaultValue: "Nova"
                },
                {
                    id: "speaking_rate",
                    label: "Speaking Rate",
                    type: "slider",
                    min: 0.5,
                    max: 2,
                    step: 0.1,
                    defaultValue: 1.0,
                    unit: "x"
                },
                {
                    id: "pitch_adjustment",
                    label: "Pitch Adjustment",
                    type: "slider",
                    min: -20,
                    max: 20,
                    defaultValue: 0,
                    unit: "semitones"
                },
                {
                    id: "pause_duration",
                    label: "Pause Duration",
                    type: "slider",
                    min: 0,
                    max: 2,
                    step: 0.1,
                    defaultValue: 0.2,
                    unit: "s"
                }
            ]
        },
        {
            id: "memory",
            label: "MEMORY",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$database$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Database$3e$__["Database"],
            fields: [
                {
                    id: "context_visualization",
                    label: "Context Visualization",
                    type: "text",
                    placeholder: "View context"
                },
                {
                    id: "token_count",
                    label: "Token Count",
                    type: "text",
                    placeholder: "0 tokens"
                },
                {
                    id: "conversation_history",
                    label: "Conversation History",
                    type: "text",
                    placeholder: "Browse history"
                },
                {
                    id: "clear_memory",
                    label: "Clear Memory",
                    type: "text",
                    placeholder: "Clear"
                }
            ]
        }
    ],
    automate: [
        {
            id: "tools",
            label: "TOOLS",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$wrench$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Wrench$3e$__["Wrench"],
            fields: [
                {
                    id: "active_servers",
                    label: "Active Servers",
                    type: "text",
                    placeholder: "Server status"
                },
                {
                    id: "tool_browser",
                    label: "Tool Browser",
                    type: "text",
                    placeholder: "Browse tools"
                },
                {
                    id: "quick_actions",
                    label: "Quick Actions",
                    type: "text",
                    placeholder: "Recent tools"
                }
            ]
        },
        {
            id: "workflows",
            label: "WORKFLOWS",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$layers$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Layers$3e$__["Layers"],
            fields: [
                {
                    id: "workflow_list",
                    label: "Workflow List",
                    type: "text",
                    placeholder: "Saved workflows"
                },
                {
                    id: "create_workflow",
                    label: "Create Workflow",
                    type: "text",
                    placeholder: "Builder"
                },
                {
                    id: "schedule",
                    label: "Schedule",
                    type: "text",
                    placeholder: "Schedule"
                }
            ]
        },
        {
            id: "favorites",
            label: "FAVORITES",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$star$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Star$3e$__["Star"],
            fields: [
                {
                    id: "favorite_commands",
                    label: "Favorite Commands",
                    type: "text",
                    placeholder: "Pinned actions"
                },
                {
                    id: "recent_actions",
                    label: "Recent Actions",
                    type: "text",
                    placeholder: "Recent"
                },
                {
                    id: "success_rate",
                    label: "Success Rate",
                    type: "text",
                    placeholder: "0%"
                }
            ]
        },
        {
            id: "shortcuts",
            label: "SHORTCUTS",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$keyboard$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Keyboard$3e$__["Keyboard"],
            fields: [
                {
                    id: "global_hotkey",
                    label: "Global Hotkey",
                    type: "text",
                    placeholder: "Ctrl+Space",
                    defaultValue: "Ctrl+Space"
                },
                {
                    id: "voice_commands",
                    label: "Voice Commands",
                    type: "text",
                    placeholder: "Map commands"
                }
            ]
        },
        {
            id: "gui",
            label: "GUI AUTOMATION",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$monitor$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Monitor$3e$__["Monitor"],
            fields: [
                {
                    id: "ui_tars_provider",
                    label: "UI-TARS Provider",
                    type: "dropdown",
                    options: [
                        "cli_npx",
                        "native_python",
                        "api_cloud"
                    ],
                    defaultValue: "native_python"
                },
                {
                    id: "model_provider",
                    label: "Vision Model",
                    type: "dropdown",
                    options: [
                        "anthropic",
                        "volcengine",
                        "local"
                    ],
                    defaultValue: "anthropic"
                },
                {
                    id: "api_key",
                    label: "API Key",
                    type: "text",
                    placeholder: "sk-..."
                },
                {
                    id: "max_steps",
                    label: "Max Automation Steps",
                    type: "slider",
                    min: 5,
                    max: 50,
                    defaultValue: 25
                },
                {
                    id: "safety_confirmation",
                    label: "Require Confirmation",
                    type: "toggle",
                    defaultValue: true
                }
            ]
        }
    ],
    system: [
        {
            id: "power",
            label: "POWER",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$power$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Power$3e$__["Power"],
            fields: [
                {
                    id: "shutdown",
                    label: "Shutdown",
                    type: "text",
                    placeholder: "Shutdown"
                },
                {
                    id: "restart",
                    label: "Restart",
                    type: "text",
                    placeholder: "Restart"
                },
                {
                    id: "sleep",
                    label: "Sleep",
                    type: "text",
                    placeholder: "Sleep"
                },
                {
                    id: "power_profile",
                    label: "Power Profile",
                    type: "dropdown",
                    options: [
                        "Balanced",
                        "Performance",
                        "Battery"
                    ],
                    defaultValue: "Balanced"
                }
            ]
        },
        {
            id: "display",
            label: "DISPLAY",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$monitor$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Monitor$3e$__["Monitor"],
            fields: [
                {
                    id: "brightness",
                    label: "Brightness",
                    type: "slider",
                    min: 0,
                    max: 100,
                    defaultValue: 50,
                    unit: "%"
                },
                {
                    id: "resolution",
                    label: "Resolution",
                    type: "dropdown",
                    options: [
                        "Auto",
                        "1920x1080",
                        "2560x1440",
                        "3840x2160"
                    ],
                    defaultValue: "Auto"
                },
                {
                    id: "night_mode",
                    label: "Night Mode",
                    type: "toggle",
                    defaultValue: false
                }
            ]
        },
        {
            id: "storage",
            label: "STORAGE",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$hard$2d$drive$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__HardDrive$3e$__["HardDrive"],
            fields: [
                {
                    id: "disk_usage",
                    label: "Disk Usage",
                    type: "text",
                    placeholder: "Usage"
                },
                {
                    id: "quick_folders",
                    label: "Quick Folders",
                    type: "text",
                    placeholder: "Desktop/Downloads/Documents"
                },
                {
                    id: "cleanup",
                    label: "Cleanup",
                    type: "text",
                    placeholder: "Cleanup"
                }
            ]
        },
        {
            id: "network",
            label: "NETWORK",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$wifi$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Wifi$3e$__["Wifi"],
            fields: [
                {
                    id: "wifi_toggle",
                    label: "WiFi",
                    type: "toggle",
                    defaultValue: true
                },
                {
                    id: "ethernet_status",
                    label: "Ethernet Status",
                    type: "text",
                    placeholder: "Connected"
                },
                {
                    id: "vpn_connection",
                    label: "VPN Connection",
                    type: "dropdown",
                    options: [
                        "None",
                        "Work",
                        "Personal"
                    ],
                    defaultValue: "None"
                }
            ]
        }
    ],
    customize: [
        {
            id: "theme",
            label: "THEME",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$palette$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Palette$3e$__["Palette"],
            fields: [
                {
                    id: "theme_mode",
                    label: "Theme Mode",
                    type: "dropdown",
                    options: [
                        "Dark",
                        "Light",
                        "Auto"
                    ],
                    defaultValue: "Dark"
                },
                {
                    id: "glow_color",
                    label: "Glow Color",
                    type: "color",
                    defaultValue: "#00ff88"
                },
                {
                    id: "state_colors",
                    label: "State Colors",
                    type: "toggle",
                    defaultValue: false
                }
            ]
        },
        {
            id: "startup",
            label: "STARTUP",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$power$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Power$3e$__["Power"],
            fields: [
                {
                    id: "launch_startup",
                    label: "Launch at Startup",
                    type: "toggle",
                    defaultValue: false
                },
                {
                    id: "startup_behavior",
                    label: "Startup Behavior",
                    type: "dropdown",
                    options: [
                        "Show Widget",
                        "Start Minimized",
                        "Start Hidden"
                    ],
                    defaultValue: "Show Widget"
                },
                {
                    id: "welcome_message",
                    label: "Welcome Message",
                    type: "toggle",
                    defaultValue: true
                }
            ]
        },
        {
            id: "behavior",
            label: "BEHAVIOR",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sliders$2d$vertical$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Sliders$3e$__["Sliders"],
            fields: [
                {
                    id: "confirm_destructive",
                    label: "Confirm Destructive",
                    type: "toggle",
                    defaultValue: true
                },
                {
                    id: "undo_history",
                    label: "Undo History",
                    type: "slider",
                    min: 0,
                    max: 50,
                    defaultValue: 10,
                    unit: "actions"
                },
                {
                    id: "auto_save",
                    label: "Auto Save",
                    type: "toggle",
                    defaultValue: true
                }
            ]
        },
        {
            id: "notifications",
            label: "NOTIFICATIONS",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$bell$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Bell$3e$__["Bell"],
            fields: [
                {
                    id: "dnd_toggle",
                    label: "Do Not Disturb",
                    type: "toggle",
                    defaultValue: false
                },
                {
                    id: "notification_sound",
                    label: "Notification Sound",
                    type: "dropdown",
                    options: [
                        "Default",
                        "Chime",
                        "Pulse",
                        "Silent"
                    ],
                    defaultValue: "Default"
                },
                {
                    id: "app_notifications",
                    label: "App Notifications",
                    type: "toggle",
                    defaultValue: true
                }
            ]
        }
    ],
    monitor: [
        {
            id: "analytics",
            label: "ANALYTICS",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chart$2d$column$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__BarChart3$3e$__["BarChart3"],
            fields: [
                {
                    id: "token_usage",
                    label: "Token Usage",
                    type: "text",
                    placeholder: "Usage"
                },
                {
                    id: "response_latency",
                    label: "Response Latency",
                    type: "text",
                    placeholder: "Latency"
                },
                {
                    id: "session_duration",
                    label: "Session Duration",
                    type: "text",
                    placeholder: "Duration"
                }
            ]
        },
        {
            id: "logs",
            label: "LOGS",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$file$2d$text$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__FileText$3e$__["FileText"],
            fields: [
                {
                    id: "system_logs",
                    label: "System Logs",
                    type: "text",
                    placeholder: "System"
                },
                {
                    id: "voice_logs",
                    label: "Voice Logs",
                    type: "text",
                    placeholder: "Voice"
                },
                {
                    id: "mcp_logs",
                    label: "MCP Logs",
                    type: "text",
                    placeholder: "MCP"
                },
                {
                    id: "export_logs",
                    label: "Export Logs",
                    type: "text",
                    placeholder: "Export"
                }
            ]
        },
        {
            id: "diagnostics",
            label: "DIAGNOSTICS",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$stethoscope$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Stethoscope$3e$__["Stethoscope"],
            fields: [
                {
                    id: "health_check",
                    label: "Health Check",
                    type: "text",
                    placeholder: "Run"
                },
                {
                    id: "lfm_benchmark",
                    label: "LFM Benchmark",
                    type: "text",
                    placeholder: "Benchmark"
                },
                {
                    id: "mcp_test",
                    label: "MCP Test",
                    type: "text",
                    placeholder: "Test MCP"
                }
            ]
        },
        {
            id: "updates",
            label: "UPDATES",
            icon: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$refresh$2d$cw$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__RefreshCw$3e$__["RefreshCw"],
            fields: [
                {
                    id: "update_channel",
                    label: "Update Channel",
                    type: "dropdown",
                    options: [
                        "Stable",
                        "Beta",
                        "Nightly"
                    ],
                    defaultValue: "Stable"
                },
                {
                    id: "check_updates",
                    label: "Check Updates",
                    type: "text",
                    placeholder: "Check"
                },
                {
                    id: "auto_update",
                    label: "Auto Update",
                    type: "toggle",
                    defaultValue: true
                }
            ]
        }
    ]
};
function useIsMobile() {
    const [isMobile, setIsMobile] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        const checkMobile = ()=>setIsMobile(window.innerWidth < 640);
        checkMobile();
        window.addEventListener("resize", checkMobile);
        return ()=>window.removeEventListener("resize", checkMobile);
    }, []);
    return isMobile;
}
function getSpiralPosition(baseAngle, radius, spinRotations) {
    const finalAngleRad = baseAngle * Math.PI / 180;
    return {
        x: Math.cos(finalAngleRad) * radius,
        y: Math.sin(finalAngleRad) * radius,
        rotation: spinRotations * 360
    };
}
const ICON_MAP = {
    Mic: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$mic$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Mic$3e$__["Mic"],
    Brain: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$brain$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Brain$3e$__["Brain"],
    Bot: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$bot$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Bot$3e$__["Bot"],
    Settings: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$settings$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Settings$3e$__["Settings"],
    Database: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$database$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Database$3e$__["Database"],
    Activity: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$activity$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Activity$3e$__["Activity"],
    Volume2: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$volume$2d$2$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Volume2$3e$__["Volume2"],
    Headphones: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$headphones$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Headphones$3e$__["Headphones"],
    Waveform: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$audio$2d$waveform$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__AudioWaveform$3e$__["AudioWaveform"],
    Link: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$link$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Link$3e$__["Link"],
    Cpu: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$cpu$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Cpu$3e$__["Cpu"],
    Sparkles: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sparkles$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Sparkles$3e$__["Sparkles"],
    MessageSquare: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$message$2d$square$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__MessageSquare$3e$__["MessageSquare"],
    Palette: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$palette$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Palette$3e$__["Palette"],
    Power: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$power$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Power$3e$__["Power"],
    Keyboard: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$keyboard$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Keyboard$3e$__["Keyboard"],
    Minimize2: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$minimize$2d$2$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Minimize2$3e$__["Minimize2"],
    RefreshCw: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$refresh$2d$cw$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__RefreshCw$3e$__["RefreshCw"],
    History: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$history$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__History$3e$__["History"],
    FileStack: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$file$2d$stack$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__FileStack$3e$__["FileStack"],
    Trash2: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$trash$2d$2$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Trash2$3e$__["Trash2"],
    Timer: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$timer$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Timer$3e$__["Timer"],
    Clock: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$clock$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Clock$3e$__["Clock"],
    BarChart3: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$chart$2d$column$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__BarChart3$3e$__["BarChart3"],
    DollarSign: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$dollar$2d$sign$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__DollarSign$3e$__["DollarSign"],
    TrendingUp: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$trending$2d$up$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__TrendingUp$3e$__["TrendingUp"],
    Wrench: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$wrench$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Wrench$3e$__["Wrench"],
    Layers: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$layers$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Layers$3e$__["Layers"],
    Star: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$star$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Star$3e$__["Star"],
    Monitor: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$monitor$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Monitor$3e$__["Monitor"],
    HardDrive: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$hard$2d$drive$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__HardDrive$3e$__["HardDrive"],
    Wifi: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$wifi$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Wifi$3e$__["Wifi"],
    Bell: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$bell$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Bell$3e$__["Bell"],
    Sliders: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$sliders$2d$vertical$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Sliders$3e$__["Sliders"],
    FileText: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$file$2d$text$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__FileText$3e$__["FileText"],
    Stethoscope: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$stethoscope$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Stethoscope$3e$__["Stethoscope"],
    Smile: __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$smile$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Smile$3e$__["Smile"]
};
// ===========================================
// MANUAL DRAG HOOK (Replaces useDragOrClick)
// Uses setPosition instead of startDragging to bypass Windows Snap Assist
// ===========================================
function useManualDragWindow(onClickAction) {
    const isDragging = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(false);
    const dragStartPos = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])({
        x: 0,
        y: 0
    });
    const windowStartPos = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])({
        x: 0,
        y: 0
    });
    const hasDragged = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(false);
    const handleMouseDown = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(async (e)=>{
        if (e.button !== 0) return;
        // Only enable dragging in Tauri app
        if (!getCurrentWindow) return;
        isDragging.current = true;
        hasDragged.current = false;
        dragStartPos.current = {
            x: e.screenX,
            y: e.screenY
        };
        const win = getCurrentWindow();
        const pos = await win.outerPosition();
        windowStartPos.current = {
            x: pos.x,
            y: pos.y
        };
        document.body.style.cursor = 'grabbing';
        document.body.style.userSelect = 'none';
    }, []);
    const handleMouseMove = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((e)=>{
        if (!isDragging.current) return;
        // Only enable dragging in Tauri app
        if (!getCurrentWindow || !PhysicalPosition) return;
        const dx = e.screenX - dragStartPos.current.x;
        const dy = e.screenY - dragStartPos.current.y;
        if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
            hasDragged.current = true;
        }
        const win = getCurrentWindow();
        win.setPosition(new PhysicalPosition(windowStartPos.current.x + dx, windowStartPos.current.y + dy));
    }, []);
    const handleMouseUp = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(()=>{
        isDragging.current = false;
        document.body.style.cursor = 'default';
        document.body.style.userSelect = '';
        // If we didn't drag significantly, it was a click
        if (!hasDragged.current) {
            onClickAction();
        }
    }, [
        onClickAction
    ]);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
        return ()=>{
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [
        handleMouseMove,
        handleMouseUp
    ]);
    return {
        handleMouseDown
    };
}
function IrisOrb({ isExpanded, onClick, centerLabel, size, glowColor }) {
    const { handleMouseDown } = useManualDragWindow(onClick);
    const [isWaking, setIsWaking] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
        className: "relative flex items-center justify-center rounded-full cursor-grab active:cursor-grabbing z-50 pointer-events-auto",
        style: {
            width: size,
            height: size
        },
        onMouseDown: handleMouseDown,
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                className: "absolute rounded-full pointer-events-none",
                style: {
                    inset: -70,
                    background: `radial-gradient(circle, ${glowColor}90 0%, ${glowColor}50 30%, transparent 70%)`,
                    filter: "blur(40px)"
                },
                animate: {
                    scale: [
                        1,
                        1.7,
                        1
                    ],
                    opacity: [
                        0.7,
                        1,
                        0.7
                    ]
                },
                transition: {
                    duration: 5,
                    repeat: Infinity,
                    ease: "easeInOut"
                }
            }, void 0, false, {
                fileName: "[project]/components/hexagonal-control-center.tsx",
                lineNumber: 357,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                className: "absolute rounded-full pointer-events-none",
                style: {
                    inset: -8,
                    background: `radial-gradient(circle at 30% 30%, ${glowColor}14, transparent 70%)`,
                    filter: "blur(8px)"
                },
                animate: {
                    scale: [
                        0.8,
                        1.4,
                        0.8
                    ],
                    opacity: [
                        0.7,
                        1,
                        0.7
                    ]
                },
                transition: {
                    duration: 3,
                    repeat: Infinity,
                    ease: "easeInOut"
                }
            }, void 0, false, {
                fileName: "[project]/components/hexagonal-control-center.tsx",
                lineNumber: 369,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                children: isWaking && centerLabel !== "IRIS" && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                    className: "absolute rounded-full pointer-events-none",
                    style: {
                        inset: -20,
                        backgroundColor: `${glowColor}99`
                    },
                    initial: {
                        opacity: 0,
                        scale: 0.8
                    },
                    animate: {
                        opacity: 1,
                        scale: 1.5
                    },
                    exit: {
                        opacity: 0,
                        scale: 2
                    },
                    transition: {
                        duration: 0.3
                    }
                }, void 0, false, {
                    fileName: "[project]/components/hexagonal-control-center.tsx",
                    lineNumber: 383,
                    columnNumber: 11
                }, this)
            }, void 0, false, {
                fileName: "[project]/components/hexagonal-control-center.tsx",
                lineNumber: 381,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                className: "absolute inset-0 rounded-full pointer-events-none overflow-hidden",
                style: {
                    background: 'transparent'
                },
                children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                    className: "absolute inset-0",
                    style: {
                        background: `conic-gradient(from 0deg at 50% 50%,
              transparent 0deg,
              transparent 88deg,
              rgba(255,255,255,0.15) 98deg,
              rgba(255,255,255,0.8) 100deg,
              rgba(255,255,255,0.15) 102deg,
              transparent 112deg,
              transparent 360deg)`
                    },
                    animate: {
                        rotate: 360
                    },
                    transition: {
                        duration: 4,
                        repeat: Infinity,
                        ease: "linear"
                    }
                }, void 0, false, {
                    fileName: "[project]/components/hexagonal-control-center.tsx",
                    lineNumber: 401,
                    columnNumber: 9
                }, this)
            }, void 0, false, {
                fileName: "[project]/components/hexagonal-control-center.tsx",
                lineNumber: 395,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                className: "absolute -inset-[3px] rounded-full pointer-events-none",
                style: {
                    padding: "3px",
                    background: `conic-gradient(from 0deg, 
            rgba(255,255,255,0) 0deg,
            rgba(255,255,255,0.5) 90deg,
            rgba(192,192,192,0.6) 180deg,
            rgba(255,255,255,0.5) 270deg,
            rgba(255,255,255,0) 360deg)`,
                    WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
                    WebkitMaskComposite: "xor"
                },
                animate: {
                    rotate: -360
                },
                transition: {
                    duration: 12,
                    repeat: Infinity,
                    ease: "linear"
                }
            }, void 0, false, {
                fileName: "[project]/components/hexagonal-control-center.tsx",
                lineNumber: 419,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                className: "absolute rounded-full pointer-events-none",
                style: {
                    inset: -3,
                    borderRadius: "50%",
                    padding: "3px",
                    background: `conic-gradient(from 0deg, transparent 0deg, ${glowColor}4d 90deg, ${glowColor}cc 180deg, ${glowColor}4d 270deg, transparent 360deg)`,
                    WebkitMask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
                    WebkitMaskComposite: "xor"
                },
                animate: {
                    rotate: 360
                },
                transition: {
                    duration: 10,
                    repeat: Infinity,
                    ease: "linear"
                }
            }, void 0, false, {
                fileName: "[project]/components/hexagonal-control-center.tsx",
                lineNumber: 437,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: "relative w-full h-full flex items-center justify-center rounded-full pointer-events-none",
                style: {
                    background: "rgba(255, 255, 255, 0.05)",
                    backdropFilter: "blur(20px)",
                    border: "1px solid rgba(255, 255, 255, 0.1)"
                },
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "absolute inset-0 rounded-full pointer-events-none",
                        style: {
                            background: `radial-gradient(circle at 30% 30%, ${glowColor}14, transparent 70%)`
                        }
                    }, void 0, false, {
                        fileName: "[project]/components/hexagonal-control-center.tsx",
                        lineNumber: 460,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                        mode: "wait",
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].span, {
                            className: "text-lg font-medium tracking-[0.2em] select-none pointer-events-none",
                            style: {
                                color: "#ffffff",
                                textShadow: '0 0 4px rgba(0,0,0,0.8), 0 2px 4px rgba(0,0,0,0.6)'
                            },
                            initial: {
                                scale: 0,
                                opacity: 0
                            },
                            animate: {
                                scale: 1,
                                opacity: 1
                            },
                            exit: {
                                scale: 0,
                                opacity: 0
                            },
                            transition: {
                                type: "spring",
                                stiffness: 300,
                                damping: 25
                            },
                            children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].span, {
                                animate: {
                                    textShadow: [
                                        `0 0 10px ${glowColor}4d`,
                                        `0 0 20px ${glowColor}99`,
                                        `0 0 10px ${glowColor}4d`
                                    ]
                                },
                                transition: {
                                    duration: 4,
                                    repeat: Infinity,
                                    ease: "easeInOut"
                                },
                                children: centerLabel
                            }, void 0, false, {
                                fileName: "[project]/components/hexagonal-control-center.tsx",
                                lineNumber: 478,
                                columnNumber: 13
                            }, this)
                        }, centerLabel, false, {
                            fileName: "[project]/components/hexagonal-control-center.tsx",
                            lineNumber: 466,
                            columnNumber: 11
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/components/hexagonal-control-center.tsx",
                        lineNumber: 465,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/components/hexagonal-control-center.tsx",
                lineNumber: 452,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/components/hexagonal-control-center.tsx",
        lineNumber: 351,
        columnNumber: 5
    }, this);
}
function HexagonalControlCenter() {
    const nav = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$NavigationContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useNavigation"])();
    const { getThemeConfig, theme: brandTheme, setTheme } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$contexts$2f$BrandColorContext$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useBrandColor"])();
    const theme = getThemeConfig();
    const themeGlowColor = theme.glow.color;
    // DEBUG: Log theme state
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        console.log('[Nav System] BrandColorContext theme:', brandTheme);
        console.log('[Nav System] Computed theme config:', theme.name, 'glow:', themeGlowColor);
    }, [
        brandTheme,
        theme,
        themeGlowColor
    ]);
    const { theme: wsTheme, confirmedNodes: wsConfirmedNodes, currentCategory, currentSubnode, selectCategory, selectSubnode, confirmMiniNode, updateTheme } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$hooks$2f$useIRISWebSocket$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useIRISWebSocket"])("ws://localhost:8000/ws/iris");
    const [currentView, setCurrentView] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    const [pendingView, setPendingView] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    const [exitingView, setExitingView] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    const [isExpanded, setIsExpanded] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    const [isTransitioning, setIsTransitioning] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    const [activeMiniNodeIndex, setActiveMiniNodeIndex] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    const isMobile = useIsMobile();
    // Refs for tracking navigation state and preventing stale closures
    const userNavigatedRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(false);
    const navLevelRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(nav.state.level);
    const nodeClickTimestampRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(null);
    // Update navLevelRef on every render to keep it fresh
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        navLevelRef.current = nav.state.level;
    }, [
        nav.state.level
    ]);
    // Ensure window starts interactive (solid, not click-through) - Tauri only
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        if (!getCurrentWindow) return;
        const setupWindow = async ()=>{
            const appWindow = await getCurrentWindow();
            await appWindow.setIgnoreCursorEvents(false);
        };
        setupWindow();
    }, []);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        // Skip backend sync if user has manually navigated
        if (userNavigatedRef.current) {
            console.log('[Nav System] Skipping backend sync - user has manually navigated');
            return;
        }
        // Skip if category is empty (user just cleared it)
        if (!currentCategory) {
            console.log('[Nav System] Skipping backend sync - currentCategory is empty');
            return;
        }
        console.log('[Nav System] Backend sync useEffect running:', {
            currentCategory,
            currentView,
            isTransitioning,
            pendingView,
            exitingView,
            navLevel: nav.state.level,
            isExpanded,
            condition: !isTransitioning && !pendingView && currentCategory !== currentView && !exitingView
        });
        // CRITICAL FIX: Don't auto-navigate to Level 3 on initial load/refresh
        // Only sync the view without advancing navigation level automatically
        // This prevents the "random main node on refresh" issue
        if (!isTransitioning && !pendingView && currentCategory !== currentView && !exitingView) {
            console.log('[Nav System] Setting currentView to currentCategory (without auto-navigating):', currentCategory);
            setCurrentView(currentCategory);
            // Only expand to show main nodes (Level 2), don't auto-select a main node
            // This prevents the backend from forcing Level 3 on refresh
            if (!isExpanded && nav.state.level === 1) {
                console.log('[Nav System] Expanding to main nodes (Level 2) from backend category');
                setIsExpanded(true);
                nav.expandToMain();
            }
        // Note: We intentionally do NOT call nav.selectMain() here
        // User must explicitly click a main node to reach Level 3
        }
        if (pendingView && currentCategory === pendingView) {
            setPendingView(null);
        }
    }, [
        currentCategory,
        currentView,
        exitingView,
        isTransitioning,
        pendingView,
        isExpanded,
        nav
    ]);
    const glowColor = themeGlowColor || "#00ff88";
    const activeSubnodeId = currentSubnode;
    const centerLabel = activeSubnodeId ? currentView && SUB_NODES[currentView]?.find((n)=>n.id === activeSubnodeId)?.label || "IRIS" : (currentView ? NODE_POSITIONS.find((n)=>n.id === currentView)?.label : "IRIS") || "IRIS";
    const confirmedNodes = wsConfirmedNodes.map((n)=>({
            id: n.id,
            label: n.label,
            icon: n.icon,
            orbitAngle: n.orbit_angle,
            values: n.values
        }));
    const irisSize = isMobile ? 110 : 140;
    const nodeSize = isMobile ? 72 : 90;
    const mainRadius = isMobile ? 140 : SPIN_CONFIG.radiusExpanded;
    const subRadius = isMobile ? 110 : SUBMENU_CONFIG.radius;
    const orbitRadius = isMobile ? 160 : ORBIT_CONFIG.radius;
    const handleNodeClick = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((nodeId, nodeLabel, hasSubnodes)=>{
        const currentNavLevel = nav.state.level;
        console.log('[Nav System] handleNodeClick START:', {
            nodeId,
            nodeLabel,
            hasSubnodes,
            currentView,
            isTransitioning,
            navLevel: currentNavLevel,
            timestamp: Date.now()
        });
        if (isTransitioning) {
            console.log('[Nav System] handleNodeClick blocked - isTransitioning');
            return;
        }
        // Navigate if:
        // 1. At Level 2 (main nodes showing) - clicking goes to Level 3
        // 2. At Level 3 but clicking a DIFFERENT main node - switch to that node's subnodes
        const shouldNavigate = currentNavLevel === 2 || currentNavLevel === 3 && nav.state.selectedMain !== nodeId;
        if (shouldNavigate) {
            console.log('[Nav System] Should navigate to subnodes:', {
                nodeId,
                fromLevel: currentNavLevel
            });
            if (SUB_NODES[nodeId]?.length > 0) {
                console.log('[Nav System] Found subnodes, proceeding with navigation');
                userNavigatedRef.current = true;
                setExitingView(currentNavLevel === 3 ? nav.state.selectedMain : "__main__");
                setIsTransitioning(true);
                setActiveMiniNodeIndex(null);
                setPendingView(nodeId);
                setCurrentView(nodeId);
                // If at Level 3, go back first then to new main
                if (currentNavLevel === 3) {
                    nav.goBack(); // Go from Level 3→2 first
                }
                // Use NavigationContext to advance to Level 3
                console.log('[Nav System] Calling nav.selectMain() for nodeId:', nodeId);
                nav.selectMain(nodeId);
                console.log('[Nav System] selectMain called:', {
                    nodeId,
                    level: nav.state.level
                });
                setTimeout(()=>{
                    console.log('[Nav System] Transition timeout completed');
                    setExitingView(null);
                    setIsTransitioning(false);
                    selectCategory(nodeId);
                    // Reset userNavigatedRef to allow backend sync again
                    userNavigatedRef.current = false;
                }, SPIN_CONFIG.spinDuration);
            } else {
                console.log('[Nav System] No subnodes found for nodeId:', nodeId);
            }
        } else {
            console.log('[Nav System] Skipping navigation:', {
                currentNavLevel,
                nodeId
            });
        }
    }, [
        isTransitioning,
        selectCategory,
        nav,
        currentView
    ]);
    const handleSubnodeClick = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((subnodeId)=>{
        // Read nav.state.level fresh to avoid stale closure
        const currentNavLevel = nav.state.level;
        console.log('[Nav System] handleSubnodeClick START:', {
            subnodeId,
            activeSubnodeId,
            currentView,
            navLevel: currentNavLevel,
            navSelectedMain: nav.state.selectedMain,
            navSelectedSub: nav.state.selectedSub
        });
        if (activeSubnodeId === subnodeId) {
            console.log('[Nav System] Deselecting subnode, going back to Level 3');
            selectSubnode(null);
            nav.goBack();
            setActiveMiniNodeIndex(null);
        } else {
            // Get mini nodes for this subnode and navigate to level 4
            const subnodeData = SUB_NODES[currentView]?.find((n)=>n.id === subnodeId);
            // Transform fields into proper MiniNode objects - each field becomes a card in the stack
            const fields = subnodeData?.fields || [];
            const miniNodes = fields.map((field, index)=>({
                    id: `${subnodeId}_${field.id}`,
                    label: field.label,
                    icon: "Settings",
                    fields: [
                        field
                    ]
                }));
            console.log('[Nav System] Attempting Level 4 navigation:', {
                subnodeId,
                subnodeFound: !!subnodeData,
                miniNodesCount: miniNodes.length,
                miniNodes: miniNodes
            });
            // CRITICAL: Call nav.selectSub() FIRST to trigger Level 4 navigation
            // This updates the navigation state and sets miniNodeStack
            nav.selectSub(subnodeId, miniNodes);
            // Update backend state
            selectSubnode(subnodeId);
        }
    }, [
        activeSubnodeId,
        currentView,
        nav,
        selectSubnode
    ]);
    const handleIrisClick = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((e)=>{
        // CRITICAL FIX: Read nav level from the ref which is updated every render
        const freshNavLevel = navLevelRef.current;
        console.log('[Nav System] handleIrisClick START:', {
            isTransitioning,
            activeSubnodeId,
            currentView,
            isExpanded,
            freshNavLevel,
            target: e?.target
        });
        // Check if a node was just clicked (within last 300ms) - prevents iris toggle when clicking nodes
        const timeSinceNodeClick = Date.now() - (nodeClickTimestampRef.current || 0);
        if (timeSinceNodeClick < 300) {
            console.log('[Nav System] handleIrisClick blocked - node was just clicked', timeSinceNodeClick, 'ms ago');
            return;
        }
        if (isTransitioning) {
            console.log('[Nav System] handleIrisClick blocked - isTransitioning');
            return;
        }
        // Use freshNavLevel to determine proper back navigation (not the stale closure value)
        const level = freshNavLevel;
        // DEFENSIVE: Prevent any back navigation if we're transitioning
        if (isTransitioning) {
            console.log('[Nav System] handleIrisClick blocked - isTransitioning');
            return;
        }
        // DEFENSIVE: Check if userNavigatedRef is already true (prevent double navigation)
        if (userNavigatedRef.current) {
            console.log('[Nav System] handleIrisClick blocked - userNavigatedRef already true');
            return;
        }
        console.log('[Nav System] handleIrisClick proceeding with level:', level);
        if (level === 4) {
            // Level 4: Mini nodes active -> go back to level 3 (subnodes)
            console.log('[Nav System] handleIrisClick: Level 4->3, deselecting subnode');
            userNavigatedRef.current = true;
            // IMPORTANT: Call nav.goBack() FIRST before clearing backend state
            // This ensures navigation state changes before backend sync can interfere
            nav.goBack();
            // Now clear backend state after navigation is initiated
            // Keep userNavigatedRef = true during this to prevent backend sync from interfering
            selectSubnode(null);
            setActiveMiniNodeIndex(null);
            // Reset userNavigatedRef AFTER a short delay to ensure navigation completes
            setTimeout(()=>{
                userNavigatedRef.current = false;
                console.log('[Nav System] userNavigatedRef reset after Level 4->3 navigation');
            }, 100);
        } else if (level === 3) {
            // Level 3: Subnodes showing -> go back to level 2 (main nodes)
            console.log('[Nav System] handleIrisClick: Level 3->2, going back to main nodes');
            userNavigatedRef.current = true;
            nav.goBack();
            // Clear the currentView to show main nodes instead of subnodes
            setExitingView(currentView || "__main__");
            setIsTransitioning(true);
            setTimeout(()=>{
                setCurrentView(null);
                setExitingView(null);
                setIsTransitioning(false);
                selectCategory("");
            // NOTE: Don't reset userNavigatedRef here - let it stay true until user selects a new node
            // This prevents backend sync from re-selecting the old category before it's cleared
            }, SPIN_CONFIG.spinDuration);
        } else if (level === 2) {
            // Level 2: Main nodes showing -> collapse to level 1 (idle)
            console.log('[Nav System] handleIrisClick: Level 2->1, collapsing to idle');
            userNavigatedRef.current = true;
            nav.collapseToIdle();
            setIsExpanded(false);
            // Clear backend category to prevent it from restoring on refresh
            selectCategory("");
        } else {
            // Level 1: Idle -> expand to level 2 (main nodes)
            console.log('[Nav System] handleIrisClick: Level 1->2, expanding');
            userNavigatedRef.current = true;
            nav.expandToMain();
            setIsExpanded(true);
        }
    }, [
        currentView,
        isExpanded,
        isTransitioning,
        activeSubnodeId,
        selectSubnode,
        selectCategory,
        nav
    ]);
    const currentNodes = currentView ? SUB_NODES[currentView].map((node, idx)=>({
            ...node,
            angle: idx * (360 / SUB_NODES[currentView].length) - 90,
            index: idx
        })) : NODE_POSITIONS.map((n)=>({
            ...n,
            fields: []
        }));
    const exitingNodes = exitingView ? exitingView === "__main__" ? NODE_POSITIONS.map((n)=>({
            ...n,
            fields: []
        })) : SUB_NODES[exitingView].map((node, idx)=>({
            ...node,
            angle: idx * (360 / SUB_NODES[exitingView].length) - 90,
            index: idx
        })) : null;
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: "relative w-full h-full flex items-center justify-center",
        style: {
            overflow: 'visible',
            pointerEvents: 'none' // Outer wrapper: click-through to desktop
        },
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            className: "relative",
            style: {
                width: 800,
                height: 800
            },
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                    className: "absolute rounded-full pointer-events-none",
                    style: {
                        width: 400,
                        height: 400,
                        left: "50%",
                        top: "50%",
                        marginLeft: -200,
                        marginTop: -200,
                        background: `radial-gradient(circle, ${glowColor}20 0%, ${glowColor}08 40%, transparent 70%)`
                    },
                    animate: {
                        scale: [
                            1,
                            1.2,
                            1
                        ],
                        opacity: [
                            0.5,
                            0.8,
                            0.5
                        ]
                    },
                    transition: {
                        duration: 8,
                        repeat: Infinity,
                        ease: "easeInOut"
                    }
                }, void 0, false, {
                    fileName: "[project]/components/hexagonal-control-center.tsx",
                    lineNumber: 838,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                    children: confirmedNodes.map((node)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                            className: "absolute flex items-center justify-center pointer-events-auto",
                            style: {
                                width: MINI_NODE_STACK_CONFIG.sizeConfirmed,
                                height: MINI_NODE_STACK_CONFIG.sizeConfirmed,
                                left: "50%",
                                top: "50%",
                                marginLeft: -MINI_NODE_STACK_CONFIG.sizeConfirmed / 2,
                                marginTop: -MINI_NODE_STACK_CONFIG.sizeConfirmed / 2
                            },
                            initial: {
                                scale: 0,
                                opacity: 0
                            },
                            animate: {
                                scale: 1,
                                x: Math.cos(node.orbitAngle * Math.PI / 180) * orbitRadius,
                                y: Math.sin(node.orbitAngle * Math.PI / 180) * orbitRadius,
                                opacity: 1
                            },
                            transition: {
                                type: "spring",
                                stiffness: 100,
                                damping: 15
                            },
                            children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: "w-full h-full flex flex-col items-center justify-center gap-1 rounded-2xl cursor-pointer",
                                style: {
                                    background: "rgba(255, 255, 255, 0.08)",
                                    backdropFilter: "blur(12px)",
                                    border: "1px solid rgba(255, 255, 255, 0.1)"
                                },
                                children: [
                                    /*#__PURE__*/ __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["default"].createElement(ICON_MAP[typeof node.icon === 'string' ? node.icon : 'Mic'] || __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$lucide$2d$react$2f$dist$2f$esm$2f$icons$2f$mic$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$export__default__as__Mic$3e$__["Mic"], {
                                        className: "w-5 h-5",
                                        style: {
                                            color: glowColor
                                        },
                                        strokeWidth: 1.5
                                    }),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        className: "text-[8px] font-medium tracking-wider text-muted-foreground",
                                        children: node.label
                                    }, void 0, false, {
                                        fileName: "[project]/components/hexagonal-control-center.tsx",
                                        lineNumber: 889,
                                        columnNumber: 17
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/components/hexagonal-control-center.tsx",
                                lineNumber: 876,
                                columnNumber: 15
                            }, this)
                        }, node.id, false, {
                            fileName: "[project]/components/hexagonal-control-center.tsx",
                            lineNumber: 856,
                            columnNumber: 13
                        }, this))
                }, void 0, false, {
                    fileName: "[project]/components/hexagonal-control-center.tsx",
                    lineNumber: 854,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                    className: "absolute left-1/2 top-1/2 flex items-center justify-center pointer-events-none z-10",
                    style: {
                        marginLeft: -(irisSize + 120) / 2,
                        marginTop: -(irisSize + 120) / 2,
                        width: irisSize + 120,
                        height: irisSize + 120
                    },
                    animate: {
                        scale: nav.state.level === 4 ? 0.43 : 1,
                        x: 0
                    },
                    transition: {
                        type: "spring",
                        stiffness: 200,
                        damping: 20,
                        duration: 0.5
                    },
                    children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        className: "pointer-events-auto",
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(IrisOrb, {
                            isExpanded: isExpanded,
                            onClick: handleIrisClick,
                            centerLabel: centerLabel,
                            size: irisSize,
                            glowColor: glowColor
                        }, void 0, false, {
                            fileName: "[project]/components/hexagonal-control-center.tsx",
                            lineNumber: 913,
                            columnNumber: 13
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/components/hexagonal-control-center.tsx",
                        lineNumber: 912,
                        columnNumber: 11
                    }, this)
                }, void 0, false, {
                    fileName: "[project]/components/hexagonal-control-center.tsx",
                    lineNumber: 898,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                    children: nav.state.level === 4 && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                        className: "absolute left-1/2 top-1/2 pointer-events-none z-[55]",
                        style: {
                            height: 2,
                            width: 200,
                            marginTop: -1,
                            marginLeft: 30,
                            background: `linear-gradient(90deg, 
                  rgba(255,255,255,0.8) 0%, 
                  rgba(192,192,192,0.9) 20%, 
                  rgba(255,255,255,0.95) 40%, 
                  rgba(192,192,192,0.9) 60%, 
                  rgba(255,255,255,0.8) 80%,
                  rgba(128,128,128,0.6) 100%)`,
                            boxShadow: '0 0 4px rgba(255,255,255,0.5)'
                        },
                        initial: {
                            opacity: 0,
                            scaleX: 0
                        },
                        animate: {
                            opacity: 1,
                            scaleX: 1
                        },
                        exit: {
                            opacity: 0,
                            scaleX: 0
                        },
                        transition: {
                            duration: 0.4
                        }
                    }, void 0, false, {
                        fileName: "[project]/components/hexagonal-control-center.tsx",
                        lineNumber: 926,
                        columnNumber: 13
                    }, this)
                }, void 0, false, {
                    fileName: "[project]/components/hexagonal-control-center.tsx",
                    lineNumber: 924,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                    children: nav.state.level === 4 && nav.state.miniNodeStack.length > 0 && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                        className: "absolute left-1/2 top-1/2 pointer-events-auto z-[200]",
                        style: {
                            marginLeft: 280,
                            marginTop: -160,
                            width: 240,
                            height: 420
                        },
                        initial: {
                            opacity: 0,
                            scale: 0.8,
                            x: -20
                        },
                        animate: {
                            opacity: 1,
                            scale: 1,
                            x: 0
                        },
                        exit: {
                            opacity: 0,
                            scale: 0.8,
                            x: -20
                        },
                        transition: {
                            duration: 0.4
                        },
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$mini$2d$node$2d$stack$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["MiniNodeStack"], {
                            miniNodes: nav.state.miniNodeStack
                        }, void 0, false, {
                            fileName: "[project]/components/hexagonal-control-center.tsx",
                            lineNumber: 966,
                            columnNumber: 15
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/components/hexagonal-control-center.tsx",
                        lineNumber: 953,
                        columnNumber: 13
                    }, this)
                }, void 0, false, {
                    fileName: "[project]/components/hexagonal-control-center.tsx",
                    lineNumber: 951,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                    children: (nav.state.level === 2 || nav.state.level === 3) && exitingNodes && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Fragment"], {
                        children: exitingNodes.map((node, idx)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$iris$2f$prism$2d$node$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["PrismNode"], {
                                node: node,
                                angle: node.angle,
                                radius: exitingView ? subRadius : mainRadius,
                                nodeSize: nodeSize,
                                onClick: ()=>{},
                                spinRotations: exitingView ? SUBMENU_CONFIG.rotations : SPIN_CONFIG.rotations,
                                spinDuration: exitingView ? SUBMENU_CONFIG.spinDuration : SPIN_CONFIG.spinDuration,
                                staggerIndex: idx,
                                isCollapsing: true,
                                isActive: false,
                                spinConfig: SPIN_CONFIG
                            }, `exit-${node.id}`, false, {
                                fileName: "[project]/components/hexagonal-control-center.tsx",
                                lineNumber: 976,
                                columnNumber: 17
                            }, this))
                    }, void 0, false)
                }, void 0, false, {
                    fileName: "[project]/components/hexagonal-control-center.tsx",
                    lineNumber: 972,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                    children: (nav.state.level === 2 || nav.state.level === 3) && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Fragment"], {
                        children: currentNodes.filter((node)=>!activeSubnodeId || node.id !== activeSubnodeId).map((node, idx)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$components$2f$iris$2f$prism$2d$node$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["PrismNode"], {
                                node: node,
                                angle: node.angle,
                                radius: currentView ? subRadius : mainRadius,
                                nodeSize: nodeSize,
                                onClick: (e)=>{
                                    // Track click timestamp to prevent iris orb toggle
                                    nodeClickTimestampRef.current = Date.now();
                                    // Stop event from bubbling to iris orb handler
                                    e?.stopPropagation();
                                    currentView ? handleSubnodeClick(node.id) : handleNodeClick(node.id, node.label, node.hasSubnodes);
                                },
                                spinRotations: currentView ? SUBMENU_CONFIG.rotations : SPIN_CONFIG.rotations,
                                spinDuration: currentView ? SUBMENU_CONFIG.spinDuration : SPIN_CONFIG.spinDuration,
                                staggerIndex: idx,
                                isCollapsing: false,
                                isActive: activeSubnodeId === node.id,
                                spinConfig: SPIN_CONFIG
                            }, node.id, false, {
                                fileName: "[project]/components/hexagonal-control-center.tsx",
                                lineNumber: 1002,
                                columnNumber: 17
                            }, this))
                    }, void 0, false)
                }, void 0, false, {
                    fileName: "[project]/components/hexagonal-control-center.tsx",
                    lineNumber: 996,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$components$2f$AnimatePresence$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["AnimatePresence"], {
                    children: nav.state.level === 1 && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].div, {
                        className: "absolute bottom-40 left-1/2 -translate-x-1/2 pointer-events-none",
                        initial: {
                            opacity: 0,
                            y: 10
                        },
                        animate: {
                            opacity: 1,
                            y: 0
                        },
                        exit: {
                            opacity: 0,
                            y: 10
                        },
                        transition: {
                            delay: 0.5,
                            duration: 0.4
                        },
                        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$framer$2d$motion$2f$dist$2f$es$2f$render$2f$components$2f$motion$2f$proxy$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["motion"].span, {
                            className: "text-xs text-muted-foreground/60 tracking-widest uppercase",
                            animate: {
                                opacity: [
                                    0.4,
                                    0.8,
                                    0.4
                                ]
                            },
                            transition: {
                                duration: 3,
                                repeat: Infinity,
                                ease: "easeInOut"
                            },
                            children: "TAP IRIS TO EXPAND"
                        }, void 0, false, {
                            fileName: "[project]/components/hexagonal-control-center.tsx",
                            lineNumber: 1037,
                            columnNumber: 15
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/components/hexagonal-control-center.tsx",
                        lineNumber: 1030,
                        columnNumber: 13
                    }, this)
                }, void 0, false, {
                    fileName: "[project]/components/hexagonal-control-center.tsx",
                    lineNumber: 1028,
                    columnNumber: 9
                }, this)
            ]
        }, void 0, true, {
            fileName: "[project]/components/hexagonal-control-center.tsx",
            lineNumber: 832,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/components/hexagonal-control-center.tsx",
        lineNumber: 824,
        columnNumber: 5
    }, this);
}
}),
];

//# sourceMappingURL=_e147a7da._.js.map