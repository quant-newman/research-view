// 复盘页分页纯函数(无 React/DOM 依赖):单独成 .js 模块,node --test 可直测边界
// (0/1/8/9 篇、数据缩减页码越界回合法页),组件只消费不再自算。
export const PER_PAGE = 8;

/** 总页数:0 篇也至少 1 页(空态页仍是合法页,分页条按 1/1 显示)。 */
export function totalPages(total, perPage = PER_PAGE) {
  return Math.max(1, Math.ceil(Math.max(0, total) / perPage));
}

/** 页码钳制到 [1, totalPages]:数据变化导致当前页越界时自动回到合法页。 */
export function clampPage(page, total, perPage = PER_PAGE) {
  const tp = totalPages(total, perPage);
  if (!Number.isFinite(page) || page < 1) return 1;
  return Math.min(Math.trunc(page), tp);
}

/** 当前页切片区间 [start, end)(先钳制页码;完整正文仍可经翻页访问,永不截断总集)。 */
export function pageSlice(page, total, perPage = PER_PAGE) {
  const p = clampPage(page, total, perPage);
  const start = (p - 1) * perPage;
  return { page: p, start, end: Math.min(start + perPage, Math.max(0, total)) };
}
