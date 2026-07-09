import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// Service Worker:Web Push 通知接收(sw.js;iOS 需 HTTPS+加入主屏幕才有推送能力)。
// 通知点击时 SW 发 notif-navigate(iOS 不支持 client.navigate),页面整页跳转——
// 目标 URL 形如 /?stock=CODE,App 挂载时读参直达个股详情。
// 注意:必须 onmessage 赋值(自动开闸消息队列)——addEventListener 不调 startMessages()
// 时 SW 消息永远滞留队列,点通知只聚焦不跳转(2026-07-10 真机踩坑)。
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
  navigator.serviceWorker.onmessage = (e) => {
    if (e.data?.type === "notif-navigate" && e.data.url) location.href = e.data.url;
  };
}

// 顶层错误边界:渲染期抛错(如数据结构漂移)显示错误信息,而不是整页白屏。
class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error)
      return (
        <div style={{ padding: 24, color: "#e5484d", fontFamily: "monospace", fontSize: 14 }}>
          页面渲染出错(数据结构可能与前端不匹配):{String(this.state.error)}
        </div>
      );
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
