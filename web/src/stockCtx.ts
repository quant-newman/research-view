import { createContext, useContext } from "react";

// 全站任意处点股票 → 打开个股详情弹层。传 code(A股6位/美股ticker)或 name。
export type StockSel = { code?: string; name?: string };
export const StockCtx = createContext<(s: StockSel) => void>(() => {});
export const useOpenStock = () => useContext(StockCtx);
