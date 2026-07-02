import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

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
